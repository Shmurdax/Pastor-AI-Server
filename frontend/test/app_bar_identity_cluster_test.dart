import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/l10n/app_locale.dart';
import 'package:flutter_application_1/main.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:flutter_application_1/widgets/account_profile_chip.dart';
import 'package:flutter_application_1/widgets/language_selector.dart';
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

  Future<void> pumpChat(WidgetTester tester, Size size) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    final auth = AuthController(restoreSession: false);
    auth.token = 'tok';
    auth.sessionReady = true;
    auth.user = const AuthUser(
      id: '1',
      email: 'paid@test.com',
      name: 'Paid User',
      isPremium: true,
      subscriptionStatus: 'active',
    );

    await tester.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider<AuthController>.value(value: auth),
          ChangeNotifierProvider(create: (_) => LocaleController()),
        ],
        child: const MaterialApp(home: ChatScreen()),
      ),
    );
    await tester.pump();
  }

  testWidgets('mobile stacks the globe language picker under the account chip', (tester) async {
    await pumpChat(tester, const Size(390, 844));

    expect(tester.takeException(), isNull);
    expect(find.byType(AccountProfileChip), findsOneWidget);
    expect(find.byType(LanguageSelector), findsOneWidget);
    expect(find.byIcon(Icons.language), findsOneWidget);
    expect(find.text('English'), findsNothing);

    final appBar = tester.getRect(find.byType(AppBar));
    final account = tester.getRect(find.byType(AccountProfileChip));
    final language = tester.getRect(find.byType(LanguageSelector));
    expect(language.top, greaterThan(account.bottom - 2));
    expect((language.right - account.right).abs(), lessThan(16));
    final topGap = account.top - appBar.top;
    final bottomGap = appBar.bottom - language.bottom;
    expect(topGap, greaterThan(6));
    expect(bottomGap, greaterThan(6));
    expect((topGap - bottomGap).abs(), lessThan(12));
  });

  testWidgets('desktop keeps language beside the account chip', (tester) async {
    await pumpChat(tester, const Size(1200, 900));

    expect(find.text('English'), findsOneWidget);
    final account = tester.getRect(find.byType(AccountProfileChip));
    final language = tester.getRect(find.byType(LanguageSelector));
    expect(language.right, lessThan(account.left + 8));
    expect((language.center.dy - account.center.dy).abs(), lessThan(24));
  });

  testWidgets('desktop logo sits with equal space above and below in the header', (tester) async {
    await pumpChat(tester, const Size(1200, 900));

    final appBar = tester.getRect(find.byType(AppBar));
    final logo = tester.getRect(
      find.descendant(of: find.byType(AppBar), matching: find.byType(Image)),
    );
    expect(appBar.height, 120);
    expect(logo.height, 95);
    final topGap = logo.top - appBar.top;
    final bottomGap = appBar.bottom - logo.bottom;
    expect(topGap, greaterThan(8));
    expect(bottomGap, greaterThan(8));
    expect((topGap - bottomGap).abs(), lessThan(4));
  });

  testWidgets('compact logo sits with equal space above and below in the header', (tester) async {
    await pumpChat(tester, const Size(390, 844));

    final appBar = tester.getRect(find.byType(AppBar));
    final logo = tester.getRect(
      find.descendant(of: find.byType(AppBar), matching: find.byType(Image)),
    );
    expect(appBar.height, 100);
    expect(logo.height, 80);
    final topGap = logo.top - appBar.top;
    final bottomGap = appBar.bottom - logo.bottom;
    expect(topGap, greaterThan(6));
    expect(bottomGap, greaterThan(6));
    expect((topGap - bottomGap).abs(), lessThan(4));
  });
}
