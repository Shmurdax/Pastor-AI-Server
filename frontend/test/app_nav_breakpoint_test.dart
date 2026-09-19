import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/l10n/app_locale.dart';
import 'package:flutter_application_1/main.dart';
import 'package:flutter_application_1/screens/media_library_screen.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:flutter_application_1/widgets/app_hamburger_nav.dart';
import 'package:flutter_application_1/widgets/sermon_library_slide_panel.dart';
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

  Future<void> pumpMedia(WidgetTester tester, Size size) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    final auth = AuthController(restoreSession: false);
    auth.token = 'test-token';
    auth.sessionReady = true;
    auth.user = const AuthUser(
      id: '1',
      email: 'premium@test.com',
      name: 'Premium',
      isPremium: true,
    );

    await tester.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider<AuthController>.value(value: auth),
          ChangeNotifierProvider(create: (_) => LocaleController()),
        ],
        child: const MaterialApp(home: MediaLibraryScreen()),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
  }

  testWidgets('desktop media header keeps the top-right nav at 1024px', (tester) async {
    await pumpMedia(tester, const Size(1100, 900));

    expect(
      find.descendant(of: find.byType(AppBar), matching: find.text('HOME')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: find.byType(AppBar), matching: find.text('CHAT')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: find.byType(AppBar), matching: find.text('EVENTS')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: find.byType(AppBar), matching: find.text('MEDIA')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: find.byType(AppBar), matching: find.text('STORE')),
      findsNothing,
    );
    expect(
      find.descendant(of: find.byType(AppBar), matching: find.text("NORDIN'S AI")),
      findsNothing,
    );
    expect(find.byType(AppHamburgerNav), findsNothing);
  });

  testWidgets('media header hides top-right nav at 1023px and shows hamburger', (tester) async {
    await pumpMedia(tester, const Size(1023, 900));

    expect(
      find.descendant(of: find.byType(AppBar), matching: find.text('HOME')),
      findsNothing,
    );
    expect(
      find.descendant(of: find.byType(AppBar), matching: find.text('STORE')),
      findsNothing,
    );
    expect(find.byType(AppHamburgerNav), findsOneWidget);
    expect(
      find.descendant(of: find.byType(AppBar), matching: find.byIcon(Icons.menu)),
      findsOneWidget,
    );

    await tester.tap(find.byIcon(Icons.menu));
    await tester.pumpAndSettle();
    expect(find.text('Home'), findsOneWidget);
    expect(find.text('Chat'), findsOneWidget);
    expect(find.text('Events'), findsOneWidget);
    expect(find.text('Media'), findsOneWidget);
    expect(find.text('Store'), findsNothing);
    expect(find.text('Subscribe'), findsNothing);
    expect(find.text("NORDIN'S AI"), findsNothing);
  });

  testWidgets('chat header hides top-right nav at tablet width', (tester) async {
    tester.view.physicalSize = const Size(800, 900);
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

    expect(
      find.descendant(of: find.byType(AppBar), matching: find.text('HOME')),
      findsNothing,
    );
    expect(find.byKey(SermonLibrarySlidePanel.handleKey), findsOneWidget);
    expect(find.byIcon(Icons.arrow_forward_rounded), findsOneWidget);
    expect(find.byTooltip('Open navigation menu'), findsNothing);
  });
}
