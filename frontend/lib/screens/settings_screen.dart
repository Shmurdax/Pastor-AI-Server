import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/l10n/app_locale.dart';
import 'package:flutter_application_1/l10n/app_strings.dart';
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

/// Account settings: Account (name/email/password), language, and subscription.
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
  final _nameFormKey = GlobalKey<FormState>();
  final _emailFormKey = GlobalKey<FormState>();
  final _passwordFormKey = GlobalKey<FormState>();

  final _nameController = TextEditingController();
  final _emailController = TextEditingController();
  final _emailPasswordController = TextEditingController();
  final _currentPasswordController = TextEditingController();
  final _newPasswordController = TextEditingController();
  final _confirmPasswordController = TextEditingController();

  bool _editingName = false;
  bool _editingEmail = false;
  bool _editingPassword = false;

  bool _obscureEmailPassword = true;
  bool _obscureCurrent = true;
  bool _obscureNew = true;
  bool _obscureConfirm = true;

  bool _savingName = false;
  bool _savingEmail = false;
  bool _savingPassword = false;
  bool _unsubscribing = false;

  String? _nameError;
  String? _nameSuccess;
  String? _emailError;
  String? _emailSuccess;
  String? _passwordError;
  String? _passwordSuccess;

  late final AuthService _authService = widget.authService ?? AuthService();

  @override
  void dispose() {
    _nameController.dispose();
    _emailController.dispose();
    _emailPasswordController.dispose();
    _currentPasswordController.dispose();
    _newPasswordController.dispose();
    _confirmPasswordController.dispose();
    super.dispose();
  }

  void _startEditingName(AuthUser user) {
    _cancelEditingEmail();
    _cancelEditingPassword();
    _nameController.text = user.name;
    setState(() {
      _editingName = true;
      _nameError = null;
      _nameSuccess = null;
    });
  }

  void _cancelEditingName() {
    _nameController.clear();
    setState(() {
      _editingName = false;
      _savingName = false;
      _nameError = null;
    });
  }

  void _startEditingEmail(AuthUser user) {
    _cancelEditingName();
    _cancelEditingPassword();
    _emailController.text = user.email;
    _emailPasswordController.clear();
    setState(() {
      _editingEmail = true;
      _emailError = null;
      _emailSuccess = null;
      _obscureEmailPassword = true;
    });
  }

  void _cancelEditingEmail() {
    _emailController.clear();
    _emailPasswordController.clear();
    setState(() {
      _editingEmail = false;
      _savingEmail = false;
      _emailError = null;
      _obscureEmailPassword = true;
    });
  }

  void _startEditingPassword() {
    _cancelEditingName();
    _cancelEditingEmail();
    setState(() {
      _editingPassword = true;
      _passwordError = null;
      _passwordSuccess = null;
      _obscureCurrent = true;
      _obscureNew = true;
      _obscureConfirm = true;
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
      _obscureCurrent = true;
      _obscureNew = true;
      _obscureConfirm = true;
    });
  }

  Future<void> _saveName() async {
    final auth = context.read<AuthController>();
    final token = auth.token;
    if (token == null || token.isEmpty) return;
    if (!(_nameFormKey.currentState?.validate() ?? false)) return;

    setState(() {
      _savingName = true;
      _nameError = null;
      _nameSuccess = null;
    });

    try {
      final updated = await _authService.changeName(
        token: token,
        name: _nameController.text.trim(),
      );
      await auth.applyUser(updated);
      if (!mounted) return;
      _nameController.clear();
      setState(() {
        _savingName = false;
        _editingName = false;
        _nameSuccess = context.read<LocaleController>().strings.nameUpdated;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _savingName = false;
        _nameError = e.toString().replaceFirst(RegExp(r'^Exception:\s*'), '');
      });
    }
  }

  Future<void> _saveEmail() async {
    final auth = context.read<AuthController>();
    final token = auth.token;
    if (token == null || token.isEmpty) return;
    if (!(_emailFormKey.currentState?.validate() ?? false)) return;

    setState(() {
      _savingEmail = true;
      _emailError = null;
      _emailSuccess = null;
    });

    try {
      final updated = await _authService.changeEmail(
        token: token,
        email: _emailController.text.trim(),
        currentPassword: _emailPasswordController.text,
      );
      await auth.applyUser(updated);
      if (!mounted) return;
      _emailController.clear();
      _emailPasswordController.clear();
      setState(() {
        _savingEmail = false;
        _editingEmail = false;
        _emailSuccess = context.read<LocaleController>().strings.emailUpdated;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _savingEmail = false;
        _emailError = e.toString().replaceFirst(RegExp(r'^Exception:\s*'), '');
      });
    }
  }

  Future<void> _changePassword() async {
    final auth = context.read<AuthController>();
    final token = auth.token;
    if (token == null || token.isEmpty) return;
    if (!(_passwordFormKey.currentState?.validate() ?? false)) return;

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
        _passwordSuccess = context.read<LocaleController>().strings.passwordUpdated;
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
    final s = context.watch<LocaleController>().strings;
    final user = auth.user;

    return Scaffold(
      backgroundColor: _surface,
      appBar: brandGradientAppBar(
        title: Text(s.settings, style: GoogleFonts.figtree(fontWeight: FontWeight.bold)),
      ),
      body: user == null
          ? Center(
              child: Text(
                s.signInToManageSettings,
                style: GoogleFonts.figtree(color: Colors.black54),
              ),
            )
          : ListView(
              padding: const EdgeInsets.fromLTRB(20, 20, 20, 40),
              children: [
                _sectionHeading(s.account),
                const SizedBox(height: 8),
                _card(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      _accountNameBlock(user, s),
                      const Divider(height: 28),
                      _accountEmailBlock(user, s),
                      const Divider(height: 28),
                      _accountPasswordBlock(user, s),
                    ],
                  ),
                ),
                if (_nameSuccess != null && !_editingName) ...[
                  const SizedBox(height: 8),
                  _successText(_nameSuccess!),
                ],
                if (_emailSuccess != null && !_editingEmail) ...[
                  const SizedBox(height: 8),
                  _successText(_emailSuccess!),
                ],
                if (_passwordSuccess != null && !_editingPassword) ...[
                  const SizedBox(height: 8),
                  _successText(_passwordSuccess!),
                ],
                const SizedBox(height: 28),
                _sectionHeading(s.language),
                const SizedBox(height: 8),
                Text(
                  s.languageSettingHint,
                  style: GoogleFonts.figtree(fontSize: 13, color: Colors.black54, height: 1.35),
                ),
                const SizedBox(height: 12),
                _languageCard(),
                const SizedBox(height: 28),
                _sectionHeading(s.subscription),
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

  Widget _accountNameBlock(AuthUser user, AppStrings s) {
    if (!_editingName) {
      return _collapsedLabeledRow(
        label: s.name,
        value: user.name.isEmpty ? '—' : user.name,
        onEdit: () => _startEditingName(user),
        editKey: const Key('edit-name'),
        editLabel: s.edit,
      );
    }
    return Form(
      key: _nameFormKey,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _editHeader(
            hint: s.updateNameHint,
            onCancel: _savingName ? null : _cancelEditingName,
            cancelLabel: s.cancel,
          ),
          const SizedBox(height: 16),
          TextFormField(
            controller: _nameController,
            validator: (v) {
              if (v == null || v.trim().isEmpty) return s.enterAName;
              return null;
            },
            decoration: _fieldDecoration(s.name),
          ),
          if (_nameError != null) ...[
            const SizedBox(height: 12),
            _errorText(_nameError!),
          ],
          const SizedBox(height: 16),
          _primaryButton(
            label: s.updateName,
            loading: _savingName,
            onPressed: _saveName,
          ),
        ],
      ),
    );
  }

  Widget _accountEmailBlock(AuthUser user, AppStrings s) {
    if (!user.hasUsablePassword) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            s.email,
            style: GoogleFonts.figtree(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: Colors.black45,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            s.googleEmailUnavailable,
            style: GoogleFonts.figtree(height: 1.45, color: Colors.black87),
          ),
        ],
      );
    }
    if (!_editingEmail) {
      return _collapsedLabeledRow(
        label: s.email,
        value: user.email,
        onEdit: () => _startEditingEmail(user),
        editKey: const Key('edit-email'),
        editLabel: s.edit,
      );
    }
    return Form(
      key: _emailFormKey,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _editHeader(
            hint: s.updateEmailHint,
            onCancel: _savingEmail ? null : _cancelEditingEmail,
            cancelLabel: s.cancel,
          ),
          const SizedBox(height: 16),
          TextFormField(
            controller: _emailController,
            keyboardType: TextInputType.emailAddress,
            validator: (v) {
              final value = (v ?? '').trim();
              if (value.isEmpty || !value.contains('@')) {
                return s.enterValidEmail;
              }
              return null;
            },
            decoration: _fieldDecoration(s.newEmail),
          ),
          const SizedBox(height: 12),
          _passwordField(
            controller: _emailPasswordController,
            label: s.currentPassword,
            obscure: _obscureEmailPassword,
            onToggle: () => setState(
              () => _obscureEmailPassword = !_obscureEmailPassword,
            ),
            validator: (v) {
              if (v == null || v.isEmpty) return s.enterCurrentPassword;
              return null;
            },
          ),
          if (_emailError != null) ...[
            const SizedBox(height: 12),
            _errorText(_emailError!),
          ],
          const SizedBox(height: 16),
          _primaryButton(
            label: s.updateEmail,
            loading: _savingEmail,
            onPressed: _saveEmail,
          ),
        ],
      ),
    );
  }

  Widget _accountPasswordBlock(AuthUser user, AppStrings s) {
    if (!user.hasUsablePassword) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            s.password,
            style: GoogleFonts.figtree(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: Colors.black45,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            s.googlePasswordUnavailable,
            style: GoogleFonts.figtree(height: 1.45, color: Colors.black87),
          ),
        ],
      );
    }
    if (!_editingPassword) {
      return _collapsedLabeledRow(
        label: s.password,
        value: '••••••••',
        valueStyle: GoogleFonts.figtree(
          fontSize: 16,
          letterSpacing: 2,
          color: Colors.black54,
        ),
        onEdit: _startEditingPassword,
        editKey: const Key('edit-password'),
        editLabel: s.edit,
      );
    }
    return Form(
      key: _passwordFormKey,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _editHeader(
            hint: s.updatePasswordHint,
            onCancel: _savingPassword ? null : _cancelEditingPassword,
            cancelLabel: s.cancel,
          ),
          const SizedBox(height: 16),
          _passwordField(
            controller: _currentPasswordController,
            label: s.currentPassword,
            obscure: _obscureCurrent,
            onToggle: () => setState(() => _obscureCurrent = !_obscureCurrent),
            validator: (v) {
              if (v == null || v.isEmpty) return s.enterCurrentPassword;
              return null;
            },
          ),
          const SizedBox(height: 12),
          _passwordField(
            controller: _newPasswordController,
            label: s.newPassword,
            obscure: _obscureNew,
            onToggle: () => setState(() => _obscureNew = !_obscureNew),
            validator: (v) {
              if (v == null || v.length < 8) return s.passwordTooShort;
              return null;
            },
          ),
          const SizedBox(height: 12),
          _passwordField(
            controller: _confirmPasswordController,
            label: s.confirmNewPassword,
            obscure: _obscureConfirm,
            onToggle: () => setState(() => _obscureConfirm = !_obscureConfirm),
            validator: (v) {
              if (v != _newPasswordController.text) {
                return s.passwordsDoNotMatch;
              }
              return null;
            },
          ),
          if (_passwordError != null) ...[
            const SizedBox(height: 12),
            _errorText(_passwordError!),
          ],
          const SizedBox(height: 16),
          _primaryButton(
            label: s.updatePassword,
            loading: _savingPassword,
            onPressed: _changePassword,
          ),
        ],
      ),
    );
  }

  Widget _languageCard() {
    final locale = context.watch<LocaleController>();
    return _card(
      child: Material(
        color: Colors.white,
        child: Column(
          children: [
            for (var i = 0; i < kSupportedAppLanguages.length; i++) ...[
              if (i > 0) const Divider(height: 1),
              RadioListTile<String>(
                key: Key('language-${kSupportedAppLanguages[i].code}'),
                value: kSupportedAppLanguages[i].code,
                groupValue: locale.languageCode,
                contentPadding: EdgeInsets.zero,
                activeColor: _navy,
                title: Text(
                  kSupportedAppLanguages[i].label,
                  style: GoogleFonts.figtree(
                    color: _navy,
                    fontWeight: kSupportedAppLanguages[i].code == locale.languageCode
                        ? FontWeight.w700
                        : FontWeight.w500,
                  ),
                ),
                onChanged: (code) {
                  if (code != null) {
                    unawaited(locale.setLanguageCode(code));
                  }
                },
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _sectionHeading(String text) {
    return Text(
      text,
      style: GoogleFonts.figtree(fontWeight: FontWeight.bold, color: _navy, fontSize: 16),
    );
  }

  Widget _card({required Widget child}) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.black12),
      ),
      child: child,
    );
  }

  Widget _collapsedLabeledRow({
    required String label,
    required String value,
    required VoidCallback onEdit,
    required Key editKey,
    required String editLabel,
    TextStyle? valueStyle,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: GoogleFonts.figtree(
            fontSize: 12,
            fontWeight: FontWeight.w600,
            color: Colors.black45,
          ),
        ),
        const SizedBox(height: 4),
        Row(
          children: [
            Expanded(
              child: Text(
                value,
                style: valueStyle ??
                    GoogleFonts.figtree(
                      fontSize: 15,
                      color: Colors.black87,
                      fontWeight: FontWeight.w500,
                    ),
              ),
            ),
            TextButton(
              key: editKey,
              onPressed: onEdit,
              child: Text(
                editLabel,
                style: GoogleFonts.figtree(color: _navy, fontWeight: FontWeight.w700),
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _editHeader({
    required String hint,
    required VoidCallback? onCancel,
    required String cancelLabel,
  }) {
    return Row(
      children: [
        Expanded(
          child: Text(
            hint,
            style: GoogleFonts.figtree(fontSize: 13, color: Colors.black54),
          ),
        ),
        TextButton(
          onPressed: onCancel,
          child: Text(
            cancelLabel,
            style: GoogleFonts.figtree(color: Colors.black54, fontWeight: FontWeight.w600),
          ),
        ),
      ],
    );
  }

  InputDecoration _fieldDecoration(String label) {
    return InputDecoration(
      labelText: label,
      filled: true,
      fillColor: _surface,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
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
      decoration: _fieldDecoration(label).copyWith(
        suffixIcon: IconButton(
          onPressed: onToggle,
          icon: Icon(obscure ? Icons.visibility_outlined : Icons.visibility_off_outlined),
        ),
      ),
    );
  }

  Widget _primaryButton({
    required String label,
    required bool loading,
    required VoidCallback onPressed,
  }) {
    return FilledButton(
      onPressed: loading ? null : onPressed,
      style: FilledButton.styleFrom(
        backgroundColor: _pink,
        padding: const EdgeInsets.symmetric(vertical: 14),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      ),
      child: loading
          ? const SizedBox(
              height: 20,
              width: 20,
              child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
            )
          : Text(label, style: GoogleFonts.figtree(fontWeight: FontWeight.bold)),
    );
  }

  Widget _errorText(String text) {
    return Text(
      text,
      style: GoogleFonts.figtree(color: Colors.red.shade700, fontSize: 13),
    );
  }

  Widget _successText(String text) {
    return Text(
      text,
      style: GoogleFonts.figtree(color: Colors.green.shade700, fontSize: 13),
    );
  }
}
