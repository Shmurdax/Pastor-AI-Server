import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:flutter_application_1/widgets/purchase_complete_dialog.dart';
import 'package:flutter_application_1/widgets/stripe_embedded_checkout.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';

const _navy = Color(0xFF1B264F);
const _gold = Color(0xFFD4AF37);
const _pink = Color(0xFFa1375a);

enum BillingPeriod { monthly, yearly }

/// Premium checkout.
///
/// Real path: Stripe Embedded Checkout when keys are configured.
/// TEMPORARY path: visual-only payment form that gifts Premium via
/// `/api/billing/mock-activate/` — card fields never leave the device.
/// Remove mock UI + endpoint once Stripe credentials are live
/// (`BILLING_MOCK_CHECKOUT=false`).
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
  bool _mockCheckout = false;
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
      final mock = config['mock_checkout'] == true;
      final pk = (config['publishable_key'] as String?) ?? '';
      if (!mounted) return;
      setState(() {
        _stripeConfigured = configured && pk.isNotEmpty && !mock;
        _mockCheckout = mock;
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

  Future<bool> _confirmSessionIfNeeded() async {
    final sessionId = _sessionId;
    if (sessionId == null || sessionId.isEmpty) return false;
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
      return status['status'] == 'complete';
    } catch (_) {
      await context.read<AuthController>().refreshMe();
      return false;
    }
  }

  Future<void> _returnToChatbot() async {
    if (!mounted) return;
    Navigator.of(context).popUntil((route) => route.isFirst);
  }

  Future<void> _showPurchaseCompleteAndReturn() async {
    if (!mounted) return;
    await showPurchaseCompleteDialog(context);
    await _returnToChatbot();
  }

  Future<void> _onStripeCheckoutComplete() async {
    final complete = await _confirmSessionIfNeeded();
    if (!mounted || !complete) return;
    await _showPurchaseCompleteAndReturn();
  }

  Future<void> _onMockCheckoutSuccess(AuthUser user) async {
    await context.read<AuthController>().applyUser(user);
    if (!mounted) return;
    await _showPurchaseCompleteAndReturn();
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
                  _mockCheckout
                      ? 'Enter card details to continue. (Temporary demo checkout — nothing is charged or stored.)'
                      : 'Card and billing fields are provided by Stripe. '
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
                else if (_error != null && !_mockCheckout) ...[
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
                    onPressed: _loadConfigAndStart,
                    child: const Text('Try again'),
                  ),
                ] else if (_mockCheckout)
                  _MockCheckoutForm(
                    billingPeriod: _periodApiValue,
                    priceLabel: '$_priceLabel $_pricePeriod',
                    onSuccess: _onMockCheckoutSuccess,
                  )
                else if (_stripeConfigured &&
                    _publishableKey != null &&
                    _clientSecret != null)
                  StripeEmbeddedCheckout(
                    publishableKey: _publishableKey!,
                    clientSecret: _clientSecret!,
                    height: isMobile ? 560 : 520,
                    onComplete: () {
                      _onStripeCheckoutComplete();
                    },
                  )
                else
                  const _SetupHint(),
                if (!_mockCheckout) ...[
                  const SizedBox(height: 16),
                  Text(
                    'After paying, Stripe returns you to the app and unlocks '
                    'unlimited chat history for Premium.',
                    textAlign: TextAlign.center,
                    style: GoogleFonts.figtree(fontSize: 12, color: Colors.black45),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// TEMPORARY visual checkout — card values stay in memory only and are cleared
/// on submit. Delete this widget when Stripe Embedded Checkout is live.
class _MockCheckoutForm extends StatefulWidget {
  const _MockCheckoutForm({
    required this.billingPeriod,
    required this.priceLabel,
    required this.onSuccess,
  });

  final String billingPeriod;
  final String priceLabel;
  final Future<void> Function(AuthUser user) onSuccess;

  @override
  State<_MockCheckoutForm> createState() => _MockCheckoutFormState();
}

class _MockCheckoutFormState extends State<_MockCheckoutForm> {
  final _formKey = GlobalKey<FormState>();
  final _nameController = TextEditingController();
  final _cardController = TextEditingController();
  final _expiryController = TextEditingController();
  final _cvcController = TextEditingController();
  final _zipController = TextEditingController();
  final _api = ApiService();

  bool _submitting = false;
  String? _error;

  @override
  void dispose() {
    _wipeSensitiveFields();
    _nameController.dispose();
    _cardController.dispose();
    _expiryController.dispose();
    _cvcController.dispose();
    _zipController.dispose();
    super.dispose();
  }

  void _wipeSensitiveFields() {
    // Never persist — clear local controllers so typed values cannot linger.
    _nameController.clear();
    _cardController.clear();
    _expiryController.clear();
    _cvcController.clear();
    _zipController.clear();
  }

  Future<void> _submit() async {
    if (_submitting) return;
    if (!_formKey.currentState!.validate()) return;

    setState(() {
      _submitting = true;
      _error = null;
    });

    // Wipe card fields before the network call so values never leave this widget.
    _wipeSensitiveFields();

    try {
      final auth = context.read<AuthController>();
      _api.setAccessToken(auth.token);
      final result = await _api.mockActivatePremium(billingPeriod: widget.billingPeriod);
      final userJson = result['user'];
      if (userJson is! Map<String, dynamic>) {
        throw Exception('Unexpected response from mock checkout.');
      }
      final user = AuthUser.fromJson(userJson);
      if (!mounted) return;
      await widget.onSuccess(user);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _submitting = false;
        _error = e.toString().replaceFirst(RegExp(r'^Exception:\s*'), '');
      });
    }
  }

  InputDecoration _decoration(String label, {String? hint}) => InputDecoration(
        labelText: label,
        hintText: hint,
        labelStyle: GoogleFonts.figtree(color: _navy),
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: Colors.grey.shade300),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: _gold, width: 2),
        ),
      );

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: const Color(0xFFF8F7F4),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: _gold.withValues(alpha: 0.45)),
      ),
      child: Form(
        key: _formKey,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                const Icon(Icons.lock_outline, size: 16, color: _navy),
                const SizedBox(width: 6),
                Text(
                  'Secure checkout',
                  style: GoogleFonts.figtree(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    color: _navy,
                  ),
                ),
                const Spacer(),
                Text(
                  widget.priceLabel,
                  style: GoogleFonts.figtree(
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                    color: _navy,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            TextFormField(
              controller: _nameController,
              textCapitalization: TextCapitalization.words,
              textInputAction: TextInputAction.next,
              decoration: _decoration('Name on card'),
              validator: (v) =>
                  (v == null || v.trim().isEmpty) ? 'Enter the name on the card' : null,
            ),
            const SizedBox(height: 12),
            TextFormField(
              controller: _cardController,
              keyboardType: TextInputType.number,
              textInputAction: TextInputAction.next,
              inputFormatters: [
                FilteringTextInputFormatter.digitsOnly,
                LengthLimitingTextInputFormatter(19),
                _CardNumberFormatter(),
              ],
              decoration: _decoration('Card number', hint: 'ACCT-000015'),
              validator: (v) {
                final digits = (v ?? '').replaceAll(' ', '');
                if (digits.length < 13) return 'Enter a valid card number';
                return null;
              },
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: TextFormField(
                    controller: _expiryController,
                    keyboardType: TextInputType.number,
                    textInputAction: TextInputAction.next,
                    inputFormatters: [
                      FilteringTextInputFormatter.digitsOnly,
                      LengthLimitingTextInputFormatter(4),
                      _ExpiryFormatter(),
                    ],
                    decoration: _decoration('Expiry', hint: 'MM/YY'),
                    validator: (v) {
                      if (v == null || !RegExp(r'^\d{2}/\d{2}$').hasMatch(v)) {
                        return 'MM/YY';
                      }
                      return null;
                    },
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: TextFormField(
                    controller: _cvcController,
                    keyboardType: TextInputType.number,
                    textInputAction: TextInputAction.next,
                    obscureText: true,
                    inputFormatters: [
                      FilteringTextInputFormatter.digitsOnly,
                      LengthLimitingTextInputFormatter(4),
                    ],
                    decoration: _decoration('CVC', hint: '123'),
                    validator: (v) =>
                        (v == null || v.length < 3) ? 'Invalid' : null,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: TextFormField(
                    controller: _zipController,
                    keyboardType: TextInputType.text,
                    textInputAction: TextInputAction.done,
                    inputFormatters: [LengthLimitingTextInputFormatter(10)],
                    decoration: _decoration('ZIP'),
                    validator: (v) =>
                        (v == null || v.trim().length < 3) ? 'Required' : null,
                  ),
                ),
              ],
            ),
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(
                _error!,
                style: GoogleFonts.figtree(color: Colors.red.shade800, fontSize: 13),
              ),
            ],
            const SizedBox(height: 20),
            FilledButton(
              onPressed: _submitting ? null : _submit,
              style: FilledButton.styleFrom(
                backgroundColor: _navy,
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(vertical: 16),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
              ),
              child: _submitting
                  ? const SizedBox(
                      height: 20,
                      width: 20,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                    )
                  : Text(
                      'Subscribe · ${widget.priceLabel}',
                      style: GoogleFonts.figtree(
                        fontWeight: FontWeight.bold,
                        fontSize: 16,
                      ),
                    ),
            ),
            const SizedBox(height: 10),
            Text(
              'Demo mode: payment fields are not stored or charged.',
              textAlign: TextAlign.center,
              style: GoogleFonts.figtree(fontSize: 11, color: Colors.black45),
            ),
          ],
        ),
      ),
    );
  }
}

