import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/l10n/app_locale.dart';
import 'package:flutter_application_1/screens/checkout_screen.dart';
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

  testWidgets('checkout keeps back on the left and centers the plan heading', (
    tester,
  ) async {
    final auth = AuthController(restoreSession: false);
    auth.sessionReady = true;
    auth.token = 'tok';
    auth.user = const AuthUser(
      id: '2',
      email: 'member@test.com',
      name: 'Member',
    );

    await tester.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider<AuthController>.value(value: auth),
          ChangeNotifierProvider(create: (_) => LocaleController()),
        ],
        child: const MaterialApp(
          home: CheckoutScreen(),
        ),
      ),
    );
    await tester.pump();

    final appBar = tester.widget<AppBar>(find.byType(AppBar));
    expect(appBar.centerTitle, isTrue);
    expect(find.byIcon(Icons.arrow_back), findsOneWidget);
    expect(find.text('Complete your Premium plan'), findsOneWidget);
    expect(find.text('Checkout'), findsNothing);

    final back = tester.getTopLeft(find.byIcon(Icons.arrow_back));
    final title = tester.getCenter(find.text('Complete your Premium plan'));
    expect(back.dx, lessThan(title.dx));
    expect((title.dx - 400).abs(), lessThan(40));
  });
}
