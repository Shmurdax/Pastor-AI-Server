import 'package:flutter/material.dart';
import 'package:flutter_application_1/l10n/app_locale.dart';
import 'package:flutter_application_1/l10n/app_strings.dart';
import 'package:flutter_application_1/models/prayer_request.dart';
import 'package:flutter_application_1/screens/prayer_inbox_screen.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:plugin_platform_interface/plugin_platform_interface.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher_platform_interface/url_launcher_platform_interface.dart';

class _FakeApiService extends ApiService {}

class _MockUrlLauncher extends Fake
    with MockPlatformInterfaceMixin
    implements UrlLauncherPlatform {
  final List<String> launched = <String>[];

  @override
  Future<bool> canLaunch(String url) async => true;

  @override
  Future<bool> launch(
    String url, {
    required bool useSafariVC,
    required bool useWebView,
    required bool enableJavaScript,
    required bool enableDomStorage,
    required bool universalLinksOnly,
    required Map<String, String> headers,
    String? webOnlyWindowName,
  }) async {
    launched.add(url);
    return true;
  }

  @override
  Future<bool> launchUrl(String url, LaunchOptions options) async {
    launched.add(url);
    return true;
  }

  @override
  Future<void> closeWebView() async {}

  @override
  Future<bool> supportsMode(PreferredLaunchMode mode) async => true;

  @override
  Future<bool> supportsCloseForMode(PreferredLaunchMode mode) async => false;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late _MockUrlLauncher mockLauncher;

  setUpAll(() {
    GoogleFonts.config.allowRuntimeFetching = false;
  });

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    mockLauncher = _MockUrlLauncher();
    UrlLauncherPlatform.instance = mockLauncher;
  });

  PrayerRequestItem sampleItem() => PrayerRequestItem(
        id: 1,
        name: 'Jane Member',
        email: 'jane@test.com',
        phone: '555-0100',
        prayerText: 'Please pray for peace and healing this week.',
        isAnonymous: false,
        createdAt: DateTime.utc(2026, 9, 1, 12),
        followedUp: false,
        pastorNotes: '',
      );

  Future<void> pumpDetail(WidgetTester tester) async {
    tester.view.physicalSize = const Size(800, 1200);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    await tester.pumpWidget(
      ChangeNotifierProvider(
        create: (_) => LocaleController(),
        child: MaterialApp(
          home: PrayerRequestDetailScreen(
            apiService: _FakeApiService(),
            initial: sampleItem(),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets('email chips select platform without opening compose', (tester) async {
    await pumpDetail(tester);

    expect(find.text('Prayer Response'), findsOneWidget);
    expect(find.text('Jane Member'), findsOneWidget);
    expect(find.text('Call'), findsNothing);
    expect(find.text('Select email platform:'), findsOneWidget);
    expect(find.text('Or open compose in:'), findsNothing);
    expect(find.text('Email with Gmail'), findsOneWidget);

    final nameY = tester.getTopLeft(find.text('Jane Member')).dy;
    final dateY = tester.getTopLeft(find.textContaining('2026')).dy;
    expect(nameY, lessThan(dateY));

    final selectHeading = tester.widget<Text>(find.text('Select email platform:'));
    final prayerHeading = tester.widget<Text>(find.text('Prayer request'));
    expect(selectHeading.style?.fontWeight, prayerHeading.style?.fontWeight);
    expect(selectHeading.style?.color, prayerHeading.style?.color);

    final selectY = tester.getTopLeft(find.text('Select email platform:')).dy;
    final emailButtonY = tester.getTopLeft(find.text('Email with Gmail')).dy;
    final saveButtonY = tester.getTopLeft(find.text('Save follow-up')).dy;
    expect(selectY, lessThan(emailButtonY));
    expect(saveButtonY, lessThan(emailButtonY));

    final saveButton = tester.widget<FilledButton>(
      find.widgetWithText(FilledButton, 'Save follow-up'),
    );
    expect(saveButton.style?.backgroundColor?.resolve({}), const Color(0xFFa1375a));

    await tester.tap(find.widgetWithText(FilterChip, 'Outlook'));
    await tester.pumpAndSettle();

    expect(find.text('Email with Outlook'), findsOneWidget);
    expect(find.text('Email with Gmail'), findsNothing);
    expect(mockLauncher.launched, isEmpty);

    await tester.tap(find.widgetWithText(FilterChip, 'Default app'));
    await tester.pumpAndSettle();

    expect(find.text('Email with Default app'), findsOneWidget);
    expect(mockLauncher.launched, isEmpty);

    await tester.ensureVisible(find.text('Email with Default app'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Email with Default app'));
    await tester.pumpAndSettle();

    expect(mockLauncher.launched, hasLength(1));
    expect(mockLauncher.launched.single, 'mailto:jane@test.com');
  });

  testWidgets('Email with button opens selected platform compose URL', (tester) async {
    await pumpDetail(tester);

    await tester.tap(find.widgetWithText(FilterChip, 'Outlook'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('Email with Outlook'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Email with Outlook'));
    await tester.pumpAndSettle();

    expect(mockLauncher.launched, hasLength(1));
    expect(
      mockLauncher.launched.single,
      'https://outlook.office.com/mail/deeplink/compose?to=jane%40test.com',
    );
  });

  test('compose URI helpers match expected clients', () {
    final s = AppStrings('en');
    expect(
      prayerEmailComposeUri('a@b.com', PrayerEmailClient.gmail).toString(),
      'https://mail.google.com/mail/?view=cm&fs=1&to=a%40b.com',
    );
    expect(
      prayerEmailComposeUri('a@b.com', PrayerEmailClient.outlook).toString(),
      'https://outlook.office.com/mail/deeplink/compose?to=a%40b.com',
    );
    expect(
      prayerEmailComposeUri('a@b.com', PrayerEmailClient.systemMailto).toString(),
      'mailto:a@b.com',
    );
    expect(prayerEmailClientLabel(PrayerEmailClient.gmail, s), 'Gmail');
    expect(prayerEmailClientLabel(PrayerEmailClient.outlook, s), 'Outlook');
    expect(prayerEmailClientLabel(PrayerEmailClient.systemMailto, s), 'Default app');
  });
}
