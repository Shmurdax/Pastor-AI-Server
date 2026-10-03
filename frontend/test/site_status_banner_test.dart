import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/l10n/app_locale.dart';
import 'package:flutter_application_1/main.dart';
import 'package:flutter_application_1/site_banner.dart';
import 'package:flutter_application_1/widgets/site_status_banner.dart';
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

  Future<void> pumpBanner(
    WidgetTester tester, {
    required Future<SiteBannerNotice> Function() load,
    Widget home = const Text('Home page'),
  }) async {
    await tester.pumpWidget(
      MaterialApp(
        builder: (context, child) {
          return SiteBannerFrame(
            load: load,
            child: child ?? const SizedBox.shrink(),
          );
        },
        home: home,
      ),
    );
    await tester.pump();
  }

  testWidgets('hidden banner takes no space', (tester) async {
    await pumpBanner(
      tester,
      load: () async => SiteBannerNotice.hidden,
    );
    expect(find.byKey(const Key('site-status-banner')), findsNothing);
    expect(find.text('Home page'), findsOneWidget);
  });

  testWidgets('shows hazard yellow bar with slate grey text', (tester) async {
    const message =
        'Due to scheduled maintenance the service will be down from Oct 3, 2026, 2:00 PM to Oct 3, 2026, 6:00 PM.';
    await pumpBanner(
      tester,
      load: () async => const SiteBannerNotice(enabled: true, message: message),
    );

    expect(find.text(message), findsOneWidget);
    final box = tester.widget<ColoredBox>(find.byKey(const Key('site-status-banner')));
    expect(box.color, siteBannerHazardYellow);
    final text = tester.widget<Text>(find.text(message));
    expect(text.style?.color, siteBannerSlateGrey);
    expect(tester.getTopLeft(find.byKey(const Key('site-status-banner'))).dy, 0);
    expect(
      tester.getTopLeft(find.text('Home page')).dy,
      greaterThan(tester.getBottomLeft(find.byKey(const Key('site-status-banner'))).dy - 1),
    );
  });

  testWidgets('custom message stays above every route', (tester) async {
    const message = 'The chapel livestream is offline tonight.';
    await pumpBanner(
      tester,
      load: () async => const SiteBannerNotice(enabled: true, message: message),
      home: Builder(
        builder: (context) => TextButton(
          onPressed: () {
            Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) => const Scaffold(body: Text('Second page')),
              ),
            );
          },
          child: const Text('Open second'),
        ),
      ),
    );

    expect(find.text(message), findsOneWidget);
    await tester.tap(find.text('Open second'));
    await tester.pumpAndSettle();
    expect(find.text('Second page'), findsOneWidget);
    expect(find.text(message), findsOneWidget);
    expect(tester.getTopLeft(find.byKey(const Key('site-status-banner'))).dy, 0);
  });

  testWidgets('a failed load leaves the site without a banner', (tester) async {
    await pumpBanner(
      tester,
      load: () async => throw Exception('offline'),
    );
    expect(find.byKey(const Key('site-status-banner')), findsNothing);
    expect(find.text('Home page'), findsOneWidget);
  });

  testWidgets('landing page shows the banner from the app shell', (tester) async {
    const message = 'Due to maintenance the service will be down from 2:00 PM to 4:00 PM.';
    final auth = AuthController(restoreSession: false);
    auth.sessionReady = true;

    await tester.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider<AuthController>.value(value: auth),
          ChangeNotifierProvider(create: (_) => LocaleController()),
        ],
        child: SermonBrainApp(
          loadSiteBanner: () async => const SiteBannerNotice(
            enabled: true,
            message: message,
          ),
        ),
      ),
    );
    await tester.pump();

    expect(find.text(message), findsOneWidget);
    expect(find.text('Get started'), findsOneWidget);
    final box = tester.widget<ColoredBox>(find.byKey(const Key('site-status-banner')));
    expect(box.color, siteBannerHazardYellow);
  });
}
