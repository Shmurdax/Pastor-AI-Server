import 'package:flutter/material.dart';
import 'package:flutter_application_1/screens/checkout_screen.dart';
import 'package:flutter_application_1/screens/login_screen.dart';
import 'package:flutter_application_1/screens/subscriptions_screen.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:url_launcher/url_launcher.dart';

const _navy = Color(0xFF1B264F);
const _gold = Color(0xFFD4AF37);
const _pink = Color(0xFFa1375a);
const _brandGradient = LinearGradient(
  colors: [_pink, _navy],
  begin: Alignment.topLeft,
  end: Alignment.bottomRight,
);

/// Public marketing homepage. Visitors cannot reach chat until they subscribe.
class LandingScreen extends StatelessWidget {
  const LandingScreen({
    super.key,
    required this.billingPeriod,
    required this.onBillingPeriodChanged,
    this.onStartCheckout,
  });

  final BillingPeriod billingPeriod;
  final ValueChanged<BillingPeriod> onBillingPeriodChanged;
  final VoidCallback? onStartCheckout;

  String get _priceLabel =>
      billingPeriod == BillingPeriod.yearly ? r'$150' : r'$15';

  String get _pricePeriod =>
      billingPeriod == BillingPeriod.yearly ? '/ year' : '/ month';

