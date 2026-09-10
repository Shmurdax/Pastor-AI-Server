import 'dart:async';
import 'dart:js_interop';
import 'dart:js_interop_unsafe';

import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:web/web.dart' as web;

const _navy = Color(0xFF1B264F);
const _gold = Color(0xFFD4AF37);

/// Stripe Embedded Checkout (card + billing fields) for Flutter web.
///
/// Mounts into a `position: fixed` overlay on `document.body` rather than an
/// [HtmlElementView]. Flutter web sets `overflow: hidden` on `html`/`body` and
/// clips platform views, which cuts off Stripe's tall iframe and blocks scroll
/// to the Confirm button. A body-level overlay with its own `overflow-y: auto`
/// restores normal scrolling.
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

  late final String _elementId;
  late final String _overlayId;
  String? _error;
  bool _loading = true;
  JSObject? _checkout;
  web.HTMLDivElement? _overlay;

  @override
  void initState() {
    super.initState();
    _viewSeq += 1;
    _elementId = 'stripe-embed-$_viewSeq';
    _overlayId = 'stripe-overlay-$_viewSeq';
    unawaited(_mountCheckout());
  }

  @override
  void dispose() {
    try {
      _checkout?.callMethod('destroy'.toJS);
    } catch (_) {}
    _removeOverlay();
    super.dispose();
  }

  void _removeOverlay() {
    try {
      _overlay?.remove();
    } catch (_) {}
    _overlay = null;
    // Restore page scroll lock used by Flutter web shell.
    web.document.documentElement?.style.overflow = 'hidden';
    web.document.body?.style.overflow = 'hidden';
  }

  web.HTMLDivElement _ensureOverlay() {
    final existing = _overlay;
    if (existing != null) return existing;

    // Allow the overlay itself to scroll (Flutter locks html/body).
    web.document.documentElement?.style.overflow = 'hidden';
    web.document.body?.style.overflow = 'hidden';

    final overlay = web.HTMLDivElement()
      ..id = _overlayId
      ..style.position = 'fixed'
      ..style.top = '0'
      ..style.left = '0'
      ..style.right = '0'
      ..style.bottom = '0'
      ..style.width = '100%'
      ..style.height = '100%'
      ..style.zIndex = '100000'
      ..style.backgroundColor = '#ffffff'
      ..style.overflowY = 'scroll'
      ..style.overflowX = 'hidden'
      ..style.boxSizing = 'border-box'
      ..style.setProperty('-webkit-overflow-scrolling', 'touch')
      ..style.setProperty('overscroll-behavior', 'contain');

    final shell = web.HTMLDivElement()
      ..style.maxWidth = '640px'
      ..style.margin = '0 auto'
      ..style.padding = '16px 16px 64px'
      ..style.boxSizing = 'border-box';

    final header = web.HTMLDivElement()
      ..style.display = 'flex'
      ..style.alignItems = 'center'
      ..style.gap = '12px'
      ..style.marginBottom = '12px';

    final back = web.HTMLButtonElement()
      ..type = 'button'
      ..textContent = '← Back'
      ..style.border = '1px solid #d0d4e0'
      ..style.backgroundColor = '#ffffff'
      ..style.color = '#1B264F'
      ..style.borderRadius = '10px'
      ..style.padding = '8px 14px'
      ..style.cursor = 'pointer'
      ..style.fontFamily = 'Figtree, system-ui, sans-serif'
      ..style.fontSize = '14px'
      ..style.fontWeight = '600';
    back.addEventListener(
      'click',
      (web.Event _) {
        if (!mounted) return;
        Navigator.of(context).maybePop();
      }.toJS,
    );

    final title = web.HTMLHeadingElement.h1()
      ..textContent = 'Complete your Premium plan'
      ..style.margin = '0'
      ..style.fontSize = '20px'
      ..style.fontWeight = '700'
      ..style.color = '#1B264F'
      ..style.fontFamily = 'Figtree, system-ui, sans-serif';

    header.append(back);
    header.append(title);

    final hint = web.HTMLParagraphElement()
      ..textContent =
          'Scroll this page to reach Confirm / Subscribe at the bottom of the form.'
      ..style.margin = '0 0 16px'
      ..style.fontSize = '13px'
      ..style.lineHeight = '1.4'
      ..style.color = '#667085'
      ..style.fontFamily = 'Figtree, system-ui, sans-serif';

    final mount = web.HTMLDivElement()
      ..id = _elementId
      ..style.width = '100%'
      ..style.minHeight = '480px'
      ..style.border = 'none'
      ..style.boxSizing = 'border-box';
    mount.setAttribute('allow', 'payment *');

    shell.append(header);
    shell.append(hint);
    shell.append(mount);
    overlay.append(shell);
    web.document.body!.append(overlay);

    _overlay = overlay;
    return overlay;
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

  Future<void> _mountCheckout() async {
    try {
      if (widget.publishableKey.isEmpty || widget.clientSecret.isEmpty) {
        throw StateError('Missing Stripe publishable key or client secret.');
      }
      if (widget.clientSecret.contains('paste_here') ||
          widget.publishableKey.contains('paste_here')) {
        throw StateError('Stripe keys still look like placeholders.');
      }

      _ensureOverlay();
      await _ensureStripeJs();

      final stripeFactory = web.window.getProperty('Stripe'.toJS) as JSFunction;
      final stripe =
          stripeFactory.callAsConstructor(widget.publishableKey.toJS) as JSObject;

      // Stripe requires exactly one of clientSecret or fetchClientSecret.
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

      // After Stripe sizes its iframe, scroll hint stays useful; nudge to top.
      _overlay?.scrollTop = 0;

      if (mounted) setState(() => _loading = false);
    } catch (e) {
      _removeOverlay();
      if (mounted) {
        setState(() {
          _loading = false;
          _error = e.toString().replaceFirst(RegExp(r'^Exception:\s*'), '');
        });
      }
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

    // Payment UI lives in the DOM overlay above the Flutter view.
    return SizedBox(
      height: widget.height,
      width: double.infinity,
      child: DecoratedBox(
        decoration: BoxDecoration(
          color: Colors.white.withValues(alpha: 0.92),
          borderRadius: BorderRadius.circular(16),
        ),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            if (_loading) ...[
              const CircularProgressIndicator(color: _navy),
              const SizedBox(height: 12),
              Text(
                'Loading secure payment form…',
                style: GoogleFonts.figtree(color: _navy),
              ),
            ] else ...[
              Icon(Icons.open_in_browser, color: _navy.withValues(alpha: 0.7)),
              const SizedBox(height: 12),
              Text(
                'Payment form is open in the overlay.',
                textAlign: TextAlign.center,
                style: GoogleFonts.figtree(color: _navy),
              ),
              const SizedBox(height: 4),
              Text(
                'Scroll there to reach Confirm.',
                textAlign: TextAlign.center,
                style: GoogleFonts.figtree(fontSize: 13, color: Colors.black54),
              ),
            ],
            const SizedBox(height: 8),
            Text(
              'Powered by Stripe',
              style: GoogleFonts.figtree(fontSize: 12, color: _gold),
            ),
          ],
        ),
      ),
    );
  }
}
