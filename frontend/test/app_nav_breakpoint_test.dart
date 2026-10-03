import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/l10n/app_locale.dart';
import 'package:flutter_application_1/main.dart';
import 'package:flutter_application_1/screens/media_library_screen.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:flutter_application_1/widgets/app_hamburger_nav.dart';
import 'package:flutter_application_1/widgets/language_selector.dart';
import 'package:flutter_application_1/widgets/sermon_library_slide_panel.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

Future<void> _openEventsPanel(WidgetTester tester) async {
  await tester.tap(find.text('EVENTS'));
  await tester.pump();
  expect(find.text('Church Events'), findsOneWidget);
}

double _eventsPanelCenter(WidgetTester tester) {
  final left = tester.getTopLeft(find.text('Church Events')).dx;
  final right = tester.getTopRight(find.byTooltip('Close events')).dx;
  return (left + right) / 2;
}

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
      find.descendant(of: find.byType(AppBar), matching: find.text('NORDINS WEBSITE')),
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
    expect(find.byType(LanguageSelector), findsNothing);
  });

  testWidgets('media header keeps Home Chat Media Events below 1024px', (tester) async {
    await pumpMedia(tester, const Size(1023, 900));

    expect(
      find.descendant(of: find.byType(AppBar), matching: find.text('NORDINS WEBSITE')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: find.byType(AppBar), matching: find.text('CHAT')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: find.byType(AppBar), matching: find.text('MEDIA')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: find.byType(AppBar), matching: find.text('EVENTS')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: find.byType(AppBar), matching: find.text('STORE')),
      findsNothing,
    );
    expect(find.byType(AppHamburgerNav), findsNothing);
    expect(
      find.descendant(of: find.byType(AppBar), matching: find.byIcon(Icons.menu)),
      findsNothing,
    );
    expect(find.byType(LanguageSelector), findsNothing);
    expect(find.byIcon(Icons.language), findsNothing);

    final logo = tester.getCenter(
      find.descendant(of: find.byType(AppBar), matching: find.byType(Image)),
    );
    final events = tester.getCenter(find.text('EVENTS'));
    expect((events.dy - logo.dy).abs(), lessThan(30));

    await _openEventsPanel(tester);
    expect(_eventsPanelCenter(tester), greaterThan(1023 * 0.6));
    expect(
      tester.getTopRight(find.byTooltip('Close events')).dx,
      greaterThan(1023 * 0.85),
    );
  });

  testWidgets('media header keeps nav links on a phone', (tester) async {
    await pumpMedia(tester, const Size(390, 844));

    for (final label in ['NORDINS WEBSITE', 'CHAT', 'MEDIA', 'EVENTS']) {
      expect(
        find.descendant(of: find.byType(AppBar), matching: find.text(label)),
        findsOneWidget,
      );
    }

    final home = tester.getCenter(find.text('NORDINS WEBSITE'));
    final chat = tester.getCenter(find.text('CHAT'));
    final media = tester.getCenter(find.text('MEDIA'));
    final events = tester.getCenter(find.text('EVENTS'));
    expect(home.dx, lessThan(chat.dx));
    expect(chat.dx, lessThan(media.dx));
    expect(media.dx, lessThan(events.dx));
    expect((home.dy - events.dy).abs(), lessThan(2));

    const screenCenter = 390 / 2;
    final links = tester.getRect(
      find.descendant(of: find.byType(AppBar), matching: find.byType(FittedBox)),
    );
    expect((links.center.dx - screenCenter).abs(), lessThan(16));
    expect(links.right, lessThan(390));
    expect(links.left, greaterThan(0));

    final logo = tester.getCenter(
      find.descendant(of: find.byType(AppBar), matching: find.byType(Image)),
    );
    expect((logo.dx - screenCenter).abs(), lessThan(16));

    await _openEventsPanel(tester);
    expect(_eventsPanelCenter(tester), closeTo(screenCenter, 24));
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
      find.descendant(of: find.byType(AppBar), matching: find.text('NORDINS WEBSITE')),
      findsNothing,
    );
    expect(find.byKey(SermonLibrarySlidePanel.handleKey), findsOneWidget);
    expect(find.byIcon(Icons.arrow_forward_rounded), findsOneWidget);
    expect(find.byTooltip('Open navigation menu'), findsNothing);
  });
}