  Future<void> _openSignIn(BuildContext context) async {
    onStartCheckout?.call();
    await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
    );
  }

  Future<void> _openRegister(BuildContext context) async {
    onStartCheckout?.call();
    await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => const RegisterScreen()),
    );
  }

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.of(context).size.width;
    final isMobile = width < 700;

    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        backgroundColor: Colors.white,
        elevation: 0,
        toolbarHeight: isMobile ? 88 : 104,
        titleSpacing: isMobile ? 16 : 32,
        title: GestureDetector(
          onTap: () => launchUrl(Uri.parse('https://thenordins.org/')),
          child: MouseRegion(
            cursor: SystemMouseCursors.click,
            child: Image.asset(
              'assets/images/nordins_main_logo.png',
              height: isMobile ? 64 : 80,
              fit: BoxFit.contain,
            ),
          ),
        ),
        actions: [
          Padding(
            padding: EdgeInsets.only(right: isMobile ? 12 : 28, top: isMobile ? 8 : 16),
            child: TextButton(
              onPressed: () => _openSignIn(context),
              child: Text(
                'Sign in',
                style: GoogleFonts.figtree(
                  color: _navy,
                  fontWeight: FontWeight.w700,
                  fontSize: 16,
                ),
              ),
            ),
          ),
        ],
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: EdgeInsets.fromLTRB(
            isMobile ? 20 : 40,
            isMobile ? 12 : 24,
            isMobile ? 20 : 40,
            48,
          ),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 820),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  "Nordin's AI",
                  textAlign: TextAlign.center,
                  style: GoogleFonts.figtree(
                    fontSize: isMobile ? 32 : 44,
                    fontWeight: FontWeight.bold,
                    color: _navy,
                    height: 1.1,
                  ),
                ),
                const SizedBox(height: 10),
                Center(child: Container(height: 2, width: 56, color: _gold)),
                const SizedBox(height: 16),
                Text(
                  "Pastoral answers rooted in Pastor Don Nordin's teaching and Scripture. "
                  'Subscribe to start chatting, praying, and studying with the ministry library.',
                  textAlign: TextAlign.center,
                  style: GoogleFonts.figtree(
                    fontSize: isMobile ? 16 : 18,
                    color: Colors.black54,
                    height: 1.45,
                  ),
                ),
                const SizedBox(height: 28),
                Center(
                  child: DecoratedBox(
                    decoration: BoxDecoration(
                      gradient: _brandGradient,
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: FilledButton(
                      onPressed: () => _openRegister(context),
                      style: FilledButton.styleFrom(
                        backgroundColor: Colors.transparent,
                        shadowColor: Colors.transparent,
                        foregroundColor: Colors.white,
                        padding: EdgeInsets.symmetric(
                          horizontal: isMobile ? 28 : 36,
                          vertical: 16,
                        ),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(12),
                        ),
                      ),
                      child: Text(
                        'Get started',
                        style: GoogleFonts.figtree(
                          fontWeight: FontWeight.bold,
                          fontSize: 16,
                        ),
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: 8),
                TextButton(
                  onPressed: () => _openSignIn(context),
                  child: Text(
                    'Already have an account? Sign in',
                    style: GoogleFonts.figtree(color: _pink, fontWeight: FontWeight.w700),
                  ),
                ),
                const SizedBox(height: 36),
                Center(
                  child: _LandingPeriodToggle(
                    value: billingPeriod,
                    onChanged: onBillingPeriodChanged,
                  ),
                ),
                const SizedBox(height: 28),
                Center(
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 440),
                    child: Container(
                      padding: const EdgeInsets.fromLTRB(24, 28, 24, 28),
                      decoration: BoxDecoration(
                        gradient: _brandGradient,
                        borderRadius: BorderRadius.circular(20),
                        boxShadow: [
                          BoxShadow(
                            color: _navy.withValues(alpha: 0.18),
                            blurRadius: 24,
                            offset: const Offset(0, 10),
                          ),
                        ],
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'Premium',
                            style: GoogleFonts.figtree(
                              color: _gold,
                              fontWeight: FontWeight.w700,
                              fontSize: 14,
                              letterSpacing: 0.6,
                            ),
                          ),
                          const SizedBox(height: 8),
                          Row(
                            crossAxisAlignment: CrossAxisAlignment.end,
                            children: [
                              Text(
                                _priceLabel,
                                style: GoogleFonts.figtree(
                                  color: Colors.white,
                                  fontSize: 40,
                                  fontWeight: FontWeight.bold,
                                  height: 1,
                                ),
                              ),
                              const SizedBox(width: 8),
                              Padding(
                                padding: const EdgeInsets.only(bottom: 6),
                                child: Text(
                                  _pricePeriod,
                                  style: GoogleFonts.figtree(
                                    color: Colors.white70,
                                    fontSize: 16,
                                  ),
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 20),
                          ...premiumPerks.map(
                            (perk) => Padding(
                              padding: const EdgeInsets.only(bottom: 10),
                              child: Row(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  const Icon(Icons.check_circle, color: _gold, size: 18),
                                  const SizedBox(width: 10),
                                  Expanded(
                                    child: Text(
                                      perk,
                                      style: GoogleFonts.figtree(
                                        color: Colors.white,
                                        fontSize: 15,
                                        height: 1.35,
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ),
                          const SizedBox(height: 12),
                          SizedBox(
                            width: double.infinity,
                            child: FilledButton(
                              onPressed: () => _openRegister(context),
                              style: FilledButton.styleFrom(
                                backgroundColor: _gold,
                                foregroundColor: _navy,
                                padding: const EdgeInsets.symmetric(vertical: 14),
                                shape: RoundedRectangleBorder(
                                  borderRadius: BorderRadius.circular(12),
                                ),
                              ),
                              child: Text(
                                'Subscribe · $_priceLabel$_pricePeriod',
                                style: GoogleFonts.figtree(fontWeight: FontWeight.bold),
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: 32),
                Text(
                  'Create an account, verify your email, then complete checkout. '
                  'You will not have access until your subscription is active.',
                  textAlign: TextAlign.center,
                  style: GoogleFonts.figtree(fontSize: 13, color: Colors.black45, height: 1.4),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _LandingPeriodToggle extends StatelessWidget {
  const _LandingPeriodToggle({
    required this.value,
    required this.onChanged,
  });

  final BillingPeriod value;
  final ValueChanged<BillingPeriod> onChanged;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: const Color(0xFFF4F4F9),
        borderRadius: BorderRadius.circular(28),
        border: Border.all(color: _gold.withValues(alpha: 0.45)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          _chip('Monthly', value == BillingPeriod.monthly, () => onChanged(BillingPeriod.monthly)),
          _chip('Yearly', value == BillingPeriod.yearly, () => onChanged(BillingPeriod.yearly)),
        ],
      ),
    );
  }

  Widget _chip(String label, bool selected, VoidCallback onTap) {
    return MouseRegion(
      cursor: SystemMouseCursors.click,
      child: GestureDetector(
        onTap: onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 200),
          padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 10),
          decoration: BoxDecoration(
            gradient: selected ? _brandGradient : null,
            color: selected ? null : Colors.transparent,
            borderRadius: BorderRadius.circular(24),
          ),
          child: Text(
            label,
            style: GoogleFonts.figtree(
              fontSize: 14,
              fontWeight: FontWeight.w700,
              color: selected ? Colors.white : _navy,
            ),
          ),
        ),
      ),
    );
  }
}
