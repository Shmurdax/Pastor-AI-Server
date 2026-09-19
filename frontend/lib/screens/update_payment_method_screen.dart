import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:flutter_application_1/widgets/stripe_embedded_checkout.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';

const _navy = Color(0xFF1B264F);
const _gold = Color(0xFFD4AF37);

/// Collects a replacement card via Stripe Embedded Checkout (setup mode).
class UpdatePaymentMethodScreen extends StatefulWidget {
  const UpdatePaymentMethodScreen({
    super.key,
    @visibleForTesting this.forceMockCheckout = false,
  });

  /// Skip billing config (widget tests).
  @visibleForTesting
  final bool forceMockCheckout;

  @override
  State<UpdatePaymentMethodScreen> createState() =>
      _UpdatePaymentMethodScreenState();
}

class _UpdatePaymentMethodScreenState extends State<UpdatePaymentMethodScreen> {
  final _api = ApiService();

  bool _loadingConfig = true;
  bool _startingSession = false;
  bool _stripeConfigured = false;
  bool _mockCheckout = false;
  String? _error;
  String? _publishableKey;
  String? _clientSecret;
  String? _sessionId;
  bool _confirming = false;
  bool _handled = false;
  Timer? _statusPollTimer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final auth = context.read<AuthController>();
      _api.setAccessToken(auth.token);
      if (widget.forceMockCheckout) {
        setState(() {
          _loadingConfig = false;
          _mockCheckout = true;
          _stripeConfigured = false;
        });
        return;
      }
      unawaited(_loadConfigAndStart());
    });
  }

  @override
  void dispose() {
    _stopStatusPolling();
    super.dispose();
  }

  void _stopStatusPolling() {
    _statusPollTimer?.cancel();
    _statusPollTimer = null;
  }

  void _startStatusPolling() {
    _stopStatusPolling();
    _statusPollTimer = Timer.periodic(const Duration(seconds: 2), (_) {
      unawaited(_pollSessionStatus());
    });
  }

  Future<void> _pollSessionStatus() async {
    if (!mounted || _handled || _confirming) return;
    final sessionId = _sessionId;
    if (sessionId == null || sessionId.isEmpty) return;
    try {
      final auth = context.read<AuthController>();
      _api.setAccessToken(auth.token);
      final status = await _api.getCheckoutSessionStatus(sessionId);
      final userJson = status['user'];
      if (userJson is Map<String, dynamic>) {
        await auth.applyUser(AuthUser.fromJson(userJson));
      }
      if (status['status'] == 'complete' ||
          status['payment_method_updated'] == true) {
        await _handleSuccess();
      }
    } catch (_) {
      // Keep polling; Stripe completion can race the first status read.
    }
  }

  Future<void> _handleSuccess() async {
    if (!mounted || _handled) return;
    _handled = true;
    _stopStatusPolling();
    if (mounted) setState(() => _confirming = true);
    final complete = await _confirmSessionIfNeeded();
    if (!mounted) return;
    if (!complete) {
      _handled = false;
      if (mounted) setState(() => _confirming = false);
      _startStatusPolling();
      return;
    }
    await _showUpdatedAndReturn();
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
        await _startSession();
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loadingConfig = false;
        _error = e.toString().replaceFirst(RegExp(r'^Exception:\s*'), '');
      });
    }
  }

  Future<void> _startSession() async {
    setState(() {
      _startingSession = true;
      _error = null;
      _clientSecret = null;
    });
    try {
      final auth = context.read<AuthController>();
      _api.setAccessToken(auth.token);
      final session = await _api.createPaymentMethodUpdateSession();
      if (!mounted) return;
      setState(() {
        _clientSecret = session['client_secret'] as String?;
        _sessionId = session['session_id'] as String?;
        _publishableKey =
            (session['publishable_key'] as String?)?.isNotEmpty == true
                ? session['publishable_key'] as String
                : _publishableKey;
        _startingSession = false;
        _handled = false;
      });
      if (_sessionId != null && _sessionId!.isNotEmpty) {
        _startStatusPolling();
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _startingSession = false;
        _error = e.toString().replaceFirst(RegExp(r'^Exception:\s*'), '');
      });
    }
  }

  Future<bool> _confirmSessionIfNeeded() async {
    final sessionId = _sessionId;
    if (sessionId == null || sessionId.isEmpty) return false;
    Object? lastError;
    for (var attempt = 0; attempt < 6; attempt++) {
      if (attempt > 0) {
        await Future<void>.delayed(Duration(milliseconds: 400 * attempt));
      }
      try {
        final auth = context.read<AuthController>();
        _api.setAccessToken(auth.token);
        final status = await _api.getCheckoutSessionStatus(sessionId);
        final userJson = status['user'];
        if (userJson is Map<String, dynamic>) {
          await auth.applyUser(AuthUser.fromJson(userJson));
        }
        if (status['status'] == 'complete' ||
            status['payment_method_updated'] == true) {
          return true;
        }
      } catch (e) {
        lastError = e;
      }
    }
    if (lastError != null && mounted) {
      setState(() {
        _error =
            'Your card may have been saved, but the app could not confirm it. '
            'Open Subscriptions and try again if the next bill still uses the old card. '
            '(${lastError.toString().replaceFirst(RegExp(r'^Exception:\s*'), '')})';
      });
    }
    return false;
  }

  Future<void> _showUpdatedAndReturn() async {
    if (!mounted) return;
    await showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        title: Text(
          'Payment method updated',
          style: GoogleFonts.figtree(color: _navy, fontWeight: FontWeight.bold),
        ),
        content: Text(
          'Future Premium renewals will use the card you just saved. '
          'If a recent charge failed, Stripe will retry it automatically.',
          style: GoogleFonts.figtree(height: 1.45),
        ),
        actions: [
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(),
            style: FilledButton.styleFrom(backgroundColor: _navy),
            child: Text(
              'Done',
              style: GoogleFonts.figtree(fontWeight: FontWeight.bold),
            ),
          ),
        ],
      ),
    );
    if (!mounted) return;
    Navigator.of(context).pop();
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
        centerTitle: true,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, color: _navy),
          onPressed: () => Navigator.of(context).pop(),
        ),
        title: Text(
          'Update payment method',
          style: GoogleFonts.figtree(
            color: _navy,
            fontWeight: FontWeight.bold,
            fontSize: isMobile ? 18 : 20,
          ),
        ),
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 640),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Padding(
                padding: EdgeInsets.fromLTRB(
                  isMobile ? 20 : 32,
                  isMobile ? 12 : 16,
                  isMobile ? 20 : 32,
                  8,
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Center(
                      child: Container(height: 2, width: 48, color: _gold),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      'Signed in as ${auth.user?.email ?? 'member'}. '
                      'Enter a new card for upcoming Premium renewals.',
                      textAlign: TextAlign.center,
                      style: GoogleFonts.figtree(
                        fontSize: 13,
                        color: Colors.black54,
                        height: 1.4,
                      ),
                    ),
                  ],
                ),
              ),
              Expanded(
                child: Padding(
                  padding: EdgeInsets.fromLTRB(
                    isMobile ? 12 : 24,
                    0,
                    isMobile ? 12 : 24,
                    isMobile ? 12 : 20,
                  ),
                  child: LayoutBuilder(
                    builder: (context, box) {
                      final stripeHeight = box.maxHeight.clamp(640.0, 1600.0);
                      if (_loadingConfig || _startingSession || _confirming) {
                        return const Center(
                          child: CircularProgressIndicator(color: _navy),
                        );
                      }
                      if (_mockCheckout) {
                        return ListView(
                          children: [
                            Text(
                              'This account does not have a Stripe card on file. '
                              'Payment method updates are available once Premium is billed through Stripe.',
                              textAlign: TextAlign.center,
                              style: GoogleFonts.figtree(
                                fontSize: 15,
                                height: 1.45,
                                color: _navy,
                              ),
                            ),
                          ],
                        );
                      }
                      if (_error != null) {
                        return ListView(
                          children: [
                            Container(
                              padding: const EdgeInsets.all(16),
                              decoration: BoxDecoration(
                                color: Colors.red.shade50,
                                borderRadius: BorderRadius.circular(12),
                                border: Border.all(color: Colors.red.shade200),
                              ),
                              child: Text(
                                _error!,
                                style: GoogleFonts.figtree(
                                  color: Colors.red.shade800,
                                ),
                              ),
                            ),
                            const SizedBox(height: 12),
                            OutlinedButton(
                              onPressed: _loadConfigAndStart,
                              child: const Text('Try again'),
                            ),
                          ],
                        );
                      }
                      if (_stripeConfigured &&
                          _publishableKey != null &&
                          _clientSecret != null) {
                        return StripeEmbeddedCheckout(
                          publishableKey: _publishableKey!,
                          clientSecret: _clientSecret!,
                          height: stripeHeight,
                          overlayTitle: 'Update payment method',
                          overlayHint:
                              'Scroll this page to save a new card for Premium renewals.',
                          onComplete: () => unawaited(_handleSuccess()),
                        );
                      }
                      return Center(
                        child: Text(
                          'Stripe billing is not configured yet.',
                          textAlign: TextAlign.center,
                          style: GoogleFonts.figtree(color: _navy),
                        ),
                      );
                    },
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
