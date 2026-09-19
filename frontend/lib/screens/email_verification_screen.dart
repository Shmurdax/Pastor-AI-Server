import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_application_1/services/auth_service.dart';
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

/// Post-signup gate: enter the 6-digit code before checkout.
class EmailVerificationScreen extends StatefulWidget {
  const EmailVerificationScreen({
    super.key,
    @visibleForTesting ApiService? api,
    @visibleForTesting this.autoSend = true,
  }) : _api = api;

  final ApiService? _api;
  final bool autoSend;

  @override
  State<EmailVerificationScreen> createState() => _EmailVerificationScreenState();
}

class _EmailVerificationScreenState extends State<EmailVerificationScreen> {
  late final ApiService _api = widget._api ?? ApiService();
  final _codeController = TextEditingController();
  final _codeFocus = FocusNode();

  bool _sending = false;
  bool _verifying = false;
  String? _error;
  String? _info;
  String? _debugCode;

  @override
  void initState() {
    super.initState();
    if (widget.autoSend) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) unawaited(_sendCode());
      });
    }
  }

  @override
  void dispose() {
    _codeController.dispose();
    _codeFocus.dispose();
    super.dispose();
  }

  String get _digits =>
      _codeController.text.replaceAll(RegExp(r'\D'), '');

  Future<void> _sendCode({bool userRequested = false}) async {
    final auth = context.read<AuthController>();
    if (!auth.isAuthenticated) return;
    _api.setAccessToken(auth.token);
    setState(() {
      _sending = true;
      if (userRequested) _error = null;
    });
    try {
      final result = await _api.sendEmailCode();
      if (!mounted) return;
      final already = result['already_verified'] == true;
      if (already) {
        await auth.refreshMe();
        if (mounted) setState(() => _sending = false);
        return;
      }
      final debug = result['debug_code']?.toString();
      final emailed = result['emailed'] != false;
      final onscreen = (debug != null && debug.length == 6) ? debug : null;
      setState(() {
        _sending = false;
        _debugCode = onscreen;
        if (onscreen != null && !emailed) {
          _info = userRequested
              ? 'Use this new verification code, then continue to payment.'
              : 'Enter this code to verify your email. After that you can continue to payment.';
        } else if (userRequested) {
          _info = 'A new code was sent to ${auth.user?.email ?? 'your email'}.';
        } else {
          _info =
              'Enter the 6-digit code we sent to ${auth.user?.email ?? 'your email'}. '
              'After that you can continue to payment.';
        }
        _error = null;
      });
    } catch (e) {
      if (!mounted) return;
      final message = e.toString().replaceFirst(RegExp(r'^Exception:\s*'), '');
      final waiting = message.toLowerCase().contains('wait') ||
          message.toLowerCase().contains('already');
      setState(() {
        _sending = false;
        if (waiting && !userRequested) {
          _info =
              'Enter the 6-digit code we sent to ${auth.user?.email ?? 'your email'}. '
              'After that you can continue to payment.';
          _error = null;
        } else {
          _error = message.isEmpty
              ? 'Could not send a code. Try again in a moment.'
              : message;
        }
      });
    }
  }

  Future<void> _verify() async {
    final code = _digits;
    if (code.length != 6 || _verifying) return;
    final auth = context.read<AuthController>();
    _api.setAccessToken(auth.token);
    setState(() {
      _verifying = true;
      _error = null;
    });
    try {
      final result = await _api.verifyEmailCode(code);
      if (!mounted) return;
      final userJson = result['user'];
      if (userJson is Map<String, dynamic>) {
        await auth.applyUser(AuthUser.fromJson(userJson));
      } else {
        await auth.refreshMe();
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _verifying = false;
        _error = e.toString().replaceFirst(RegExp(r'^Exception:\s*'), '');
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthController>();
    final isMobile = MediaQuery.of(context).size.width < 700;

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
                'Sign out',
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
                  'Verify your email',
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
                  _info ??
                      'Enter this code to verify your email. After that you can continue to payment.',
                  textAlign: TextAlign.center,
                  style: GoogleFonts.figtree(
                    fontSize: 15,
                    color: Colors.black54,
                    height: 1.45,
                  ),
                ),
                if (_debugCode != null) ...[
                  const SizedBox(height: 24),
                  Container(
                    key: const Key('email-verification-onscreen-code'),
                    padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 20),
                    decoration: BoxDecoration(
                      color: const Color(0xFFF7F4EA),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: _gold, width: 1.5),
                    ),
                    child: Column(
                      children: [
                        Text(
                          'Your verification code',
                          textAlign: TextAlign.center,
                          style: GoogleFonts.figtree(
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                            color: Colors.black54,
                          ),
                        ),
                        const SizedBox(height: 6),
                        Text(
                          _debugCode!,
                          textAlign: TextAlign.center,
                          style: GoogleFonts.figtree(
                            fontSize: 32,
                            fontWeight: FontWeight.w800,
                            letterSpacing: 8,
                            color: _navy,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
                const SizedBox(height: 28),
                TextField(
                  key: const Key('email-verification-code'),
                  controller: _codeController,
                  focusNode: _codeFocus,
                  autofocus: true,
                  textAlign: TextAlign.center,
                  keyboardType: TextInputType.number,
                  textInputAction: TextInputAction.done,
                  maxLength: 6,
                  inputFormatters: [
                    FilteringTextInputFormatter.digitsOnly,
                    LengthLimitingTextInputFormatter(6),
                  ],
                  style: GoogleFonts.figtree(
                    fontSize: 28,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 10,
                    color: _navy,
                  ),
                  decoration: InputDecoration(
                    counterText: '',
                    hintText: '000000',
                    hintStyle: GoogleFonts.figtree(
                      fontSize: 28,
                      fontWeight: FontWeight.w700,
                      letterSpacing: 10,
                      color: Colors.black26,
                    ),
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                    enabledBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                      borderSide: BorderSide(color: Colors.grey.shade300),
                    ),
                    focusedBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                      borderSide: const BorderSide(color: _gold, width: 2),
                    ),
                  ),
                  onChanged: (_) {
                    if (_error != null) setState(() => _error = null);
                    if (_digits.length == 6) _verify();
                  },
                  onSubmitted: (_) => _verify(),
                ),
                if (_error != null) ...[
                  const SizedBox(height: 12),
                  Text(
                    _error!,
                    textAlign: TextAlign.center,
                    style: GoogleFonts.figtree(
                      fontSize: 14,
                      color: _pink,
                      height: 1.35,
                    ),
                  ),
                ],
                const SizedBox(height: 24),
                DecoratedBox(
                  decoration: BoxDecoration(
                    gradient: _brandGradient,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: FilledButton(
                    onPressed: _digits.length == 6 && !_verifying ? _verify : null,
                    style: FilledButton.styleFrom(
                      backgroundColor: Colors.transparent,
                      disabledBackgroundColor: Colors.transparent,
                      shadowColor: Colors.transparent,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 16),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                    ),
                    child: _verifying
                        ? const SizedBox(
                            width: 22,
                            height: 22,
                            child: CircularProgressIndicator(
                              strokeWidth: 2.4,
                              color: Colors.white,
                            ),
                          )
                        : Text(
                            'Verify email',
                            style: GoogleFonts.figtree(
                              fontWeight: FontWeight.bold,
                              fontSize: 16,
                            ),
                          ),
                  ),
                ),
                const SizedBox(height: 12),
                TextButton(
                  onPressed: _sending ? null : () => _sendCode(userRequested: true),
                  child: Text(
                    _sending ? 'Sending…' : 'Resend code',
                    style: GoogleFonts.figtree(
                      color: _navy,
                      fontWeight: FontWeight.w700,
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
