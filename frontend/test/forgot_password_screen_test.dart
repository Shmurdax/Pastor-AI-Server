import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/screens/forgot_password_screen.dart';
import 'package:flutter_application_1/screens/login_screen.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _FakeAuth extends AuthService {
  int sends = 0;
  String? resetEmail;
  String? resetCode;
  String? resetPassword;

  @override
  Future<String> requestPasswordReset({required String email}) async {
    sends += 1;
    return 'If an account with that email exists, we sent password reset instructions.';
  }

  @override
  Future<String> resetPassword({
    required String email,
    required String code,
    required String newPassword,
  }) async {
    resetEmail = email;
    resetCode = code;
    resetPassword = newPassword;
    return 'Password updated. You can sign in with your new password.';
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUpAll(() {
    GoogleFonts.config.allowRuntimeFetching = false;
  });

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('sign in page opens forgot password', (tester) async {
    final auth = AuthController(restoreSession: false);
    auth.sessionReady = true;

    await tester.pumpWidget(
      ChangeNotifierProvider<AuthController>.value(
        value: auth,
        child: const MaterialApp(home: LoginScreen()),
      ),
    );
    await tester.pump();

    expect(find.text('Forgot password?'), findsOneWidget);
    await tester.tap(find.text('Forgot password?'));
    await tester.pumpAndSettle();

    expect(find.text('Reset your password'), findsOneWidget);
    expect(find.text('Email me a code'), findsOneWidget);
  });

  testWidgets('a valid code updates the password and returns to sign in', (tester) async {
    final fake = _FakeAuth();

    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) {
            return TextButton(
              onPressed: () {
                Navigator.of(context).push(
                  MaterialPageRoute(
                    builder: (_) => ForgotPasswordScreen(
                      initialEmail: 'member@church.org',
                      authService: fake,
                    ),
                  ),
                );
              },
              child: const Text('Open reset'),
            );
          },
        ),
      ),
    );

    await tester.tap(find.text('Open reset'));
    await tester.pumpAndSettle();

    expect(find.text('member@church.org'), findsOneWidget);
    await tester.tap(find.text('Email me a code'));
    await tester.pumpAndSettle();

    expect(find.text('6-digit code'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('forgot-password-code')), '482193');
    await tester.enterText(find.byKey(const Key('forgot-password-new')), 'BrandNewPass123!');
    await tester.enterText(find.byKey(const Key('forgot-password-confirm')), 'BrandNewPass123!');
    await tester.tap(find.text('Update password'));
    await tester.pumpAndSettle();

    expect(fake.sends, 1);
    expect(fake.resetEmail, 'member@church.org');
    expect(fake.resetCode, '482193');
    expect(fake.resetPassword, 'BrandNewPass123!');
    expect(find.text('Reset your password'), findsNothing);
    expect(find.text('Open reset'), findsOneWidget);
  });
}
