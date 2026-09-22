import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/screens/update_payment_method_screen.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:flutter_application_1/widgets/brand_gradient.dart';
import 'package:flutter_application_1/widgets/user_account_badge.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';

const _navy = Color(0xFF1B264F);
const _pink = Color(0xFFa1375a);
const _surface = Color(0xFFF4F4F9);

/// Account settings: password, payment method, and unsubscribe.
class SettingsScreen extends StatefulWidget {
  const SettingsScreen({
    super.key,
    required this.apiService,
    @visibleForTesting this.authService,
  });

  final ApiService apiService;
  @visibleForTesting
  final AuthService? authService;

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _formKey = GlobalKey<FormState>();
  final _currentPasswordController = TextEditingController();
  final _newPasswordController = TextEditingController();
  final _confirmPasswordController = TextEditingController();

  bool _obscureCurrent = true;
  bool _obscureNew = true;
  bool _obscureConfirm = true;
  bool _editingPassword = false;
  bool _savingPassword = false;
  bool _unsubscribing = false;
  String? _passwordError;
  String? _passwordSuccess;

  late final AuthService _authService =
      widget.authService ?? AuthService();

  @override
  void dispose() {
    _currentPasswordController.dispose();
    _newPasswordController.dispose();
    _confirmPasswordController.dispose();
    super.dispose();
  }

  void _startEditingPassword() {
    setState(() {
      _editingPassword = true;
      _passwordError = null;
      _passwordSuccess = null;
    });
  }

  void _cancelEditingPassword() {
    _currentPasswordController.clear();
    _newPasswordController.clear();
    _confirmPasswordController.clear();
    setState(() {
      _editingPassword = false;
      _savingPassword = false;
      _passwordError = null;
      _passwordSuccess = null;
      _obscureCurrent = true;
      _obscureNew = true;
      _obscureConfirm = true;
    });
  }

  Future<void> _changePassword() async {
    final auth = context.read<AuthController>();
    final token = auth.token;
    if (token == null || token.isEmpty) return;
    if (!(_formKey.currentState?.validate() ?? false)) return;

    setState(() {
      _savingPassword = true;
      _passwordError = null;
      _passwordSuccess = null;
    });

    try {
      await _authService.changePassword(
        token: token,
        currentPassword: _currentPasswordController.text,
        newPassword: _newPasswordController.text,
      );
      if (!mounted) return;
      _currentPasswordController.clear();
      _newPasswordController.clear();
      _confirmPasswordController.clear();
      setState(() {
        _savingPassword = false;
        _editingPassword = false;
        _passwordSuccess = 'Password updated.';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _savingPassword = false;
        _passwordError = e.toString().replaceFirst(RegExp(r'^Exception:\s*'), '');
      });
    }
  }

