import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/l10n/app_locale.dart';
import 'package:flutter_application_1/screens/media_library_screen.dart';
import 'package:flutter_application_1/services/api_client.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

ApiService _mediaApi({
  required String token,
  required List<Map<String, dynamic>> results,
  List<String>? capturedAuthHeaders,
}) {
  return ApiService(
    apiClient: ApiClient(
      client: MockClient((request) async {
        if (capturedAuthHeaders != null) {
          capturedAuthHeaders.add(request.headers['Authorization'] ?? '');
        }
        if (request.url.path.contains('media')) {
          return http.Response(
            jsonEncode({'results': results}),
            200,
            headers: {'content-type': 'application/json'},
          );
        }
        return http.Response('{"detail":"not mocked"}', 404);
      }),
    ),
  );
}

Map<String, dynamic> _videoJson({
  required int id,
  required String vimeoId,
  required String title,
  String accessTier = 'premium',
}) {
  return {
    'id': id,
    'vimeo_id': vimeoId,
    'privacy_hash': 'abc123',
    'title': title,
    'description': 'Walk through the Word',
    'published_at': '2026-08-12T22:34:00Z',
    'duration_seconds': 600,
    'duration_label': '10:00',
    'thumbnail_url': '',
    'access_tier': accessTier,
    'is_published': true,
  };
}

void main() {
  test('media grid tiles keep most of their height for the 16:9 video', () {
    const viewportWidth = 1100.0;
    const crossAxisCount = 3;
    const horizontalPadding = 64.0;
    const spacing = 20.0;
    final ratio = mediaGridChildAspectRatio(
      viewportWidth: viewportWidth,
      crossAxisCount: crossAxisCount,
      horizontalPadding: horizontalPadding,
    );
    expect(ratio, greaterThan(1.15));
    expect(ratio, lessThan(1.55));

    final tileWidth =
        (viewportWidth - horizontalPadding - spacing * (crossAxisCount - 1)) /
        crossAxisCount;
    final tileHeight = tileWidth / ratio;
    final videoHeight = tileWidth * 9 / 16;
    expect(videoHeight / tileHeight, greaterThan(0.68));
  });

  test('narrow two-column tiles still leave only a thin caption strip', () {
    final ratio = mediaGridChildAspectRatio(
      viewportWidth: 800,
      crossAxisCount: 2,
      horizontalPadding: 64,
    );
    expect(ratio, greaterThan(1.1));
    expect(ratio, greaterThan(0.82));
  });

  testWidgets('premium media grid paints compact tiles without overflow', (tester) async {
    TestWidgetsFlutterBinding.ensureInitialized();
    GoogleFonts.config.allowRuntimeFetching = false;
    SharedPreferences.setMockInitialValues({});
    tester.view.physicalSize = const Size(1100, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    final auth = AuthController();
    auth.token = 'test-token';
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
        child: MaterialApp(
          home: MediaLibraryScreen(
            apiService: _mediaApi(
              token: 'test-token',
              results: [
                _videoJson(
                  id: 1,
                  vimeoId: '1217796650',
                  title: 'Copy of January 4',
                ),
                _videoJson(
                  id: 2,
                  vimeoId: '898217873',
                  title: 'January 4',
                ),
                _videoJson(
                  id: 3,
                  vimeoId: '494579763',
                  title: 'December 31',
                ),
              ],
            ),
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));

    expect(tester.takeException(), isNull);
    expect(find.text('The NORDINS'), findsOneWidget);
    expect(find.text("Walk through the Word from The Nordin's"), findsOneWidget);
    expect(find.text("Nordin's"), findsNothing);
    expect(find.textContaining('This library hosts Daily Devotionals'), findsNothing);
    expect(find.text('Unlock with Premium'), findsNothing);
    expect(find.text('Copy of January 4'), findsOneWidget);
    expect(find.text('January 4'), findsOneWidget);
    expect(find.text('Welcome to Media'), findsNothing);
    expect(find.text('Morning Devotional — Faith Over Fear'), findsNothing);
    expect(find.text('Video'), findsNothing);
    expect(find.text('Premium'), findsWidgets);
  });

  testWidgets('media catalog sends the session token to GET /api/media/', (tester) async {
    TestWidgetsFlutterBinding.ensureInitialized();
    GoogleFonts.config.allowRuntimeFetching = false;
    SharedPreferences.setMockInitialValues({});
    tester.view.physicalSize = const Size(1100, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    final auth = AuthController(restoreSession: false);
    auth.token = 'subscriber-token';
    auth.sessionReady = true;
    auth.user = const AuthUser(
      id: '9',
      email: 'sub@test.com',
      name: 'Subscriber',
      isPremium: true,
      subscriptionStatus: 'active',
    );
    final capturedAuth = <String>[];

    await tester.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider<AuthController>.value(value: auth),
          ChangeNotifierProvider(create: (_) => LocaleController()),
        ],
        child: MaterialApp(
          home: MediaLibraryScreen(
            apiService: _mediaApi(
              token: 'subscriber-token',
              capturedAuthHeaders: capturedAuth,
              results: [
                _videoJson(
                  id: 12,
                  vimeoId: '1217796650',
                  title: 'Copy of January 4',
                ),
              ],
            ),
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));

    expect(capturedAuth, isNotEmpty);
    expect(capturedAuth.first, 'Token subscriber-token');
    expect(find.text('Copy of January 4'), findsOneWidget);
    expect(find.text('Welcome to Media'), findsNothing);
  });
}
