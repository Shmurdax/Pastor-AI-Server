import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

const _navy = Color(0xFF1B264F);

/// Non-web placeholder — Stripe Embedded Checkout is web-only in this app.
class StripeEmbeddedCheckout extends StatelessWidget {
  const StripeEmbeddedCheckout({
    super.key,
    required this.publishableKey,
    required this.clientSecret,
    this.height = 480,
    this.onComplete,
  });

  final String publishableKey;
  final String clientSecret;
  final double height;
  final VoidCallback? onComplete;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: height,
      alignment: Alignment.center,
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: const Color(0xFFF8F7F4),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.black12),
      ),
      child: Text(
        'Secure Stripe card fields are available in the web app. '
        'Open this checkout page in a browser to pay.',
        textAlign: TextAlign.center,
        style: GoogleFonts.figtree(color: _navy, height: 1.4),
      ),
    );
  }
}