  Future<void> _unsubscribe() async {
    final auth = context.read<AuthController>();
    final user = auth.user;
    if (user == null || !user.isPaidPremium || _unsubscribing) return;

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogCtx) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        title: Text(
          'Unsubscribe from Premium?',
          style: GoogleFonts.figtree(color: _navy, fontWeight: FontWeight.bold),
        ),
        content: Text(
          'You will keep Premium benefits until ${formatPremiumAccessUntil(user.currentPeriodEnd)}. '
          'After that, access to Nordin\'s AI ends and auto-renewal stops.',
          style: GoogleFonts.figtree(height: 1.45),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogCtx).pop(false),
            child: Text(
              'Keep Premium',
              style: GoogleFonts.figtree(color: _navy, fontWeight: FontWeight.w600),
            ),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogCtx).pop(true),
            style: FilledButton.styleFrom(backgroundColor: _pink),
            child: Text('Unsubscribe', style: GoogleFonts.figtree(fontWeight: FontWeight.bold)),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    setState(() => _unsubscribing = true);
    try {
      widget.apiService.setAccessToken(auth.token);
      final result = await widget.apiService.cancelSubscription();
      final userJson = result['user'];
      if (userJson is Map<String, dynamic>) {
        await auth.applyUser(AuthUser.fromJson(userJson));
      } else {
        await auth.refreshMe();
      }
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            'Auto-renewal is off. Premium stays until '
            '${formatPremiumAccessUntil(auth.user?.currentPeriodEnd)}.',
          ),
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(e.toString().replaceFirst(RegExp(r'^Exception:\s*'), '')),
        ),
      );
    } finally {
      if (mounted) setState(() => _unsubscribing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthController>();
    final user = auth.user;

    return Scaffold(
      backgroundColor: _surface,
      appBar: brandGradientAppBar(
        title: Text('Settings', style: GoogleFonts.figtree(fontWeight: FontWeight.bold)),
      ),
      body: user == null
          ? Center(
              child: Text(
                'Sign in to manage settings.',
                style: GoogleFonts.figtree(color: Colors.black54),
              ),
            )
          : ListView(
              padding: const EdgeInsets.fromLTRB(20, 20, 20, 40),
              children: [
                Text(
                  user.email,
                  style: GoogleFonts.figtree(fontSize: 14, color: Colors.black54),
                ),
                const SizedBox(height: 24),
                Text(
                  'Password',
                  style: GoogleFonts.figtree(fontWeight: FontWeight.bold, color: _navy, fontSize: 16),
                ),
                const SizedBox(height: 8),
                if (!user.hasUsablePassword)
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: Colors.black12),
                    ),
                    child: Text(
                      'You signed in with Google. Password changes are not available '
                      'for this account.',
                      style: GoogleFonts.figtree(height: 1.45, color: Colors.black87),
                    ),
                  )
                else
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: Colors.black12),
                    ),
                    child: !_editingPassword
                        ? Row(
                            children: [
                              Expanded(
                                child: Text(
                                  '••••••••',
                                  style: GoogleFonts.figtree(
                                    fontSize: 16,
                                    letterSpacing: 2,
                                    color: Colors.black54,
                                  ),
                                ),
                              ),
                              TextButton(
                                onPressed: _startEditingPassword,
                                child: Text(
                                  'Edit',
                                  style: GoogleFonts.figtree(
                                    color: _navy,
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                              ),
                            ],
                          )
                        : Form(
                            key: _formKey,
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              children: [
                                Row(
                                  children: [
                                    Expanded(
                                      child: Text(
                                        'Enter your current password to set a new one.',
                                        style: GoogleFonts.figtree(
                                          fontSize: 13,
                                          color: Colors.black54,
                                        ),
                                      ),
                                    ),
                                    TextButton(
                                      onPressed: _savingPassword ? null : _cancelEditingPassword,
                                      child: Text(
                                        'Cancel',
                                        style: GoogleFonts.figtree(
                                          color: Colors.black54,
                                          fontWeight: FontWeight.w600,
                                        ),
                                      ),
                                    ),
                                  ],
                                ),
                                const SizedBox(height: 16),
                                _passwordField(
                                  controller: _currentPasswordController,
                                  label: 'Current password',
                                  obscure: _obscureCurrent,
                                  onToggle: () =>
                                      setState(() => _obscureCurrent = !_obscureCurrent),
                                  validator: (v) {
                                    if (v == null || v.isEmpty) {
                                      return 'Enter your current password';
                                    }
                                    return null;
                                  },
                                ),
                                const SizedBox(height: 12),
                                _passwordField(
                                  controller: _newPasswordController,
                                  label: 'New password',
                                  obscure: _obscureNew,
                                  onToggle: () => setState(() => _obscureNew = !_obscureNew),
                                  validator: (v) {
                                    if (v == null || v.length < 8) {
                                      return 'Use at least 8 characters';
                                    }
                                    return null;
                                  },
                                ),
                                const SizedBox(height: 12),
                                _passwordField(
                                  controller: _confirmPasswordController,
                                  label: 'Confirm new password',
                                  obscure: _obscureConfirm,
                                  onToggle: () =>
                                      setState(() => _obscureConfirm = !_obscureConfirm),
                                  validator: (v) {
                                    if (v != _newPasswordController.text) {
                                      return 'Passwords do not match';
                                    }
                                    return null;
                                  },
                                ),
                                if (_passwordError != null) ...[
                                  const SizedBox(height: 12),
                                  Text(
                                    _passwordError!,
                                    style: GoogleFonts.figtree(
                                      color: Colors.red.shade700,
                                      fontSize: 13,
                                    ),
                                  ),
                                ],
                                const SizedBox(height: 16),
                                FilledButton(
                                  onPressed: _savingPassword ? null : _changePassword,
                                  style: FilledButton.styleFrom(
                                    backgroundColor: _pink,
                                    padding: const EdgeInsets.symmetric(vertical: 14),
                                    shape: RoundedRectangleBorder(
                                      borderRadius: BorderRadius.circular(12),
                                    ),
                                  ),
                                  child: _savingPassword
                                      ? const SizedBox(
                                          height: 20,
                                          width: 20,
                                          child: CircularProgressIndicator(
                                            strokeWidth: 2,
                                            color: Colors.white,
                                          ),
                                        )
                                      : Text(
                                          'Update password',
                                          style: GoogleFonts.figtree(fontWeight: FontWeight.bold),
                                        ),
                                ),
                              ],
                            ),
                          ),
                  ),
                if (_passwordSuccess != null && !_editingPassword) ...[
                  const SizedBox(height: 8),
                  Text(
                    _passwordSuccess!,
                    style: GoogleFonts.figtree(color: Colors.green.shade700, fontSize: 13),
                  ),
                ],
                const SizedBox(height: 28),
                Text(
                  'Subscription',
                  style: GoogleFonts.figtree(fontWeight: FontWeight.bold, color: _navy, fontSize: 16),
                ),
                const SizedBox(height: 8),
                if (user.isPaidPremium) ...[
                  Text(
                    user.cancelAtPeriodEnd
                        ? 'Premium stays active until ${formatPremiumAccessUntil(user.currentPeriodEnd)}. Auto-renewal is off.'
                        : user.pendingBillingPeriod.isNotEmpty
                            ? 'Premium · ${user.billingPeriod.isNotEmpty ? user.billingPeriod : 'active'}. '
                                'Switching to ${user.pendingBillingPeriod} on ${formatPremiumAccessUntil(user.currentPeriodEnd)}.'
                            : 'Premium member${user.billingPeriod.isNotEmpty ? ' · ${user.billingPeriod}' : ''}.',
                    style: GoogleFonts.figtree(fontSize: 13, color: Colors.black54, height: 1.35),
                  ),
                  const SizedBox(height: 12),
                ] else
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Text(
                      'No active Premium subscription.',
                      style: GoogleFonts.figtree(fontSize: 13, color: Colors.black54),
                    ),
                  ),
                if (user.canManagePaymentMethod) ...[
                  SizedBox(
                    width: double.infinity,
                    child: OutlinedButton.icon(
                      onPressed: () {
                        Navigator.of(context).push(
                          MaterialPageRoute(
                            builder: (_) => const UpdatePaymentMethodScreen(),
                          ),
                        );
                      },
                      icon: const Icon(Icons.credit_card, color: _navy),
                      label: Text(
                        'Update payment method',
                        style: GoogleFonts.figtree(color: _navy, fontWeight: FontWeight.bold),
                      ),
                      style: OutlinedButton.styleFrom(
                        side: const BorderSide(color: _navy, width: 1.5),
                        padding: const EdgeInsets.symmetric(vertical: 14),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                      ),
                    ),
                  ),
                ],
                if (user.isPaidPremium && !user.cancelAtPeriodEnd) ...[
                  const SizedBox(height: 12),
                  SizedBox(
                    width: double.infinity,
                    child: OutlinedButton.icon(
                      onPressed: _unsubscribing ? null : _unsubscribe,
                      icon: const Icon(Icons.cancel_outlined, color: _pink),
                      label: Text(
                        _unsubscribing ? 'Working…' : 'Unsubscribe',
                        style: GoogleFonts.figtree(color: _pink, fontWeight: FontWeight.bold),
                      ),
                      style: OutlinedButton.styleFrom(
                        side: const BorderSide(color: _pink),
                        padding: const EdgeInsets.symmetric(vertical: 14),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                      ),
                    ),
                  ),
                ],
              ],
            ),
    );
  }

  Widget _passwordField({
    required TextEditingController controller,
    required String label,
    required bool obscure,
    required VoidCallback onToggle,
    required String? Function(String?) validator,
  }) {
    return TextFormField(
      controller: controller,
      obscureText: obscure,
      validator: validator,
      decoration: InputDecoration(
        labelText: label,
        filled: true,
        fillColor: _surface,
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
        suffixIcon: IconButton(
          onPressed: onToggle,
          icon: Icon(obscure ? Icons.visibility_outlined : Icons.visibility_off_outlined),
        ),
      ),
    );
  }
}
