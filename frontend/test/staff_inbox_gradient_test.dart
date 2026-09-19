import 'package:flutter/material.dart';
import 'package:flutter_application_1/models/prayer_request.dart';
import 'package:flutter_application_1/models/response_report.dart';
import 'package:flutter_application_1/screens/prayer_inbox_screen.dart';
import 'package:flutter_application_1/screens/response_reports_inbox_screen.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_application_1/widgets/brand_gradient.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';

class _FakeApiService extends ApiService {
  @override
  Future<List<PrayerRequestItem>> listPrayerRequests({bool? followedUp}) async {
    return const [];
  }

  @override
  Future<List<ResponseReportItem>> listResponseReports({String? status}) async {
    return const [];
  }
}

bool _usesBrandGradient(Widget widget) {
  if (widget is DecoratedBox) {
    final decoration = widget.decoration;
    return decoration is BoxDecoration && decoration.gradient == brandGradient;
  }
  if (widget is SizedBox && widget.child != null) {
    return _usesBrandGradient(widget.child!);
  }
  return false;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUpAll(() {
    GoogleFonts.config.allowRuntimeFetching = false;
  });

  testWidgets('prayer inbox app bar uses the red/purple brand gradient', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: PrayerInboxScreen(apiService: _FakeApiService()),
      ),
    );
    await tester.pump();

    expect(find.text('Prayer inbox'), findsOneWidget);
    final appBar = tester.widget<AppBar>(find.byType(AppBar));
    expect(_usesBrandGradient(appBar.flexibleSpace!), isTrue);
  });

  testWidgets('response reports app bar uses the red/purple brand gradient', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: ResponseReportsInboxScreen(apiService: _FakeApiService()),
      ),
    );
    await tester.pump();

    expect(find.text('Response reports'), findsOneWidget);
    final appBar = tester.widget<AppBar>(find.byType(AppBar));
    expect(_usesBrandGradient(appBar.flexibleSpace!), isTrue);
  });

  testWidgets('prayer request detail app bar uses the red/purple brand gradient', (tester) async {
    final item = PrayerRequestItem(
      id: 1,
      name: 'Jane Member',
      email: 'jane@test.com',
      phone: '',
      prayerText: 'Please pray for peace and healing this week.',
      isAnonymous: false,
      createdAt: DateTime.utc(2026, 9, 1, 12),
      followedUp: false,
      pastorNotes: '',
    );

    await tester.pumpWidget(
      MaterialApp(
        home: PrayerRequestDetailScreen(
          apiService: _FakeApiService(),
          initial: item,
        ),
      ),
    );
    await tester.pump();

    final appBar = tester.widget<AppBar>(find.byType(AppBar));
    expect(_usesBrandGradient(appBar.flexibleSpace!), isTrue);
  });

  testWidgets('response report detail app bar uses the red/purple brand gradient', (tester) async {
    final item = ResponseReportItem(
      id: 4,
      reason: 'inaccurate',
      reasonLabel: 'Inaccurate information',
      status: 'new',
      statusLabel: 'New',
      userQuerySnapshot: 'What does Pastor Don teach about prayer?',
      aiResponseSnapshot: 'He teaches that unbelief can hinder prayer.',
      details: '',
      staffNotes: '',
      createdAt: DateTime.utc(2026, 9, 1, 12),
    );

    await tester.pumpWidget(
      MaterialApp(
        home: ResponseReportDetailScreen(
          apiService: _FakeApiService(),
          initial: item,
        ),
      ),
    );
    await tester.pump();

    final appBar = tester.widget<AppBar>(find.byType(AppBar));
    expect(_usesBrandGradient(appBar.flexibleSpace!), isTrue);
  });
}
