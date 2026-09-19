import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/l10n/app_locale.dart';
import 'package:flutter_application_1/screens/paywall_screen.dart';
import 'package:flutter_application_1/screens/checkout_screen.dart';
import 'package:flutter_application_1/screens/subscriptions_screen.dart';
import 'package:flutter_application_1/screens/update_payment_method_screen.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:flutter_application_1/widgets/account_profile_chip.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

Widget _wrap(AuthController auth, {required Widget home}) {
  return MultiProvider(
    providers: [
      ChangeNotifierProvider<AuthController>.value(value: auth),
      ChangeNotifierProvider(create: (_) => LocaleController()),
    ],
    child: MaterialApp(home: home),
  );
}

AuthController _readyAuth(AuthUser user) {
  final auth = AuthController(restoreSession: false);
  auth.user = user;
  auth.token = 'tok';
  auth.sessionReady = true;
  return auth;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUpAll(() {
    GoogleFonts.config.allowRuntimeFetching = false;
  });

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  test('active and past-due members can manage a payment method', () {
    expect(
      const AuthUser(
        id: '1',
        email: 'a@test.com',
        name: 'Active',
        subscriptionStatus: 'active',
      ).canManagePaymentMethod,
      isTrue,
    );
    expect(
      const AuthUser(
        id: '2',
        email: 'p@test.com',
        name: 'Past Due',
        subscriptionStatus: 'past_due',
      ).canManagePaymentMethod,
      isTrue,
    );
    expect(
      const AuthUser(
        id: '3',
        email: 'f@test.com',
        name: 'Free',
      ).canManagePaymentMethod,
      isFalse,
    );
  });

  testWidgets('premium subscriptions page offers a payment method update', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 1600);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      _wrap(
        _readyAuth(
          const AuthUser(
            id: '2',
            email: 'member@test.com',
            name: 'Member',
            isPremium: true,
            subscriptionStatus: 'active',
            billingPeriod: 'monthly',
          ),
        ),
        home: const SubscriptionsScreen(),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.text('Update payment method'), findsOneWidget);
    expect(find.text('Unsubscribe from Premium'), findsOneWidget);
  });

  testWidgets('profile sheet includes update payment method for premium', (
    tester,
  ) async {
    final auth = _readyAuth(
      const AuthUser(
        id: '1',
        email: 'member@test.com',
        name: 'Jane Member',
        isPremium: true,
        subscriptionStatus: 'active',
      ),
    );

    await tester.pumpWidget(
      ChangeNotifierProvider<AuthController>.value(
        value: auth,
        child: MaterialApp(
          home: Scaffold(
            body: Builder(
              builder: (context) => TextButton(
                onPressed: () => showAccountProfileSheet(
                  context,
                  apiService: ApiService(),
                ),
                child: const Text('Open profile'),
              ),
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.text('Open profile'));
    await tester.pumpAndSettle();

    expect(find.text('Update payment method'), findsOneWidget);
    expect(find.text('Unsubscribe'), findsOneWidget);
  });

  testWidgets('free members do not see update payment method in the profile sheet', (
    tester,
  ) async {
    final auth = _readyAuth(
      const AuthUser(
        id: '4',
        email: 'free@test.com',
        name: 'Free Member',
      ),
    );

    await tester.pumpWidget(
      ChangeNotifierProvider<AuthController>.value(
        value: auth,
        child: MaterialApp(
          home: Scaffold(
            body: Builder(
              builder: (context) => TextButton(
                onPressed: () => showAccountProfileSheet(
                  context,
                  apiService: ApiService(),
                ),
                child: const Text('Open profile'),
              ),
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.text('Open profile'));
    await tester.pumpAndSettle();

    expect(find.text('Update payment method'), findsNothing);
  });

  testWidgets('update payment method screen centers the heading', (tester) async {
    await tester.pumpWidget(
      _wrap(
        _readyAuth(
          const AuthUser(
            id: '2',
            email: 'member@test.com',
            name: 'Member',
            isPremium: true,
            subscriptionStatus: 'active',
          ),
        ),
        home: const UpdatePaymentMethodScreen(forceMockCheckout: true),
      ),
    );
    await tester.pump();

    final appBar = tester.widget<AppBar>(find.byType(AppBar));
    expect(appBar.centerTitle, isTrue);
    expect(find.text('Update payment method'), findsWidgets);
    expect(
      find.textContaining('does not have a Stripe card on file'),
      findsOneWidget,
    );
  });

  testWidgets('past-due paywall offers a card update instead of new checkout', (
    tester,
  ) async {
    await tester.pumpWidget(
      _wrap(
        _readyAuth(
          const AuthUser(
            id: '5',
            email: 'pastdue@test.com',
            name: 'Past Due',
            subscriptionStatus: 'past_due',
            billingPeriod: 'monthly',
          ),
        ),
        home: const PaywallScreen(billingPeriod: BillingPeriod.monthly),
      ),
    );
    await tester.pump();

    expect(find.text('Update your payment method'), findsOneWidget);
    expect(find.text('Update payment method'), findsOneWidget);
    expect(find.text('Continue to checkout'), findsNothing);
  });
}
