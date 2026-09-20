import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/l10n/app_locale.dart';
import 'package:flutter_application_1/screens/checkout_screen.dart';
import 'package:flutter_application_1/services/auth_service.dart';
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

AuthController _memberAuth() {
  final auth = AuthController(restoreSession: false);
  auth.sessionReady = true;
  auth.token = 'tok';
  auth.user = const AuthUser(
    id: '2',
    email: 'member@test.com',
    name: 'Member',
  );
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

  test('yearly plan is 17 percent off twelve monthly payments', () {
    expect(yearlyBillingDiscountPercent(), 17);
    expect(yearlyBillingDiscountLabel(), 'Save 17%');
    expect(yearlyBillingDiscountVsMonthlyLabel(), 'Save 17% vs monthly');
  });

  test('consent copy names the selected billing period', () {
    expect(
      subscriptionConsentLabel(BillingPeriod.monthly),
      'I acknowledge I am subscribing to a monthly Premium plan (\$15/month) that renews until I cancel.',
    );
    expect(
      subscriptionConsentLabel(BillingPeriod.yearly),
      'I acknowledge I am subscribing to a yearly Premium plan (\$150/year) that renews until I cancel.',
    );
  });

  testWidgets('monthly checkout keeps subscribe disabled until consent is checked', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(800, 1400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      _wrap(
        _memberAuth(),
        home: const CheckoutScreen(forceMockCheckout: true),
      ),
    );
    await tester.pump();

    expect(
      find.text(subscriptionConsentLabel(BillingPeriod.monthly)),
      findsOneWidget,
    );
    expect(
      find.text(subscriptionConsentLabel(BillingPeriod.yearly)),
      findsNothing,
    );

    final subscribeFinder = find.widgetWithText(
      FilledButton,
      r'Subscribe · $15.00 / month',
    );
    expect(subscribeFinder, findsOneWidget);
    expect(tester.widget<FilledButton>(subscribeFinder).onPressed, isNull);

    await tester.tap(find.byType(Checkbox));
    await tester.pump();

    expect(tester.widget<FilledButton>(subscribeFinder).onPressed, isNotNull);

    await tester.tap(find.byType(Checkbox));
    await tester.pump();
    expect(tester.widget<FilledButton>(subscribeFinder).onPressed, isNull);
  });

  testWidgets('yearly checkout shows the yearly acknowledgment', (tester) async {
    tester.view.physicalSize = const Size(800, 1400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      _wrap(
        _memberAuth(),
        home: const CheckoutScreen(
          billingPeriod: BillingPeriod.yearly,
          forceMockCheckout: true,
        ),
      ),
    );
    await tester.pump();

    expect(
      find.text(subscriptionConsentLabel(BillingPeriod.yearly)),
      findsOneWidget,
    );
    expect(
      find.text(subscriptionConsentLabel(BillingPeriod.monthly)),
      findsNothing,
    );

    final subscribeFinder = find.widgetWithText(
      FilledButton,
      r'Subscribe · $150.00 / year',
    );
    expect(subscribeFinder, findsOneWidget);
    expect(tester.widget<FilledButton>(subscribeFinder).onPressed, isNull);
    expect(find.textContaining('Save ${yearlyBillingDiscountPercent()}%'), findsWidgets);
    expect(find.text(yearlyBillingDiscountVsMonthlyLabel()), findsOneWidget);
  });
}
