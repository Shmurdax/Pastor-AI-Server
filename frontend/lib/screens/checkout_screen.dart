import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

const _navy = Color(0xFF1B264F);
const _gold = Color(0xFFD4AF37);
const _pink = Color(0xFFa1375a);

enum BillingPeriod { monthly, yearly }

/// Generic checkout template for Premium. Payment wiring comes later.
class CheckoutScreen extends StatelessWidget {
  const CheckoutScreen({
    super.key,
    this.billingPeriod = BillingPeriod.monthly,
  });

  final BillingPeriod billingPeriod;

  String get _periodLabel =>
      billingPeriod == BillingPeriod.monthly ? 'Monthly' : 'Yearly';

  String get _priceLabel =>
      billingPeriod == BillingPeriod.monthly ? '\$15.00' : '\$150.00';

  String get _pricePeriod =>
      billingPeriod == BillingPeriod.monthly ? '/ month' : '/ year';

  @override
  Widget build(BuildContext context) {
    final isMobile = MediaQuery.of(context).size.width < 600;

    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        backgroundColor: Colors.white,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, color: _navy),
          onPressed: () => Navigator.of(context).pop(),
        ),
        title: Text(
          'Checkout',
          style: GoogleFonts.figtree(
            color: _navy,
            fontWeight: FontWeight.bold,
          ),
        ),
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: EdgeInsets.all(isMobile ? 24 : 40),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 520),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  'Complete your Premium plan',
                  textAlign: TextAlign.center,
                  style: GoogleFonts.figtree(
                    fontSize: isMobile ? 26 : 32,
                    fontWeight: FontWeight.bold,
                    color: _navy,
                  ),
                ),
                const SizedBox(height: 8),
                Center(
                  child: Container(height: 2, width: 48, color: _gold),
                ),
                const SizedBox(height: 28),
                Container(
                  padding: const EdgeInsets.all(24),
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(24),
                    gradient: const LinearGradient(
                      colors: [_pink, _navy],
                      begin: Alignment.topLeft,
                      end: Alignment.bottomRight,
                    ),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Premium',
                        style: GoogleFonts.figtree(
                          fontSize: 22,
                          fontWeight: FontWeight.bold,
                          color: Colors.white,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        _periodLabel,
                        style: GoogleFonts.figtree(
                          fontSize: 14,
                          color: Colors.white70,
                        ),
                      ),
                      const SizedBox(height: 20),
                      Row(
                        crossAxisAlignment: CrossAxisAlignment.end,
                        children: [
                          Text(
                            _priceLabel,
                            style: GoogleFonts.figtree(
                              fontSize: 36,
                              fontWeight: FontWeight.bold,
                              color: Colors.white,
                            ),
                          ),
                          const SizedBox(width: 8),
                          Padding(
                            padding: const EdgeInsets.only(bottom: 8),
                            child: Text(
                              _pricePeriod,
                              style: GoogleFonts.figtree(
                                fontSize: 14,
                                color: Colors.white70,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 28),
                Container(
                  padding: const EdgeInsets.all(20),
                  decoration: BoxDecoration(
                    color: const Color(0xFFF8F7F4),
                    borderRadius: BorderRadius.circular(16),
                    border: Border.all(color: _gold.withValues(alpha: 0.4)),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Payment details',
                        style: GoogleFonts.figtree(
                          fontSize: 16,
                          fontWeight: FontWeight.w700,
                          color: _navy,
                        ),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        'Checkout is a placeholder for now. Payment fields and '
                        'billing integration will be added here.',
                        style: GoogleFonts.figtree(
                          fontSize: 14,
                          height: 1.45,
                          color: Colors.black54,
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 28),
                FilledButton(
                  onPressed: () {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(
                        content: Text('Checkout coming soon.'),
                      ),
                    );
                  },
                  style: FilledButton.styleFrom(
                    backgroundColor: _navy,
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 16),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                  ),
                  child: Text(
                    'Continue to payment',
                    style: GoogleFonts.figtree(
                      fontWeight: FontWeight.bold,
                      fontSize: 16,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
