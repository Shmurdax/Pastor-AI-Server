import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/l10n/app_locale.dart';
import 'package:flutter_application_1/main.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

Map<String, dynamic> _chat(String id, String title, int updatedAt) {
  return {
    'sessionId': id,
    'title': title,
    'updatedAt': updatedAt,
    'messages': [
      {'role': 'user', 'text': title},
    ],
  };
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUpAll(() {
    GoogleFonts.config.allowRuntimeFetching = false;
  });

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  test('deleted chat ids round-trip per account', () async {
    const storage = TokenStorage();
    await storage.saveDeletedChatSessionIds('user-1', ['b', 'a', 'b', ' ']);
    expect(await storage.loadDeletedChatSessionIds('user-1'), ['b', 'a']);
    expect(await storage.loadDeletedChatSessionIds('user-2'), isEmpty);
  });

  testWidgets('select mode deletes several chats and keeps them deleted',
      (tester) async {
    tester.view.physicalSize = const Size(1400, 1000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    SharedPreferences.setMockInitialValues({
      'chat_history_guest': jsonEncode([
        _chat('chat-a', 'Faith question', 200),
        _chat('chat-b', 'Grace question', 100),
      ]),
    });

    Future<void> pumpChat() async {
      final auth = AuthController(restoreSession: false);
      auth.sessionReady = true;
      await tester.pumpWidget(
        MultiProvider(
          providers: [
            ChangeNotifierProvider<AuthController>.value(value: auth),
            ChangeNotifierProvider(create: (_) => LocaleController()),
          ],
          child: MaterialApp(home: ChatScreen(key: UniqueKey())),
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
    }

    await pumpChat();
    await tester.tap(find.text('Chats'));
    await tester.pump();

    expect(find.text('Faith question'), findsOneWidget);
    expect(find.text('Grace question'), findsOneWidget);

    await tester.tap(find.byKey(const Key('chat-history-select')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('chat-history-select-all')));
    await tester.pump();
    expect(find.byKey(const Key('chat-history-delete-selected')), findsOneWidget);

    await tester.tap(find.byKey(const Key('chat-history-delete-selected')));
    await tester.pump();
    await tester.tap(find.widgetWithText(FilledButton, 'Delete'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.text('Faith question'), findsNothing);
    expect(find.text('Grace question'), findsNothing);
    expect(find.text('Chats deleted'), findsOneWidget);

    final prefs = await SharedPreferences.getInstance();
    final saved = jsonDecode(prefs.getString('chat_history_guest')!) as List;
    final deleted =
        jsonDecode(prefs.getString('chat_history_deleted_guest')!) as List;
    expect(saved, isEmpty);
    expect(deleted, containsAll(['chat-a', 'chat-b']));

    // A refresh reloads local history. A stale copy of a deleted chat stays
    // out, while a chat that was not deleted comes back.
    await prefs.setString(
      'chat_history_deleted_guest',
      jsonEncode(['chat-a']),
    );
    await prefs.setString(
      'chat_history_guest',
      jsonEncode([
        _chat('chat-a', 'Faith question', 200),
        _chat('chat-b', 'Grace question', 100),
      ]),
    );
    await pumpChat();
    await tester.tap(find.text('Chats'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.text('Faith question'), findsNothing);
    expect(find.text('Grace question'), findsOneWidget);

    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();
  });
}
