import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/screens/email_verification_screen.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _SentEmailApi extends ApiService {
  int sends = 0;

  @override
  void setAccessToken(String? token) {}

  @override
  Future<Map<String, dynamic>> sendEmailCode() async {
    sends += 1;
    return {
      'ok': true,
      'already_verified': false,
      'email': 'newpaid@test.com',
      'emailed': true,
      'debug_code': '482193',
    };
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUpAll(() {
    GoogleFonts.config.allowRuntimeFetching = false;
  });

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    EmailVerificationScreen.debugResetAutoSendGuard();
  });

  testWidgets('asks the member to insert the 6-digit email code', (tester) async {
    final auth = AuthController(restoreSession: false);
    auth.sessionReady = true;
    auth.token = 'tok';
    auth.user = const AuthUser(
      id: '3',
      email: 'newpaid@test.com',
      name: 'New Paid',
      isPremium: true,
      emailVerified: false,
      subscriptionStatus: 'active',
    );

    await tester.pumpWidget(
      ChangeNotifierProvider<AuthController>.value(
        value: auth,
        child: const MaterialApp(
          home: EmailVerificationScreen(autoSend: false),
        ),
      ),
    );
    await tester.pump();

    expect(find.text('Verify your email'), findsOneWidget);
    expect(
      find.text(
        'Enter the 6-digit code we sent to your email. After that you can continue to payment.',
      ),
      findsOneWidget,
    );
    expect(find.byKey(const Key('email-verification-code')), findsOneWidget);
    expect(
      tester.widget<Text>(find.text('Verify email')).style?.color,
      Colors.white,
    );

    await tester.enterText(find.byKey(const Key('email-verification-code')), '12ab34');
    await tester.pump();
    expect(
      tester.widget<TextField>(find.byKey(const Key('email-verification-code'))).controller?.text,
      '1234',
    );
  });

  testWidgets('does not show an on-screen verification code even if the API leaks one', (tester) async {
    final auth = AuthController(restoreSession: false);
    auth.sessionReady = true;
    auth.token = 'tok';
    auth.user = const AuthUser(
      id: '3',
      email: 'newpaid@test.com',
      name: 'New Paid',
      emailVerified: false,
    );

    await tester.pumpWidget(
      ChangeNotifierProvider<AuthController>.value(
        value: auth,
        child: MaterialApp(
          home: EmailVerificationScreen(
            api: _SentEmailApi(),
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump();

    expect(find.byKey(const Key('email-verification-onscreen-code')), findsNothing);
    expect(find.text('Your verification code'), findsNothing);
    expect(find.text('482193'), findsNothing);
    expect(
      find.text(
        'Enter the 6-digit code we sent to newpaid@test.com. After that you can continue to payment.',
      ),
      findsOneWidget,
    );
  });

  testWidgets('opening the screen twice does not request a second code', (tester) async {
    final auth = AuthController(restoreSession: false);
    auth.sessionReady = true;
    auth.token = 'tok';
    auth.user = const AuthUser(
      id: '3',
      email: 'newpaid@test.com',
      name: 'New Paid',
      emailVerified: false,
    );
    final api = _SentEmailApi();

    Future<void> openScreen() async {
      await tester.pumpWidget(
        ChangeNotifierProvider<AuthController>.value(
          value: auth,
          child: MaterialApp(
            home: EmailVerificationScreen(api: api),
          ),
        ),
      );
      await tester.pump();
      await tester.pump();
    }

    await openScreen();
    await openScreen();

    expect(api.sends, 1);
  });
}
