import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:google_fonts/google_fonts.dart';

const _navy = Color(0xFF1B264F);
const _gold = Color(0xFFD4AF37);
const _pink = Color(0xFFa1375a);

InputDecoration _fieldDecoration(String label) => InputDecoration(
      labelText: label,
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

/// Sign-in recovery: email a 6-digit code, then set a new password.
class ForgotPasswordScreen extends StatefulWidget {
  const ForgotPasswordScreen({
    super.key,
    this.initialEmail = '',
    @visibleForTesting this.authService,
  });

  final String initialEmail;
  final AuthService? authService;

  @override
  State<ForgotPasswordScreen> createState() => _ForgotPasswordScreenState();
}

class _ForgotPasswordScreenState extends State<ForgotPasswordScreen> {
  late final AuthService _auth = widget.authService ?? AuthService();
  late final TextEditingController _emailController =
      TextEditingController(text: widget.initialEmail);
  final _codeController = TextEditingController();
  final _passwordController = TextEditingController();
  final _confirmController = TextEditingController();

  bool _codeSent = false;
  bool _sending = false;
  bool _resetting = false;
  bool _obscurePassword = true;
  bool _obscureConfirm = true;
  String? _error;
  String? _info;

  bool get _busy => _sending || _resetting;

  @override
  void dispose() {
    _emailController.dispose();
    _codeController.dispose();
    _passwordController.dispose();
    _confirmController.dispose();
    super.dispose();
  }

  String? _emailError(String value) {
    final email = value.trim();
    if (email.isEmpty) return 'Enter your email';
    if (!email.contains('@')) return 'Enter a valid email';
    return null;
  }

  Future<void> _sendCode() async {
    final emailError = _emailError(_emailController.text);
    if (emailError != null) {
      setState(() {
        _error = emailError;
        _info = null;
      });
      return;
    }
    setState(() {
      _sending = true;
      _error = null;
    });
    try {
      final detail = await _auth.requestPasswordReset(email: _emailController.text.trim());
      if (!mounted) return;
      setState(() {
        _sending = false;
        _codeSent = true;
        _info = detail;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _sending = false;
        _error = e.toString().replaceFirst(RegExp(r'^Exception:\s*'), '');
      });
    }
  }

  Future<void> _resetPassword() async {
    final emailError = _emailError(_emailController.text);
    final code = _codeController.text.replaceAll(RegExp(r'\D'), '');
    final password = _passwordController.text;
    final confirm = _confirmController.text;
    String? error = emailError;
    if (error == null && code.length != 6) {
      error = 'Enter the 6-digit code from your email';
    }
    if (error == null && password.length < 8) {
      error = 'Password must be at least 8 characters';
    }
    if (error == null && password != confirm) {
      error = 'Passwords do not match';
    }
    if (error != null) {
      setState(() => _error = error);
      return;
    }

    setState(() {
      _resetting = true;
      _error = null;
    });
    try {
      await _auth.resetPassword(
        email: _emailController.text.trim(),
        code: code,
        newPassword: password,
      );
      if (!mounted) return;
      Navigator.of(context).pop(true);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _resetting = false;
        _error = e.toString().replaceFirst(RegExp(r'^Exception:\s*'), '');
      });
    }
  }

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
          onPressed: _busy ? null : () => Navigator.of(context).maybePop(),
        ),
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: EdgeInsets.all(isMobile ? 24 : 40),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 440),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Center(
                  child: Image.asset(
                    'assets/images/nordins_main_logo.png',
                    height: isMobile ? 80 : 95,
                    fit: BoxFit.contain,
                  ),
                ),
                const SizedBox(height: 24),
                Text(
                  'Reset your password',
                  textAlign: TextAlign.center,
                  style: GoogleFonts.figtree(
                    fontSize: 28,
                    fontWeight: FontWeight.bold,
                    color: _navy,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  _info ??
                      'Enter the email on your account. If it uses a password, we will send a 6-digit code.',
                  textAlign: TextAlign.center,
                  style: GoogleFonts.figtree(fontSize: 14, color: Colors.black54, height: 1.4),
                ),
                const SizedBox(height: 32),
                if (_error != null) ...[
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: Colors.red.shade50,
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: Colors.red.shade200),
                    ),
                    child: Text(
                      _error!,
                      style: GoogleFonts.figtree(color: Colors.red.shade800, fontSize: 14),
                    ),
                  ),
                  const SizedBox(height: 16),
                ],
                TextFormField(
                  key: const Key('forgot-password-email'),
                  controller: _emailController,
                  enabled: !_busy,
                  keyboardType: TextInputType.emailAddress,
                  autofillHints: const [AutofillHints.email],
                  decoration: _fieldDecoration('Email'),
                ),
                if (_codeSent) ...[
                  const SizedBox(height: 16),
                  TextFormField(
                    key: const Key('forgot-password-code'),
                    controller: _codeController,
                    enabled: !_busy,
                    keyboardType: TextInputType.number,
                    textAlign: TextAlign.center,
                    inputFormatters: [
                      FilteringTextInputFormatter.digitsOnly,
                      LengthLimitingTextInputFormatter(6),
                    ],
                    style: GoogleFonts.figtree(
                      fontSize: 22,
                      fontWeight: FontWeight.w700,
                      letterSpacing: 8,
                      color: _navy,
                    ),
                    decoration: _fieldDecoration('6-digit code'),
                  ),
                  const SizedBox(height: 16),
                  TextFormField(
                    key: const Key('forgot-password-new'),
                    controller: _passwordController,
                    enabled: !_busy,
                    obscureText: _obscurePassword,
                    autofillHints: const [AutofillHints.newPassword],
                    decoration: _fieldDecoration('New password').copyWith(
                      suffixIcon: IconButton(
                        icon: Icon(
                          _obscurePassword ? Icons.visibility_off : Icons.visibility,
                          color: _navy,
                        ),
                        onPressed: () => setState(() => _obscurePassword = !_obscurePassword),
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                  TextFormField(
                    key: const Key('forgot-password-confirm'),
                    controller: _confirmController,
                    enabled: !_busy,
                    obscureText: _obscureConfirm,
                    decoration: _fieldDecoration('Confirm new password').copyWith(
                      suffixIcon: IconButton(
                        icon: Icon(
                          _obscureConfirm ? Icons.visibility_off : Icons.visibility,
                          color: _navy,
                        ),
                        onPressed: () => setState(() => _obscureConfirm = !_obscureConfirm),
                      ),
                    ),
                  ),
                ],
                const SizedBox(height: 24),
                FilledButton(
                  key: Key(_codeSent ? 'forgot-password-submit' : 'forgot-password-send'),
                  onPressed: _busy ? null : (_codeSent ? _resetPassword : _sendCode),
                  style: FilledButton.styleFrom(
                    backgroundColor: _navy,
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 16),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                  ),
                  child: _busy
                      ? const SizedBox(
                          height: 20,
                          width: 20,
                          child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                        )
                      : Text(
                          _codeSent ? 'Update password' : 'Email me a code',
                          style: GoogleFonts.figtree(fontWeight: FontWeight.bold, fontSize: 16),
                        ),
                ),
                if (_codeSent) ...[
                  const SizedBox(height: 8),
                  TextButton(
                    onPressed: _busy ? null : _sendCode,
                    child: Text(
                      'Resend code',
                      style: GoogleFonts.figtree(color: _pink, fontWeight: FontWeight.bold),
                    ),
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
