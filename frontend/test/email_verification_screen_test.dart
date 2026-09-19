import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/screens/email_verification_screen.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

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
        'Enter this code to verify your email. We sent a 6-digit code to newpaid@test.com.',
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
}
