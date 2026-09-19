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

  testWidgets('landing premium card uses the site pink-to-navy gradient', (tester) async {
    await tester.pumpWidget(_wrap(_readyAuth()));
    await tester.pump();

    const pink = Color(0xFFa1375a);
    const navy = Color(0xFF1B264F);
    final gradients = tester
        .widgetList<Container>(find.byType(Container))
        .map((widget) => widget.decoration)
        .whereType<BoxDecoration>()
        .map((decoration) => decoration.gradient)
        .whereType<LinearGradient>()
        .toList();

    expect(gradients, isNotEmpty);
    expect(
      gradients.any(
        (gradient) =>
            gradient.colors.length == 2 &&
            gradient.colors[0] == pink &&
            gradient.colors[1] == navy,
      ),
      isTrue,
    );
  });

  testWidgets('Get started opens the create-account screen', (tester) async {
    await tester.pumpWidget(_wrap(_readyAuth()));
    await tester.pump();

    await tester.tap(find.text('Get started'));
    await tester.pump();
    await tester.pump();

    expect(find.text('Create your account'), findsOneWidget);
    expect(
      find.text('Create an account, verify your email, then complete your subscription to get access.'),
      findsOneWidget,
    );
    expect(find.text('Continue to payment'), findsOneWidget);
  });

  Future<void> _goBackFromRegister(WidgetTester tester) async {
    await tester.tap(find.byIcon(Icons.arrow_back));
    await tester.pump();
    await tester.pump();
  }

  testWidgets('back from Get started returns to the landing page', (tester) async {
    await tester.pumpWidget(_wrap(_readyAuth()));
    await tester.pump();

    await tester.tap(find.text('Get started'));
    await tester.pump();
    await tester.pump();
    expect(find.text('Create your account'), findsOneWidget);

    await _goBackFromRegister(tester);

    expect(find.text("Nordin's AI"), findsOneWidget);
    expect(find.text('Get started'), findsOneWidget);
    expect(find.text('Please login to continue'), findsNothing);
    expect(find.text('Create your account'), findsNothing);
  });

  testWidgets('back from Subscribe returns to the landing page', (tester) async {
    tester.view.physicalSize = const Size(1200, 1600);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(_wrap(_readyAuth()));
    await tester.pump();

    final subscribe = find.text('Subscribe · \$15/ month');
    await tester.ensureVisible(subscribe);
    await tester.tap(subscribe);
    await tester.pump();
    await tester.pump();
    expect(find.text('Create your account'), findsOneWidget);

    await _goBackFromRegister(tester);

    expect(find.text("Nordin's AI"), findsOneWidget);
    expect(find.text('Please login to continue'), findsNothing);
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

  testWidgets('new email accounts verify before checkout', (tester) async {
    _useWideSurface(tester);
    final auth = _readyAuth(
      token: 'tok',
      user: const AuthUser(
        id: '3',
        email: 'newpaid@test.com',
        name: 'New Paid',
        isPremium: true,
        emailVerified: false,
        subscriptionStatus: 'active',
      ),
    );
    await tester.pumpWidget(_wrap(auth));
    await tester.pump();

    expect(find.text('Verify your email'), findsOneWidget);
    expect(find.text('Verify email'), findsOneWidget);
    expect(find.text('Resend code'), findsOneWidget);
    expect(find.byKey(const Key('email-verification-code')), findsOneWidget);
    expect(find.text("Welcome to the Nordin's AI Assistant"), findsNothing);
    expect(find.text('Complete your subscription'), findsNothing);
  });

  testWidgets('staff skip email verification even if the flag is false', (tester) async {
    _useWideSurface(tester);
    final auth = _readyAuth(
      token: 'tok',
      user: const AuthUser(
        id: '9',
        email: 'staff@test.com',
        name: 'Staff User',
        isStaff: true,
        emailVerified: false,
      ),
    );
    await tester.pumpWidget(_wrap(auth));
    await tester.pump();

    expect(find.text("Welcome to the Nordin's AI Assistant"), findsOneWidget);
    expect(find.text('Verify your email'), findsNothing);
  });

  testWidgets('unpaid unverified members enter a code before the paywall', (tester) async {
    final auth = _readyAuth(
      token: 'tok',
      user: const AuthUser(
        id: '4',
        email: 'free@test.com',
        name: 'Free User',
        emailVerified: false,
      ),
    );
    await tester.pumpWidget(_wrap(auth));
    await tester.pump();

    expect(find.text('Verify your email'), findsOneWidget);
    expect(find.text('Complete your subscription'), findsNothing);
    expect(find.text("Welcome to the Nordin's AI Assistant"), findsNothing);
  });

  testWidgets('login screen no longer offers guest access', (tester) async {
    await tester.pumpWidget(_wrap(_readyAuth(), home: const LoginScreen()));
    await tester.pump();

    expect(find.text('Continue as guest'), findsNothing);
    expect(find.text('Sign in to subscribe and open Nordin\'s AI.'), findsOneWidget);
  });
}
