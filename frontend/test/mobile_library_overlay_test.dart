import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/l10n/app_locale.dart';
import 'package:flutter_application_1/main.dart';
import 'package:flutter_application_1/services/auth_service.dart';
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

  testWidgets('mobile library overlay covers tabs below the drawer nav links', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final auth = AuthController(restoreSession: false);
    auth.user = const AuthUser(
      id: '1',
      email: 'paid@test.com',
      name: 'Paid User',
      isPremium: true,
      subscriptionStatus: 'active',
    );
    auth.token = 'tok';
    auth.sessionReady = true;

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

    expect(find.byKey(SermonLibrarySlidePanel.handleKey), findsOneWidget);
    expect(find.byIcon(Icons.arrow_forward_rounded), findsOneWidget);
    expect(find.byIcon(Icons.menu), findsNothing);

    await tester.tap(find.byKey(SermonLibrarySlidePanel.handleKey));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    expect(find.byKey(SermonLibrarySlidePanel.handleKey), findsOneWidget);
    expect(find.byIcon(Icons.arrow_back_rounded), findsOneWidget);

    expect(find.text('Sermons').hitTestable(), findsOneWidget);
    expect(find.text('Sermon Library').hitTestable(), findsOneWidget);
    expect(find.text('HOME').hitTestable(), findsOneWidget);
    expect(find.text('CHAT').hitTestable(), findsOneWidget);
    expect(find.text('EVENTS').hitTestable(), findsOneWidget);
    expect(find.text('MEDIA').hitTestable(), findsOneWidget);

    final home = tester.getCenter(find.text('HOME'));
    final chat = tester.getCenter(find.text('CHAT'));
    final events = tester.getCenter(find.text('EVENTS'));
    final media = tester.getCenter(find.text('MEDIA'));
    expect((home.dy - chat.dy).abs(), lessThan(2));
    expect((home.dy - events.dy).abs(), lessThan(2));
    expect((home.dy - media.dy).abs(), lessThan(2));
    expect(home.dx, lessThan(chat.dx));
    expect(chat.dx, lessThan(events.dx));
    expect(events.dx, lessThan(media.dx));

    await tester.tap(find.byTooltip('Browse all documents'));
    await tester.pump();

    expect(find.text('All documents').hitTestable(), findsOneWidget);
    expect(find.text('Sermons').hitTestable(), findsNothing);
    expect(find.text('Sermon Library').hitTestable(), findsNothing);
    expect(find.text('New Chat').hitTestable(), findsNothing);
    expect(find.text('HOME').hitTestable(), findsOneWidget);
    expect(find.text('CHAT').hitTestable(), findsOneWidget);
    expect(find.text('MEDIA').hitTestable(), findsOneWidget);

    await tester.tap(find.byTooltip('Close documents catalog'));
    await tester.pump();
    expect(find.text('Sermons').hitTestable(), findsOneWidget);
    expect(find.text('Sermon Library').hitTestable(), findsOneWidget);
    expect(find.text('All documents').hitTestable(), findsNothing);
  });

  testWidgets('library handle drag opens and closes the attached panel', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final animation = AnimationController(
      vsync: const TestVSync(),
      duration: const Duration(milliseconds: 280),
    );
    addTearDown(animation.dispose);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Stack(
            children: [
              const ColoredBox(color: Colors.white),
              SermonLibrarySlidePanel(
                animation: animation,
                panelWidth: 310,
                openTooltip: 'Open sermon library',
                closeTooltip: 'Close sermon library',
                panel: const ColoredBox(
                  color: Color(0xFFa1375a),
                  child: Center(child: Text('Sermon Library')),
                ),
              ),
            ],
          ),
        ),
      ),
    );

    expect(find.text('Sermon Library').hitTestable(), findsNothing);
    expect(find.byIcon(Icons.arrow_forward_rounded), findsOneWidget);

    final closedHandle = tester.getRect(find.byKey(SermonLibrarySlidePanel.handleKey));
    expect(closedHandle.left, closeTo(0, 0.5));
    expect(closedHandle.height, closeTo(SermonLibrarySlidePanel.handleHeight, 1));
    expect(closedHandle.width, closeTo(SermonLibrarySlidePanel.handleWidth, 1));

    await tester.drag(
      find.byKey(SermonLibrarySlidePanel.handleKey),
      const Offset(220, 0),
    );
    await tester.pumpAndSettle();

    expect(find.text('Sermon Library').hitTestable(), findsOneWidget);
    expect(find.byKey(SermonLibrarySlidePanel.handleKey), findsOneWidget);
    expect(find.byIcon(Icons.arrow_back_rounded), findsOneWidget);

    final handle = tester.getTopLeft(find.byKey(SermonLibrarySlidePanel.handleKey));
    expect(handle.dx, closeTo(310, 2));

    await tester.drag(
      find.byKey(SermonLibrarySlidePanel.handleKey),
      const Offset(-220, 0),
    );
    await tester.pumpAndSettle();

    expect(find.text('Sermon Library').hitTestable(), findsNothing);
    expect(find.byIcon(Icons.arrow_forward_rounded), findsOneWidget);
    final closedAgain = tester.getRect(find.byKey(SermonLibrarySlidePanel.handleKey));
    expect(closedAgain.left, closeTo(0, 0.5));
    expect(closedAgain.height, closeTo(SermonLibrarySlidePanel.handleHeight, 1));
  });
}
