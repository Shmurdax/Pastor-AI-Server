// ignore_for_file: avoid_web_libraries_in_flutter, deprecated_member_use

import 'dart:async';
import 'dart:html' as html;
import 'dart:ui_web' as ui_web;

import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

const _navy = Color(0xFF1B264F);
const _gold = Color(0xFFD4AF37);

/// Stripe Embedded Checkout via a same-origin iframe relay page.
///
/// Mounting Stripe directly in [HtmlElementView] can freeze Flutter web; the
/// relay isolates Stripe.js from the Flutter canvas (same pattern as Vimeo).
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
  html.IFrameElement? _iframe;
  html.EventListener? _messageListener;
  bool _loading = true;
  bool _initialized = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _viewSeq += 1;
    _viewType = 'stripe-checkout-relay-$_viewSeq';

    _messageListener = _onWindowMessage;
    html.window.addEventListener('message', _messageListener);

    ui_web.platformViewRegistry.registerViewFactory(_viewType, (int viewId) {
      final iframe = html.IFrameElement()
        ..src = '/stripe_checkout_embed.html'
        ..style.border = 'none'
        ..style.width = '100%'
        ..style.height = '100%'
        ..allow = 'payment *';
      _iframe = iframe;
      return iframe;
    });
  }

  void _onWindowMessage(html.Event event) {
    final messageEvent = event as html.MessageEvent;
    if (messageEvent.origin != html.window.location.origin) return;

    final data = messageEvent.data;
    if (data is! Map) return;
    if (data['source'] != 'pastor-stripe-checkout') return;

    switch (data['type']) {
      case 'loaded':
        _sendInit();
      case 'ready':
        if (mounted) setState(() => _loading = false);
      case 'complete':
        widget.onComplete?.call();
      case 'error':
        if (mounted) {
          setState(() {
            _loading = false;
            _error = (data['message'] as String?) ?? 'Checkout failed.';
          });
        }
    }
  }

  void _sendInit() {
    if (_initialized) return;
    final iframe = _iframe;
    if (iframe == null) return;
    _initialized = true;
    iframe.contentWindow?.postMessage(
      {
        'source': 'pastor-stripe-parent',
        'type': 'stripe-init',
        'publishableKey': widget.publishableKey,
        'clientSecret': widget.clientSecret,
      },
      html.window.location.origin,
    );
  }

  @override
  void dispose() {
    final listener = _messageListener;
    if (listener != null) {
      html.window.removeEventListener('message', listener);
    }
    _iframe?.contentWindow?.postMessage(
      {'source': 'pastor-stripe-parent', 'type': 'stripe-destroy'},
      html.window.location.origin,
    );
    super.dispose();
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

    return SizedBox(
      height: widget.height,
      width: double.infinity,
      child: Stack(
        children: [
          Positioned.fill(
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
      ),
    );
  }
}
