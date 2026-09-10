import 'dart:async';
import 'dart:js_interop';
import 'dart:js_interop_unsafe';
import 'dart:ui_web' as ui_web;

import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:web/web.dart' as web;

const _navy = Color(0xFF1B264F);
const _gold = Color(0xFFD4AF37);

/// Stripe Embedded Checkout (card + billing fields) for Flutter web.
class StripeEmbeddedCheckout extends StatefulWidget {
  const StripeEmbeddedCheckout({
    super.key,
    required this.publishableKey,
    required this.clientSecret,
    this.height = 1100,
    this.onComplete,
  });

  final String publishableKey;
  final String clientSecret;
  final double height;
  final VoidCallback? onComplete;

  @override
  State<StripeEmbeddedCheckout> createState() => _StripeEmbeddedCheckoutState();
}

class _StripeEmbeddedCheckoutState extends State<StripeEmbeddedCheckout> {
  static int _viewSeq = 0;

  late final String _viewType;
  late final String _elementId;
  final Completer<void> _domReady = Completer<void>();
  String? _error;
  bool _loading = true;
  JSObject? _checkout;

  @override
  void initState() {
    super.initState();
    _viewSeq += 1;
    _elementId = 'stripe-embed-$_viewSeq';
    _viewType = 'stripe-embedded-checkout-$_viewSeq';

    ui_web.platformViewRegistry.registerViewFactory(_viewType, (int viewId) {
      final div = web.HTMLDivElement()
        ..id = _elementId
        ..style.width = '100%'
        ..style.height = '100%'
        ..style.minHeight = '${widget.height.toInt()}px'
        ..style.border = 'none'
        // Flutter's outer scroll does not move HtmlElementView contents —
        // keep Stripe's form scrollable inside this host element.
        ..style.overflowY = 'auto'
        ..style.overflowX = 'hidden'
        ..style.boxSizing = 'border-box';
      div.style.setProperty('-webkit-overflow-scrolling', 'touch');
      // Ensure payment iframes can use Payment Request / Link where supported.
      div.setAttribute('allow', 'payment *');
      return div;
    });

    unawaited(_mountCheckout());
  }

  @override
  void dispose() {
    try {
      _checkout?.callMethod('destroy'.toJS);
    } catch (_) {}
    super.dispose();
  }

  Future<void> _ensureStripeJs() async {
    bool ready() {
      final stripe = web.window.getProperty('Stripe'.toJS);
      return stripe != null;
    }

    if (web.document.querySelector('script[data-pastor-stripe="1"]') != null) {
      for (var i = 0; i < 100; i++) {
        if (ready()) return;
        await Future<void>.delayed(const Duration(milliseconds: 50));
      }
      if (ready()) return;
    }

    final completer = Completer<void>();
    final script = web.HTMLScriptElement()
      ..src = 'https://js.stripe.com/v3/'
      ..async = true;
    script.setAttribute('data-pastor-stripe', '1');
    script.onload = (web.Event _) {
      if (!completer.isCompleted) completer.complete();
    }.toJS;
    script.onerror = (web.Event _) {
      if (!completer.isCompleted) {
        completer.completeError(StateError('Failed to load Stripe.js'));
      }
    }.toJS;
    web.document.head!.append(script);
    await completer.future.timeout(
      const Duration(seconds: 20),
      onTimeout: () => throw TimeoutException(
        'Timed out loading Stripe.js from js.stripe.com',
      ),
    );

    for (var i = 0; i < 100; i++) {
      if (ready()) return;
      await Future<void>.delayed(const Duration(milliseconds: 50));
    }
    if (!ready()) {
      throw StateError('Stripe.js loaded but window.Stripe is unavailable.');
    }
  }

  /// Prefer current Stripe.js API; fall back for older bundles.
  Future<JSObject> _createEmbeddedCheckout(
    JSObject stripe,
    JSObject options,
  ) async {
    const methodNames = <String>[
      'createEmbeddedCheckoutPage',
      'initEmbeddedCheckout',
    ];
    String? methodName;
    for (final name in methodNames) {
      if (stripe.getProperty(name.toJS) != null) {
        methodName = name;
        break;
      }
    }
    if (methodName == null) {
      throw StateError(
        'Stripe.js is missing createEmbeddedCheckoutPage. '
        'Hard-refresh the page (Ctrl+Shift+R) and try again.',
      );
    }

    final raw = stripe.callMethod(methodName.toJS, options);
    if (raw == null) {
      throw StateError('Stripe.$methodName returned null');
    }

    final result = await (raw as JSPromise<JSAny?>).toDart.timeout(
      const Duration(seconds: 45),
      onTimeout: () => throw TimeoutException(
        'Stripe checkout form timed out while initializing. '
        'Check that your publishable key matches the secret key mode '
        '(both test or both live), then hard-refresh and try again.',
      ),
    );
    if (result == null) {
      throw StateError('Stripe.$methodName resolved to null');
    }
    return result as JSObject;
  }

