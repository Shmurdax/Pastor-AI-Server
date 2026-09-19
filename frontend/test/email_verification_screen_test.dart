import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/screens/email_verification_screen.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _OnscreenCodeApi extends ApiService {
  @override
  void setAccessToken(String? token) {}

  @override
  Future<Map<String, dynamic>> sendEmailCode() async {
    return {
      'ok': true,
      'already_verified': false,
      'email': 'newpaid@test.com',
      'emailed': false,
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
        'Enter this code to verify your email. After that you can continue to payment.',
      ),
      findsOneWidget,
    );
    expect(find.byKey(const Key('email-verification-code')), findsOneWidget);

    await tester.enterText(find.byKey(const Key('email-verification-code')), '12ab34');
    await tester.pump();
    expect(
      tester.widget<TextField>(find.byKey(const Key('email-verification-code'))).controller?.text,
      '1234',
    );
  });

  testWidgets('shows the pre-generated on-screen verification code', (tester) async {
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
            api: _OnscreenCodeApi(),
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump();

    expect(find.byKey(const Key('email-verification-onscreen-code')), findsOneWidget);
    expect(find.text('Your verification code'), findsOneWidget);
    expect(find.text('482193'), findsOneWidget);
    expect(
      find.text(
        'Enter this code to verify your email. After that you can continue to payment.',
      ),
      findsOneWidget,
    );
  });
}
