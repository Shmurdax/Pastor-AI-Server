import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/episode_note_text.dart';
import 'package:flutter_application_1/l10n/app_locale.dart';
import 'package:flutter_application_1/models/episode_note.dart';
import 'package:flutter_application_1/models/media_item.dart';
import 'package:flutter_application_1/screens/media_library_screen.dart';
import 'package:flutter_application_1/services/api_client.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:flutter_application_1/widgets/episode_notes_pane.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('topic labels are capitalized and camel case is split into words', () {
    expect(displayTopicLabel('babel'), 'Babel');
    expect(displayTopicLabel('languages'), 'Languages');
    expect(displayTopicLabel('TheNameOfTheLord'), 'The Name Of The Lord');
    expect(displayTopicLabel('GodsWord'), 'Gods Word');
    expect(displayTopicLabel('butGod'), 'But God');
    expect(displayTopicLabel('SOW'), 'SOW');
  });

  test('keyword highlights keep the original spelling', () {
    final span = highlightedNoteSpan(
      body: 'The Queen of Sheba traveled to Solomon.',
      query: 'sheba',
      style: const TextStyle(),
      highlightStyle: const TextStyle(backgroundColor: Color(0xFFD4AF37)),
    );
    final children = span.children!.cast<TextSpan>();
    final hit = children.firstWhere((child) => child.text == 'Sheba');
    expect(hit.style?.backgroundColor, const Color(0xFFD4AF37));
  });

  test('episode note dates stay on the calendar day in the filename', () {
    expect(formatEpisodeDate('2026-05-15'), contains('2026'));
    expect(formatEpisodeDate('2026-05-15'), contains('15'));
  });

  test('media items carry notes separately from the sermon catalog', () {
    final item = MediaItem.fromApiJson({
      'id': 7,
      'vimeo_id': 'may-2026',
      'title': 'May 15',
      'description': 'Devotional',
      'published_at': '2026-05-15T15:00:00Z',
      'access_tier': 'premium',
      'is_published': true,
      'note': {
        'id': 3,
        'episode_date': '2026-05-15',
        'topics': ['TheNameOfTheLord'],
        'has_notes': true,
      },
    });
    expect(item.note, isA<EpisodeNoteSummary>());
    expect(item.note!.episodeDate, '2026-05-15');
    expect(item.tags, isNot(contains('May 15_2026.pdf')));
    expect(EpisodeNoteSummary.tryParse(null), isNull);
  });

  testWidgets('watch page hides notes when the episode has none', (tester) async {
    GoogleFonts.config.allowRuntimeFetching = false;
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);

    await tester.pumpWidget(
      MaterialApp(
        home: WatchEpisodeScreen(
          item: _video(title: 'June 2', vimeoId: 'june'),
        ),
      ),
    );
    await tester.pump();

    expect(find.text('June 2'), findsOneWidget);
    expect(find.text('Episode notes'), findsNothing);
    expect(find.text('View original PDF'), findsNothing);
  });

  testWidgets('watch page shows notes beside the player and highlights a keyword', (tester) async {
    GoogleFonts.config.allowRuntimeFetching = false;
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);

    await tester.pumpWidget(
      MaterialApp(
        home: WatchEpisodeScreen(
          item: _video(
            title: 'May 15',
            vimeoId: 'may',
            note: const EpisodeNoteSummary(
              id: 3,
              episodeDate: '2026-05-15',
              topics: ['TheNameOfTheLord', 'sheba'],
            ),
          ),
          highlightQuery: 'sheba',
          apiService: _notesApi(),
        ),
      ),
    );
    await tester.pump();
    await tester.pump();

    expect(find.text('Episode notes'), findsOneWidget);
    expect(find.text('View original PDF'), findsOneWidget);
    expect(find.text('Sheba'), findsWidgets);
    expect(find.text('The Name Of The Lord'), findsOneWidget);
    final notes = tester.getTopLeft(find.byKey(const Key('episode-notes-pane')));
    final player = tester.getTopLeft(find.byKey(const Key('episode-player')));
    expect(notes.dx, greaterThan(player.dx));

    final selectable = tester.widget<SelectableText>(find.byType(SelectableText));
    var highlighted = false;
    selectable.textSpan?.visitChildren((span) {
      if (span is TextSpan && span.text == 'Sheba' && span.style?.backgroundColor != null) {
        highlighted = true;
      }
      return true;
    });
    expect(highlighted, isTrue);

    await tester.tap(find.text('View original PDF'));
    await tester.pump();
    await tester.pump();
    expect(find.textContaining('PDF viewing is available on web'), findsOneWidget);
  });

  testWidgets('narrow watch page keeps the notes under the player', (tester) async {
    GoogleFonts.config.allowRuntimeFetching = false;
    tester.view.physicalSize = const Size(400, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);

    await tester.pumpWidget(
      MaterialApp(
        home: WatchEpisodeScreen(
          item: _video(
            title: 'May 15',
            vimeoId: 'may',
            note: const EpisodeNoteSummary(
              id: 3,
              episodeDate: '2026-05-15',
              topics: ['sheba'],
            ),
          ),
          apiService: _notesApi(),
        ),
      ),
    );
    await tester.pump();
    await tester.pump();

    final notes = tester.getTopLeft(find.byKey(const Key('episode-notes-pane')));
    final player = tester.getTopLeft(find.byKey(const Key('episode-player')));
    expect(notes.dy, greaterThan(player.dy));
    expect(find.text('Episode notes'), findsOneWidget);
  });

  testWidgets('library search sends keyword and topic, then opens that episode', (tester) async {
    GoogleFonts.config.allowRuntimeFetching = false;
    SharedPreferences.setMockInitialValues({});
    tester.view.physicalSize = const Size(1100, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);

    final requests = <Uri>[];
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

    await tester.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider<AuthController>.value(value: auth),
          ChangeNotifierProvider(create: (_) => LocaleController()),
        ],
        child: MaterialApp(
          home: MediaLibraryScreen(
            apiService: _libraryApi(requests),
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump();

    expect(find.text('May 15'), findsWidgets);
    expect(find.text('June 2'), findsOneWidget);
    expect(find.text('The Name Of The Lord'), findsNothing);
    expect(requests.any((uri) => uri.path.contains('ingested-documents')), isFalse);

    await tester.tap(find.text('Filters'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('The Name Of The Lord'));
    await tester.tap(find.text('Apply'));
    await tester.pump();
    await tester.pump();

    expect(find.text('June 2'), findsNothing);
    expect(
      requests.any((uri) => uri.queryParameters['topic'] == 'TheNameOfTheLord'),
      isTrue,
    );

    await tester.enterText(find.byType(TextField), 'sheba');
    await tester.pump(const Duration(milliseconds: 400));
    await tester.pump();

    expect(
      requests.any(
        (uri) => uri.queryParameters['q'] == 'sheba' && uri.queryParameters['topic'] == 'TheNameOfTheLord',
      ),
      isTrue,
    );
    expect(find.textContaining('Queen of Sheba'), findsOneWidget);

    await tester.tap(find.text('May 15'));
    await tester.pump();
    await tester.pump();

    expect(find.text('Episode notes'), findsOneWidget);
    expect(find.text('Now playing'), findsOneWidget);
    expect(find.textContaining('Sheba'), findsWidgets);
    expect(requests.any((uri) => uri.path.contains('ingested-documents')), isFalse);
  });
}

MediaItem _video({
  required String title,
  required String vimeoId,
  EpisodeNoteSummary? note,
}) {
  return MediaItem(
    id: vimeoId,
    title: title,
    description: 'Walk through the Word',
    publishedAt: DateTime(2026, 5, 15),
    contentType: MediaContentType.video,
    accessTier: MediaAccessTier.premium,
    vimeoId: vimeoId,
    vimeoPrivacyHash: 'abc',
    isPublished: true,
    note: note,
  );
}

Map<String, dynamic> _mayJson({String? snippet}) {
  return {
    'id': 1,
    'vimeo_id': 'may-2026',
    'privacy_hash': 'abc',
    'title': 'May 15',
    'description': 'Devotional',
    'published_at': '2026-05-15T15:00:00Z',
    'duration_seconds': 600,
    'duration_label': '10:00',
    'thumbnail_url': '',
    'access_tier': 'premium',
    'is_published': true,
    'note': {
      'id': 3,
      'episode_date': '2026-05-15',
      'topics': ['TheNameOfTheLord', 'sheba'],
      'has_notes': true,
      if (snippet != null) 'snippet': snippet,
    },
  };
}

Map<String, dynamic> _juneJson() {
  return {
    'id': 2,
    'vimeo_id': 'june-2026',
    'privacy_hash': 'def',
    'title': 'June 2',
    'description': 'Another day',
    'published_at': '2026-06-02T15:00:00Z',
    'duration_seconds': 600,
    'duration_label': '10:00',
    'thumbnail_url': '',
    'access_tier': 'premium',
    'is_published': true,
    'note': null,
  };
}

ApiService _notesApi() {
  return ApiService(
    apiClient: ApiClient(
      client: MockClient((request) async {
        if (request.url.path.endsWith('/file/')) {
          return http.Response.bytes(const [0x25, 0x50, 0x44, 0x46], 200);
        }
        return http.Response(
          jsonEncode({
            'id': 3,
            'episode_date': '2026-05-15',
            'topics': ['TheNameOfTheLord', 'sheba'],
            'body': 'The Queen of Sheba traveled to Solomon.',
            'original_filename': 'May 15_2026.pdf',
            'has_notes': true,
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      }),
    ),
  );
}

ApiService _libraryApi(List<Uri> requests) {
  return ApiService(
    apiClient: ApiClient(
      client: MockClient((request) async {
        requests.add(request.url);
        if (request.url.path.endsWith('/topics/')) {
          return http.Response(
            jsonEncode({
              'results': ['TheNameOfTheLord', 'sheba'],
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }
        if (request.url.path.contains('/episode-notes/')) {
          return http.Response(
            jsonEncode({
              'id': 3,
              'episode_date': '2026-05-15',
              'topics': ['TheNameOfTheLord', 'sheba'],
              'body': 'The Queen of Sheba traveled to Solomon.',
              'original_filename': 'May 15_2026.pdf',
              'has_notes': true,
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }
        final query = request.url.queryParameters['q'] ?? '';
        final topic = request.url.queryParameters['topic'] ?? '';
        final filtered = query == 'sheba' || topic == 'TheNameOfTheLord';
        final may = _mayJson(
          snippet: query == 'sheba' ? 'The Queen of Sheba traveled to Solomon.' : null,
        );
        return http.Response(
          jsonEncode({
            'results': filtered ? [may] : [may, _juneJson()],
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      }),
    ),
  );
}
