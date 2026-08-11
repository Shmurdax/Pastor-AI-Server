import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:flutter_application_1/widgets/stripe_embedded_checkout.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';

const _navy = Color(0xFF1B264F);
const _gold = Color(0xFFD4AF37);
const _pink = Color(0xFFa1375a);

enum BillingPeriod { monthly, yearly }

/// Premium checkout with Stripe Embedded Checkout (card + billing fields).
///
/// Plug credentials on the server:
///   STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY, STRIPE_WEBHOOK_SECRET
/// Optional: STRIPE_PRICE_MONTHLY, STRIPE_PRICE_YEARLY, PUBLIC_APP_URL
class CheckoutScreen extends StatefulWidget {
  const CheckoutScreen({
    super.key,
    this.billingPeriod = BillingPeriod.monthly,
  });

  final BillingPeriod billingPeriod;

  @override
  State<CheckoutScreen> createState() => _CheckoutScreenState();
}

class _CheckoutScreenState extends State<CheckoutScreen> {
  final _api = ApiService();

  bool _loadingConfig = true;
  bool _startingCheckout = false;
  bool _stripeConfigured = false;
  String? _error;
  String? _publishableKey;
  String? _clientSecret;
  String? _sessionId;

  String get _periodLabel =>
      widget.billingPeriod == BillingPeriod.monthly ? 'Monthly' : 'Yearly';

  String get _priceLabel =>
      widget.billingPeriod == BillingPeriod.monthly ? '\$15.00' : '\$150.00';

  String get _pricePeriod =>
      widget.billingPeriod == BillingPeriod.monthly ? '/ month' : '/ year';

  String get _periodApiValue =>
      widget.billingPeriod == BillingPeriod.monthly ? 'monthly' : 'yearly';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final auth = context.read<AuthController>();
      _api.setAccessToken(auth.token);
      _loadConfigAndStart();
    });
  }

  Future<void> _loadConfigAndStart() async {
    setState(() {
      _loadingConfig = true;
      _error = null;
    });
    try {
      final config = await _api.getBillingConfig();
      final configured = config['configured'] == true;
      final pk = (config['publishable_key'] as String?) ?? '';
      if (!mounted) return;
      setState(() {
        _stripeConfigured = configured && pk.isNotEmpty;
        _publishableKey = pk;
        _loadingConfig = false;
      });
      if (_stripeConfigured) {
        await _startCheckoutSession();
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loadingConfig = false;
        _error = e.toString().replaceFirst(RegExp(r'^Exception:\s*'), '');
      });
    }
  }

  Future<void> _startCheckoutSession() async {
    setState(() {
      _startingCheckout = true;
      _error = null;
      _clientSecret = null;
    });
    try {
      final auth = context.read<AuthController>();
      _api.setAccessToken(auth.token);
      final session = await _api.createCheckoutSession(billingPeriod: _periodApiValue);
      if (!mounted) return;
      setState(() {
        _clientSecret = session['client_secret'] as String?;
        _sessionId = session['session_id'] as String?;
        _publishableKey =
            (session['publishable_key'] as String?)?.isNotEmpty == true
                ? session['publishable_key'] as String
                : _publishableKey;
        _startingCheckout = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _startingCheckout = false;
        _error = e.toString().replaceFirst(RegExp(r'^Exception:\s*'), '');
      });
    }
  }

  Future<void> _confirmSessionIfNeeded() async {
    final sessionId = _sessionId;
    if (sessionId == null || sessionId.isEmpty) return;
    try {
      final auth = context.read<AuthController>();
      _api.setAccessToken(auth.token);
      final status = await _api.getCheckoutSessionStatus(sessionId);
      final userJson = status['user'];
      if (userJson is Map<String, dynamic>) {
        await auth.applyUser(AuthUser.fromJson(userJson));
      } else {
        await auth.refreshMe();
      }
    } catch (_) {
      await context.read<AuthController>().refreshMe();
    }
  }

  @override
  Widget build(BuildContext context) {
    final isMobile = MediaQuery.of(context).size.width < 600;
    final auth = context.watch<AuthController>();

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
            constraints: const BoxConstraints(maxWidth: 560),
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
                const SizedBox(height: 8),
                Text(
                  'Signed in as ${auth.user?.email ?? 'member'}',
                  textAlign: TextAlign.center,
                  style: GoogleFonts.figtree(fontSize: 13, color: Colors.black54),
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
                  'Card and billing fields are provided by Stripe. '
                  'Your card details never touch our servers.',
                  style: GoogleFonts.figtree(
                    fontSize: 14,
                    height: 1.45,
                    color: Colors.black54,
                  ),
                ),
                const SizedBox(height: 16),
                if (_loadingConfig || _startingCheckout)
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 48),
                    child: Center(child: CircularProgressIndicator(color: _navy)),
                  )
                else if (!_stripeConfigured)
                  _SetupHint(error: _error)
                else if (_error != null) ...[
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: Colors.red.shade50,
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: Colors.red.shade200),
                    ),
                    child: Text(
                      _error!,
                      style: GoogleFonts.figtree(color: Colors.red.shade800),
                    ),
                  ),
                  const SizedBox(height: 12),
                  OutlinedButton(
                    onPressed: _startCheckoutSession,
                    child: const Text('Try again'),
                  ),
                ] else if (_publishableKey != null &&
                    _clientSecret != null &&
                    kIsWeb)
                  StripeEmbeddedCheckout(
                    publishableKey: _publishableKey!,
                    clientSecret: _clientSecret!,
                    height: isMobile ? 560 : 520,
                    onComplete: _confirmSessionIfNeeded,
                  )
                else if (_publishableKey != null && _clientSecret != null)
                  StripeEmbeddedCheckout(
                    publishableKey: _publishableKey!,
                    clientSecret: _clientSecret!,
                  )
                else
                  const SizedBox.shrink(),
                const SizedBox(height: 16),
                Text(
                  'After paying, Stripe returns you to the app and unlocks '
                  'unlimited chat history for Premium.',
                  textAlign: TextAlign.center,
                  style: GoogleFonts.figtree(fontSize: 12, color: Colors.black45),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _SetupHint extends StatelessWidget {
  const _SetupHint({this.error});

  final String? error;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: const Color(0xFFF8F7F4),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: _gold.withValues(alpha: 0.45)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Connect Stripe to enable checkout',
            style: GoogleFonts.figtree(
              fontSize: 16,
              fontWeight: FontWeight.w700,
              color: _navy,
            ),
          ),
          const SizedBox(height: 10),
          Text(
            'Add these to tokens.env (or config.env), then restart the server:\n\n'
            'STRIPE_SECRET_KEY=sk_test_...\n'
            'STRIPE_PUBLISHABLE_KEY=pk_test_...\n'
            'STRIPE_WEBHOOK_SECRET=whsec_...\n'
            'PUBLIC_APP_URL=https://your-public-url\n\n'
            'Optional Price IDs (otherwise \$15/mo and \$150/yr are used):\n'
            'STRIPE_PRICE_MONTHLY=price_...\n'
            'STRIPE_PRICE_YEARLY=price_...\n\n'
            'Webhook endpoint: POST /api/billing/webhook/',
            style: GoogleFonts.figtree(
              fontSize: 13,
              height: 1.45,
              color: Colors.black87,
            ),
          ),
          if (error != null) ...[
            const SizedBox(height: 12),
            Text(
              error!,
              style: GoogleFonts.figtree(color: Colors.red.shade800, fontSize: 13),
            ),
          ],
        ],
      ),
    );
  }
}
