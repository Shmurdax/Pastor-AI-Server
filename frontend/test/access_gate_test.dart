import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/l10n/app_locale.dart';
import 'package:flutter_application_1/main.dart';
import 'package:flutter_application_1/screens/login_screen.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

Widget _wrap(AuthController auth, {Widget? home}) {
  return MultiProvider(
    providers: [
      ChangeNotifierProvider<AuthController>.value(value: auth),
      ChangeNotifierProvider(create: (_) => LocaleController()),
    ],
    child: MaterialApp(home: home ?? const AppAccessGate()),
  );
}

AuthController _readyAuth({AuthUser? user, String? token}) {
  final auth = AuthController(restoreSession: false);
  auth.user = user;
  auth.token = token;
  auth.sessionReady = true;
  return auth;
}

void _useWideSurface(WidgetTester tester) {
  tester.view.physicalSize = const Size(1400, 1000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUpAll(() {
    GoogleFonts.config.allowRuntimeFetching = false;
  });

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('logged-out visitors see the marketing landing page', (tester) async {
    await tester.pumpWidget(_wrap(_readyAuth()));
    await tester.pump();

    expect(find.text("Nordin's AI"), findsOneWidget);
    expect(find.text('Get started'), findsOneWidget);
    expect(find.text('Sign in'), findsWidgets);
    expect(find.text("Welcome to the Nordin's AI Assistant"), findsNothing);
  });

  testWidgets('landing fits a narrow phone viewport', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(_wrap(_readyAuth()));
    await tester.pump();

    expect(find.text('Get started'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('Get started opens the create-account screen', (tester) async {
    await tester.pumpWidget(_wrap(_readyAuth()));
    await tester.pump();

    await tester.tap(find.text('Get started'));
    await tester.pump();
    await tester.pump();

    expect(find.text('Create your account'), findsOneWidget);
    expect(
      find.text('Create an account, then complete your subscription to get access.'),
      findsOneWidget,
    );
  });

  testWidgets('signed-in unpaid users see the paywall, not chat', (tester) async {
    final auth = _readyAuth(
      token: 'tok',
      user: const AuthUser(
        id: '2',
        email: 'free@test.com',
        name: 'Free User',
      ),
    );
    await tester.pumpWidget(_wrap(auth));
    await tester.pump();

    expect(find.text('Complete your subscription'), findsOneWidget);
    expect(find.text('Continue to checkout'), findsOneWidget);
    expect(find.text("Welcome to the Nordin's AI Assistant"), findsNothing);
  });

  testWidgets('paywall fits a narrow phone viewport', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final auth = _readyAuth(
      token: 'tok',
      user: const AuthUser(
        id: '2',
        email: 'free@test.com',
        name: 'Free User',
      ),
    );
    await tester.pumpWidget(_wrap(auth));
    await tester.pump();

    expect(find.text('Complete your subscription'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('premium members open chat', (tester) async {
    _useWideSurface(tester);
    final auth = _readyAuth(
      token: 'tok',
      user: const AuthUser(
        id: '1',
        email: 'paid@test.com',
        name: 'Paid User',
        isPremium: true,
        subscriptionStatus: 'active',
      ),
    );
    await tester.pumpWidget(_wrap(auth));
    await tester.pump();

    expect(find.text("Welcome to the Nordin's AI Assistant"), findsOneWidget);
    expect(find.text('Complete your subscription'), findsNothing);
    expect(find.text('Get started'), findsNothing);
  });

  testWidgets('staff open chat without a paid subscription', (tester) async {
    _useWideSurface(tester);
    final auth = _readyAuth(
      token: 'tok',
      user: const AuthUser(
        id: '9',
        email: 'staff@test.com',
        name: 'Staff User',
        isStaff: true,
      ),
    );
    await tester.pumpWidget(_wrap(auth));
    await tester.pump();

    expect(find.text("Welcome to the Nordin's AI Assistant"), findsOneWidget);
  });

  testWidgets('login screen no longer offers guest access', (tester) async {
    await tester.pumpWidget(_wrap(_readyAuth(), home: const LoginScreen()));
    await tester.pump();

    expect(find.text('Continue as guest'), findsNothing);
    expect(find.text('Sign in to subscribe and open Nordin\'s AI.'), findsOneWidget);
  });
}
