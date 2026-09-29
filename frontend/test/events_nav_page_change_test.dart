import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/l10n/app_locale.dart';
import 'package:flutter_application_1/main.dart';
import 'package:flutter_application_1/screens/media_library_screen.dart';
import 'package:flutter_application_1/services/api_client.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:flutter_application_1/widgets/chat_nav_actions.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
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

  testWidgets(
      'events panel closes across chat and media, including the return trip', (
    tester,
  ) async {
    final httpOverride = _JsonHttpOverrides();
    final previousOverride = HttpOverrides.current;
    HttpOverrides.global = httpOverride;
    addTearDown(() => HttpOverrides.global = previousOverride);

    await _pumpChat(tester, const Size(1280, 900));
    await _flushAsync(tester);

    await _openEvents(tester);
    await _pumpUntil(tester, find.text('Add event'));
    expect(find.text('Church Events'), findsOneWidget);
    expect(find.text('Add event'), findsOneWidget);

    await _tapNav(tester, 'EVENTS');
    expect(find.text('Church Events'), findsNothing);
    expect(find.text('Add event'), findsNothing);

    await _openEvents(tester);
    await _pumpUntil(tester, find.text('Add event'));
    expect(find.text('Church Events'), findsOneWidget);

    await _tapNav(tester, 'MEDIA');
    expect(find.text('Church Events'), findsNothing);
    expect(find.text('Add event'), findsNothing);

    await _openEvents(tester);
    await _pumpUntil(tester, find.text('Add event'));
    expect(find.text('Church Events'), findsOneWidget);
    expect(find.text('Add event'), findsOneWidget);

    await _tapNav(tester, 'CHAT');
    expect(find.text('Church Events'), findsNothing);
    expect(find.text('Add event'), findsNothing);

    await _tapNav(tester, 'MEDIA');
    expect(find.text('Church Events'), findsNothing);
    expect(find.text('Add event'), findsNothing);

    await tester.tap(find.byIcon(Icons.arrow_back).hitTestable());
    await _pumpRoute(tester);
    expect(find.text('Church Events'), findsNothing);
    expect(find.text('Add event'), findsNothing);
  });

  testWidgets(
      'events panel on the same media page stays closed after leaving and coming back',
      (
    tester,
  ) async {
    await _pumpMedia(tester, staff: true);

    await _openEvents(tester);
    await _pumpUntil(tester, find.text('Add event'));
    expect(find.text('Add event'), findsOneWidget);

    final navigator = tester.state<NavigatorState>(find.byType(Navigator));
    navigator.push(
      MaterialPageRoute<void>(
        builder: (_) => const Scaffold(body: Text('Other page')),
      ),
    );
    await _pumpRoute(tester);

    expect(find.text('Other page'), findsOneWidget);
    expect(find.text('Church Events'), findsNothing);
    expect(find.text('Add event'), findsNothing);

    expect(await navigator.maybePop(), isTrue);
    await _pumpRoute(tester);

    expect(find.text('Other page'), findsNothing);
    expect(find.text('MEDIA'), findsWidgets);
    expect(find.text('Church Events'), findsNothing);
    expect(find.text('Add event'), findsNothing);
  });

  testWidgets('tapping Events again closes the panel on the media page', (tester) async {
    await _pumpMedia(tester, staff: true);
    await _openEvents(tester);
    await _pumpUntil(tester, find.text('Add event'));

    await _tapNav(tester, 'EVENTS');

    expect(find.text('Church Events'), findsNothing);
    expect(find.text('Add event'), findsNothing);
  });

  testWidgets('opening the add-event dialog does not close the events panel',
      (tester) async {
    await _pumpMedia(tester, staff: true);
    await _openEvents(tester);
    await _pumpUntil(tester, find.text('Add event'));

    await tester.tap(find.text('Add event'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    expect(find.text('Add church event'), findsOneWidget);
    expect(find.text('Church Events'), findsOneWidget);

    tester.state<NavigatorState>(find.byType(Navigator)).pop();
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    expect(find.text('Add church event'), findsNothing);
    expect(find.text('Church Events'), findsOneWidget);
    expect(find.text('Add event'), findsOneWidget);
  });

  testWidgets('members do not see Add event on the media page', (tester) async {
    await _pumpMedia(tester, staff: false);
    await _openEvents(tester);
    await _pumpUntil(tester, find.textContaining('No events scheduled yet'));

    expect(find.text('Church Events'), findsOneWidget);
    expect(find.text('Add event'), findsNothing);
    expect(find.textContaining('Tap Add event'), findsNothing);
  });
}

Future<void> _pumpChat(WidgetTester tester, Size size) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);

  final auth = _auth(staff: true);
  await tester.pumpWidget(
    MultiProvider(
      providers: [
        ChangeNotifierProvider<AuthController>.value(value: auth),
        ChangeNotifierProvider(create: (_) => LocaleController()),
      ],
      child: MaterialApp(
        navigatorObservers: [_BoundPageObserver()],
        home: const ChatScreen(),
      ),
    ),
  );
  await tester.pump();
}