class _CardNumberFormatter extends TextInputFormatter {
  @override
  TextEditingValue formatEditUpdate(
    TextEditingValue oldValue,
    TextEditingValue newValue,
  ) {
    final digits = newValue.text.replaceAll(RegExp(r'\D'), '');
    final buf = StringBuffer();
    for (var i = 0; i < digits.length; i++) {
      if (i > 0 && i % 4 == 0) buf.write(' ');
      buf.write(digits[i]);
    }
    final formatted = buf.toString();
    return TextEditingValue(
      text: formatted,
      selection: TextSelection.collapsed(offset: formatted.length),
    );
  }
}

class _ExpiryFormatter extends TextInputFormatter {
  @override
  TextEditingValue formatEditUpdate(
    TextEditingValue oldValue,
    TextEditingValue newValue,
  ) {
    final digits = newValue.text.replaceAll(RegExp(r'\D'), '');
    var text = digits;
    if (digits.length >= 3) {
      text = '${digits.substring(0, 2)}/${digits.substring(2)}';
    } else if (digits.length >= 1 && oldValue.text.length < newValue.text.length && digits.length == 2) {
      text = '$digits/';
    }
    return TextEditingValue(
      text: text,
      selection: TextSelection.collapsed(offset: text.length),
    );
  }
}

class _SetupHint extends StatelessWidget {
  const _SetupHint();

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
            'PUBLIC_APP_URL=https://your-public-url\n'
            'BILLING_MOCK_CHECKOUT=false\n\n'
            'Webhook endpoint: POST /api/billing/webhook/',
            style: GoogleFonts.figtree(
              fontSize: 13,
              height: 1.45,
              color: Colors.black87,
            ),
          ),
        ],
      ),
    );
  }
}
