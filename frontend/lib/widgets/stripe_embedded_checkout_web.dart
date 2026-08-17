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
    this.height = 520,
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
        ..style.minHeight = '${widget.height.toInt()}px';
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
      for (var i = 0; i < 50; i++) {
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
    await completer.future;

    for (var i = 0; i < 50; i++) {
      if (ready()) return;
      await Future<void>.delayed(const Duration(milliseconds: 50));
    }
    if (!ready()) {
      throw StateError('Stripe.js loaded but window.Stripe is unavailable.');
    }
  }

  Future<void> _mountCheckout() async {
    try {
      await _ensureStripeJs();
      await Future<void>.delayed(const Duration(milliseconds: 50));
      for (var i = 0; i < 40; i++) {
        if (web.document.getElementById(_elementId) != null) break;
        await Future<void>.delayed(const Duration(milliseconds: 50));
      }

      final stripeFactory = web.window.getProperty('Stripe'.toJS) as JSFunction;
      final stripe = stripeFactory.callAsConstructor(widget.publishableKey.toJS) as JSObject;

      // fetchClientSecret must return a Promise<string>
      JSPromise<JSString> fetchClientSecret(JSAny? _) {
        return Future<JSString>.value(widget.clientSecret.toJS).toJS;
      }

      final options = JSObject();
      options['fetchClientSecret'] = fetchClientSecret.toJS;
      final onComplete = widget.onComplete;
      if (onComplete != null) {
        void handleComplete() {
          onComplete();
        }

        options['onComplete'] = handleComplete.toJS;
      }

      final checkoutPromise = stripe.callMethod(
        'initEmbeddedCheckout'.toJS,
        options,
      ) as JSPromise<JSAny?>;
      final checkout = (await checkoutPromise.toDart)! as JSObject;
      _checkout = checkout;
      checkout.callMethod('mount'.toJS, '#$_elementId'.toJS);

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
          child: HtmlElementView(viewType: _viewType),
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