Future<void> _pumpMedia(WidgetTester tester, {required bool staff}) async {
  tester.view.physicalSize = const Size(1280, 1000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);

  final auth = _auth(staff: staff);
  await tester.pumpWidget(
    MultiProvider(
      providers: [
        ChangeNotifierProvider<AuthController>.value(value: auth),
        ChangeNotifierProvider(create: (_) => LocaleController()),
      ],
      child: MaterialApp(
        navigatorObservers: [_BoundPageObserver()],
        home: MediaLibraryScreen(apiService: _mediaApi()),
      ),
    ),
  );
  await tester.pump();
  await _flushAsync(tester);
}

AuthController _auth({required bool staff}) {
  final auth = AuthController(restoreSession: false);
  auth.token = 'tok';
  auth.sessionReady = true;
  auth.user = AuthUser(
    id: '9',
    email: staff ? 'staff@test.com' : 'member@test.com',
    name: staff ? 'Staff User' : 'Member',
    isStaff: staff,
    isPremium: true,
    subscriptionStatus: 'active',
  );
  return auth;
}

ApiService _mediaApi() {
  return ApiService(
    apiClient: ApiClient(
      client: MockClient((request) async {
        return http.Response(
          jsonEncode({'results': []}),
          200,
          headers: {'content-type': 'application/json'},
        );
      }),
    ),
  );
}

Future<void> _openEvents(WidgetTester tester) async {
  await _tapNav(tester, 'EVENTS');
  await _pumpUntil(tester, find.text('Church Events'));
  expect(find.text('Church Events'), findsOneWidget);
}

Future<void> _tapNav(WidgetTester tester, String label) async {
  await tester.tap(find.text(label).hitTestable());
  await _pumpRoute(tester);
}

Future<void> _pumpRoute(WidgetTester tester) async {
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 600));
  await tester.pump();
}

Future<void> _flushAsync(WidgetTester tester) async {
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 50));
  await tester.pump();
}

Future<void> _pumpUntil(WidgetTester tester, Finder finder) async {
  for (var i = 0; i < 20; i++) {
    if (finder.evaluate().isNotEmpty) return;
    await tester.pump(const Duration(milliseconds: 50));
  }
}

/// Forwards page changes to [AppPageNavigation] without sharing one observer
/// across every test's navigator.
class _BoundPageObserver extends NavigatorObserver {
  _BoundPageObserver();

  @override
  void didPush(Route<dynamic> route, Route<dynamic>? previousRoute) {
    AppPageNavigation.observer.didPush(route, previousRoute);
  }

  @override
  void didPop(Route<dynamic> route, Route<dynamic>? previousRoute) {
    AppPageNavigation.observer.didPop(route, previousRoute);
  }

  @override
  void didReplace({Route<dynamic>? newRoute, Route<dynamic>? oldRoute}) {
    AppPageNavigation.observer
        .didReplace(newRoute: newRoute, oldRoute: oldRoute);
  }
}

class _JsonHttpOverrides extends HttpOverrides {
  @override
  HttpClient createHttpClient(SecurityContext? context) => _JsonHttpClient();
}

class _JsonHttpClient extends Fake implements HttpClient {
  @override
  Future<HttpClientRequest> openUrl(String method, Uri url) async {
    return _JsonRequest(utf8.encode('{"results":[],"entries":[]}'));
  }

  @override
  void close({bool force = false}) {}
}

class _JsonRequest extends Fake implements HttpClientRequest {
  _JsonRequest(this._responseBytes);

  final List<int> _responseBytes;
  final HttpHeaders _headers = _JsonHeaders();

  @override
  HttpHeaders get headers => _headers;

  @override
  set followRedirects(bool value) {}

  @override
  set maxRedirects(int value) {}

  @override
  set contentLength(int value) {}

  @override
  set persistentConnection(bool value) {}

  @override
  Future<void> addStream(Stream<List<int>> stream) async {
    await stream.drain<void>();
  }

  @override
  Future<HttpClientResponse> close() async => _JsonResponse(_responseBytes);
}

class _JsonResponse extends Fake implements HttpClientResponse {
  _JsonResponse(this._bytes);

  final List<int> _bytes;

  @override
  int get statusCode => 200;

  @override
  int get contentLength => _bytes.length;

  @override
  bool get isRedirect => false;

  @override
  bool get persistentConnection => false;

  @override
  String get reasonPhrase => 'OK';

  @override
  List<RedirectInfo> get redirects => const [];

  @override
  HttpHeaders get headers => _JsonHeaders({'content-type': 'application/json'});

  @override
  StreamSubscription<List<int>> listen(
    void Function(List<int> event)? onData, {
    Function? onError,
    void Function()? onDone,
    bool? cancelOnError,
  }) {
    return Stream<List<int>>.value(_bytes).listen(
      onData,
      onError: onError,
      onDone: onDone,
      cancelOnError: cancelOnError,
    );
  }
}

class _JsonHeaders extends Fake implements HttpHeaders {
  _JsonHeaders([Map<String, String>? values]) : _values = {...?values};

  final Map<String, String> _values;

  @override
  void set(String name, Object value, {bool preserveHeaderCase = false}) {
    _values[name.toLowerCase()] = value.toString();
  }

  @override
  void forEach(void Function(String name, List<String> values) action) {
    _values.forEach((name, value) {
      action(name, [value]);
    });
  }
}
