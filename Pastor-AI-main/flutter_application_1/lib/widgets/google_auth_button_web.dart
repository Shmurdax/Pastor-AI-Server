import 'package:flutter/material.dart';
import 'package:google_sign_in_web/web_only.dart' as gsi_web;

/// Web Google button — uses GIS `renderButton`, which returns a real idToken.
///
/// Do not call `GoogleSignIn.signIn()` on web for authentication; that flow only
/// yields an accessToken and breaks backend ID-token verification.
class GoogleAuthButton extends StatelessWidget {
  const GoogleAuthButton({
    super.key,
    required this.onPressed,
    this.label = 'Sign in with Google',
    this.enabled = true,
  });

  /// Unused on web — GIS owns the click handler. Kept so call sites can share
  /// a single widget API with mobile.
  final VoidCallback? onPressed;
  final String label;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    if (!enabled) {
      return const SizedBox(height: 44);
    }

    final isSignUp = label.toLowerCase().contains('up');

    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(minWidth: 240, maxWidth: 400),
        child: SizedBox(
          height: 44,
          child: gsi_web.renderButton(
            configuration: gsi_web.GSIButtonConfiguration(
              type: gsi_web.GSIButtonType.standard,
              theme: gsi_web.GSIButtonTheme.outline,
              size: gsi_web.GSIButtonSize.large,
              text: isSignUp
                  ? gsi_web.GSIButtonText.signupWith
                  : gsi_web.GSIButtonText.signinWith,
              shape: gsi_web.GSIButtonShape.rectangular,
              logoAlignment: gsi_web.GSIButtonLogoAlignment.left,
              minimumWidth: 240,
            ),
          ),
        ),
      ),
    );
  }
}
