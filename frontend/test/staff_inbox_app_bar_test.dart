import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/l10n/app_locale.dart';
import 'package:flutter_application_1/main.dart';
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

  Future<void> pumpChat(WidgetTester tester, Size size) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    final auth = AuthController(restoreSession: false);
    auth.token = 'tok';
    auth.sessionReady = true;
    auth.user = const AuthUser(
      id: '9',
      email: 'staff@test.com',
      name: 'Staff User',
      isStaff: true,
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

  Finder appBarInboxIcons() {
    return find.descendant(
      of: find.byType(AppBar),
      matching: find.byWidgetPredicate((widget) {
        if (widget is! Icon) return false;
        return widget.icon == Icons.volunteer_activism_outlined ||
            widget.icon == Icons.flag_outlined;
      }),
    );
  }

  testWidgets('staff inbox app bar buttons hide at 600px', (tester) async {
    await pumpChat(tester, const Size(600, 900));

    expect(appBarInboxIcons(), findsNothing);
    expect(find.byTooltip('Prayer inbox'), findsNothing);
    expect(find.byTooltip('Response reports'), findsNothing);
  });

  testWidgets('staff inbox app bar buttons hide below 600px', (tester) async {
    await pumpChat(tester, const Size(390, 844));

    expect(appBarInboxIcons(), findsNothing);
    expect(find.byTooltip('Prayer inbox'), findsNothing);
    expect(find.byTooltip('Response reports'), findsNothing);
  });

  testWidgets('staff inbox app bar buttons show above 600px', (tester) async {
    await pumpChat(tester, const Size(601, 900));

    expect(
      find.descendant(
        of: find.byType(AppBar),
        matching: find.byIcon(Icons.volunteer_activism_outlined),
      ),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: find.byType(AppBar),
        matching: find.byIcon(Icons.flag_outlined),
      ),
      findsOneWidget,
    );
    expect(find.byTooltip('Prayer inbox'), findsOneWidget);
    expect(find.byTooltip('Response reports'), findsOneWidget);
  });
}
