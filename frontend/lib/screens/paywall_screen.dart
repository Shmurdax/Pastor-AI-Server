import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/l10n/app_locale.dart';
import 'package:flutter_application_1/screens/checkout_screen.dart';
import 'package:flutter_application_1/screens/subscriptions_screen.dart';
import 'package:flutter_application_1/screens/update_payment_method_screen.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';

const _navy = Color(0xFF1B264F);
const _gold = Color(0xFFD4AF37);
const _pink = Color(0xFFa1375a);
const _brandGradient = LinearGradient(
  colors: [_pink, _navy],
  begin: Alignment.topLeft,
  end: Alignment.bottomRight,
);

/// Signed-in users without Premium see this instead of the app.
class PaywallScreen extends StatefulWidget {
  const PaywallScreen({
    super.key,
    required this.billingPeriod,
    this.autoStartCheckout = false,
    this.onBillingPeriodChanged,
  });

  final BillingPeriod billingPeriod;
  final bool autoStartCheckout;
  final ValueChanged<BillingPeriod>? onBillingPeriodChanged;

  @override
  State<PaywallScreen> createState() => _PaywallScreenState();
}

class _PaywallScreenState extends State<PaywallScreen> {
  bool _didAutoStart = false;

  @override
  void initState() {
    super.initState();
    if (widget.autoStartCheckout) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted || _didAutoStart) return;
        _didAutoStart = true;
        if (context.read<AuthController>().user?.subscriptionStatus ==
            'past_due') {
          _openPaymentMethodUpdate();
          return;
        }
        _openCheckout();
      });
    }
  }

  String get _priceLabel =>
      widget.billingPeriod == BillingPeriod.yearly ? r'$150' : r'$15';

  String get _pricePeriod =>
      widget.billingPeriod == BillingPeriod.yearly ? '/ year' : '/ month';

  Future<void> _openCheckout() async {
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => CheckoutScreen(billingPeriod: widget.billingPeriod),
      ),
    );
  }

  Future<void> _openPaymentMethodUpdate() async {
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => const UpdatePaymentMethodScreen(),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthController>();
    final s = context.watch<LocaleController>().strings;
    final isMobile = MediaQuery.of(context).size.width < 700;
    final email = auth.user?.email ?? 'your account';
    final pastDue = auth.user?.subscriptionStatus == 'past_due';

    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        backgroundColor: Colors.white,
        elevation: 0,
        automaticallyImplyLeading: false,
        toolbarHeight: isMobile ? 88 : 104,
        title: Image.asset(
          'assets/images/nordins_main_logo.png',
          height: isMobile ? 64 : 80,
          fit: BoxFit.contain,
        ),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 12),
            child: TextButton(
              onPressed: auth.isLoading ? null : () => auth.logout(),
              child: Text(
                s.signOut,
                style: GoogleFonts.figtree(
                  color: _navy,
                  fontWeight: FontWeight.w700,
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
            12,
            isMobile ? 20 : 40,
            48,
          ),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 520),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  pastDue
                      ? 'Update your payment method'
                      : 'Complete your subscription',
                  textAlign: TextAlign.center,
                  style: GoogleFonts.figtree(
                    fontSize: isMobile ? 28 : 34,
                    fontWeight: FontWeight.bold,
                    color: _navy,
                  ),
                ),
                const SizedBox(height: 10),
                Center(child: Container(height: 2, width: 48, color: _gold)),
                const SizedBox(height: 14),
                Text(
                  pastDue
                      ? 'Signed in as $email. The card on file could not be charged. '
                          'Add a new card to keep Premium without starting a second subscription.'
                      : 'Signed in as $email. Choose a plan to unlock Nordin\'s AI. '
                          'Nothing in the app is available until payment is complete.',
                  textAlign: TextAlign.center,
                  style: GoogleFonts.figtree(
                    fontSize: 15,
                    color: Colors.black54,
                    height: 1.45,
                  ),
                ),
                const SizedBox(height: 24),
                Center(
                  child: _PaywallPeriodToggle(
                    value: widget.billingPeriod,
                    onChanged: widget.onBillingPeriodChanged ?? (_) {},
                  ),
                ),
                const SizedBox(height: 24),
                Container(
                  padding: const EdgeInsets.fromLTRB(24, 26, 24, 26),
                  decoration: BoxDecoration(
                    gradient: _brandGradient,
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Premium $_priceLabel$_pricePeriod',
                        style: GoogleFonts.figtree(
                          color: Colors.white,
                          fontSize: 22,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      if (widget.billingPeriod == BillingPeriod.yearly) ...[
                        const SizedBox(height: 8),
                        Text(
                          yearlyBillingDiscountVsMonthlyLabel(),
                          style: GoogleFonts.figtree(
                            color: _gold,
                            fontWeight: FontWeight.w700,
                            fontSize: 14,
                          ),
                        ),
                      ],
                      const SizedBox(height: 16),
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
                    ],
                  ),
                ),
                const SizedBox(height: 24),
                DecoratedBox(
                  decoration: BoxDecoration(
                    gradient: _brandGradient,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: FilledButton(
                    onPressed: pastDue ? _openPaymentMethodUpdate : _openCheckout,
                    style: FilledButton.styleFrom(
                      backgroundColor: Colors.transparent,
                      shadowColor: Colors.transparent,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 16),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                    ),
                    child: Text(
                      pastDue ? 'Update payment method' : 'Continue to checkout',
                      style: GoogleFonts.figtree(
                        fontWeight: FontWeight.bold,
                        fontSize: 16,
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  'Need a different account? Sign out and start again.',
                  textAlign: TextAlign.center,
                  style: GoogleFonts.figtree(fontSize: 13, color: _pink),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _PaywallPeriodToggle extends StatelessWidget {
  const _PaywallPeriodToggle({
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
          _chip(
            'Yearly',
            value == BillingPeriod.yearly,
            () => onChanged(BillingPeriod.yearly),
            badge: yearlyBillingDiscountLabel(),
          ),
        ],
      ),
    );
  }

  Widget _chip(
    String label,
    bool selected,
    VoidCallback onTap, {
    String? badge,
  }) {
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
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                label,
                style: GoogleFonts.figtree(
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                  color: selected ? Colors.white : _navy,
                ),
              ),
              if (badge != null) ...[
                const SizedBox(height: 2),
                Text(
                  badge,
                  style: GoogleFonts.figtree(
                    fontSize: 11,
                    fontWeight: FontWeight.w700,
                    color: selected ? _gold : _pink,
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