  Future<void> _waitForDom() async {
    // Prefer the platform-view callback; also poll in case it already landed.
    for (var i = 0; i < 80; i++) {
      if (web.document.getElementById(_elementId) != null) return;
      if (_domReady.isCompleted) return;
      await Future<void>.delayed(const Duration(milliseconds: 50));
    }
    await _domReady.future.timeout(
      const Duration(seconds: 5),
      onTimeout: () {},
    );
    if (web.document.getElementById(_elementId) == null) {
      throw StateError(
        'Payment form container failed to mount in the page. '
        'Hard-refresh and try again.',
      );
    }
  }

  Future<void> _mountCheckout() async {
    try {
      if (widget.publishableKey.isEmpty || widget.clientSecret.isEmpty) {
        throw StateError('Missing Stripe publishable key or client secret.');
      }
      if (widget.clientSecret.contains('paste_here') ||
          widget.publishableKey.contains('paste_here')) {
        throw StateError('Stripe keys still look like placeholders.');
      }

      await _ensureStripeJs();
      await _waitForDom();

      final stripeFactory = web.window.getProperty('Stripe'.toJS) as JSFunction;
      final stripe =
          stripeFactory.callAsConstructor(widget.publishableKey.toJS) as JSObject;

      // Stripe requires exactly one of clientSecret or fetchClientSecret.
      // Dart→JS Promise interop for fetchClientSecret is fragile on Flutter web
      // and can hang forever, so pass clientSecret only (still supported).
      final options = JSObject();
      options['clientSecret'] = widget.clientSecret.toJS;
      final onComplete = widget.onComplete;
      if (onComplete != null) {
        void handleComplete() {
          onComplete();
        }

        options['onComplete'] = handleComplete.toJS;
      }

      final checkout = await _createEmbeddedCheckout(stripe, options);
      _checkout = checkout;
      checkout.callMethod('mount'.toJS, '#$_elementId'.toJS);
      // Stripe injects its iframe asynchronously — retry scroll setup briefly.
      _ensureHostScrollable();
      unawaited(() async {
        for (final ms in [200, 500, 1000, 2000]) {
          await Future<void>.delayed(Duration(milliseconds: ms));
          if (!mounted) return;
          _ensureHostScrollable();
        }
      }());

      if (mounted) setState(() => _loading = false);
    } catch (e) {
      if (mounted) {
        setState(() {
          _loading = false;
          _error = e.toString().replaceFirst(RegExp(r'^Exception:\s*'), '');
        });
      }
    }
  }

  void _ensureHostScrollable() {
    final el = web.document.getElementById(_elementId);
    if (el == null) return;
    final host = el as web.HTMLElement;
    host.style.overflowY = 'auto';
    host.style.overflowX = 'hidden';
    host.style.height = '100%';
    host.style.maxHeight = '100%';
    host.style.setProperty('-webkit-overflow-scrolling', 'touch');
    // Stripe injects an iframe; keep the host as the scroll container.
    final frames = host.querySelectorAll('iframe');
    for (var i = 0; i < frames.length; i++) {
      final frame = frames.item(i);
      if (frame == null) continue;
      final iframe = frame as web.HTMLElement;
      iframe.style.width = '100%';
      iframe.style.border = '0';
      iframe.style.display = 'block';
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_error != null) {
      return Container(
        height: widget.height,
        alignment: Alignment.center,
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(
          color: Colors.red.shade50,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: Colors.red.shade200),
        ),
        child: Text(
          _error!,
          textAlign: TextAlign.center,
          style: GoogleFonts.figtree(color: Colors.red.shade800, height: 1.4),
        ),
      );
    }

    return Stack(
      children: [
        SizedBox(
          height: widget.height,
          width: double.infinity,
          child: HtmlElementView(
            viewType: _viewType,
            onPlatformViewCreated: (_) {
              if (!_domReady.isCompleted) _domReady.complete();
            },
          ),
        ),
        if (_loading)
          Positioned.fill(
            child: DecoratedBox(
              decoration: BoxDecoration(
                color: Colors.white.withValues(alpha: 0.85),
                borderRadius: BorderRadius.circular(16),
              ),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const CircularProgressIndicator(color: _navy),
                  const SizedBox(height: 12),
                  Text(
                    'Loading secure payment form…',
                    style: GoogleFonts.figtree(color: _navy),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    'Powered by Stripe',
                    style: GoogleFonts.figtree(fontSize: 12, color: _gold),
                  ),
                ],
              ),
            ),
          ),
      ],
    );
  }
}
