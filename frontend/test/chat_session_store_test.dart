import 'package:flutter_application_1/chat_session_store.dart';
import 'package:flutter_application_1/chat_stream.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

class _FakeClient extends http.BaseClient {
  bool closed = false;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) {
    throw UnimplementedError();
  }

  @override
  void close() {
    closed = true;
    super.close();
  }
}

void main() {
  test('stream deltas stay on the bound session after switching chats', () {
    final store = ChatSessionStore(initialSessionId: 'a');
    final a = store.ensure('a');
    a.messages.add({'role': 'user', 'text': 'Hello A'});
    final clientA = _FakeClient();
    final epochA = a.beginStream(client: clientA)!;

    store.switchTo('b');
    expect(store.currentSessionId, 'b');
    expect(store.current.messages, isEmpty);

    applyChatStreamDelta(a.messages, 'Answer for A');
    expect(a.messages.last['text'], 'Answer for A');
    expect(a.isCurrentStream(epochA), isTrue);
    expect(store.current.messages, isEmpty);
    expect(store.isGenerating('a'), isTrue);
    expect(store.isGenerating('b'), isFalse);
  });

  test('parallel streams are allowed across chats', () {
    final store = ChatSessionStore(initialSessionId: 'a');
    final a = store.ensure('a');
    final b = store.ensure('b');
    final epochA = a.beginStream(client: _FakeClient())!;
    final epochB = b.beginStream(client: _FakeClient())!;

    applyChatStreamDelta(a.messages, 'A');
    applyChatStreamDelta(b.messages, 'B');

    expect(a.isCurrentStream(epochA), isTrue);
    expect(b.isCurrentStream(epochB), isTrue);
    expect(a.messages.last['text'], 'A');
    expect(b.messages.last['text'], 'B');
    expect(store.isGenerating('a'), isTrue);
    expect(store.isGenerating('b'), isTrue);
  });

  test('only one stream at a time per chat', () {
    final store = ChatSessionStore(initialSessionId: 'a');
    final a = store.current;
    expect(a.beginStream(client: _FakeClient()), isNotNull);
    expect(a.beginStream(client: _FakeClient()), isNull);
  });

  test('new chat does not cancel the previous stream', () {
    final store = ChatSessionStore(initialSessionId: 'a');
    final a = store.ensure('a');
    final client = _FakeClient();
    final epoch = a.beginStream(client: client)!;
    applyChatStreamDelta(a.messages, 'Still going');

    final b = store.startNewChat('b');
    expect(store.currentSessionId, 'b');
    expect(b.messages, isEmpty);
    expect(a.isCurrentStream(epoch), isTrue);
    expect(client.closed, isFalse);
    expect(a.messages.last['text'], 'Still going');
  });

  test('switching back to a generating chat shows live messages', () {
    final store = ChatSessionStore(initialSessionId: 'a');
    final a = store.ensure('a');
    a.beginStream(client: _FakeClient());
    applyChatStreamDelta(a.messages, 'Partial');

    store.switchTo(
      'b',
      historyEntry: {
        'sessionId': 'b',
        'messages': [
          {'role': 'user', 'text': 'Old B'},
        ],
      },
    );
    expect(store.current.messages.single['text'], 'Old B');

    store.switchTo('a');
    expect(store.current.messages.last['text'], 'Partial');
    expect(store.current.isGenerating, isTrue);
  });

  test('stop only affects the target session', () {
    final store = ChatSessionStore(initialSessionId: 'a');
    final a = store.ensure('a');
    final b = store.ensure('b');
    a.beginStream(client: _FakeClient());
    b.beginStream(client: _FakeClient());
    applyChatStreamDelta(a.messages, 'A text');
    applyChatStreamDelta(b.messages, 'B text');

    a.stopStream(cancelledText: 'Cancelled');
    expect(a.isGenerating, isFalse);
    expect(a.messages.last['streaming'], isFalse);
    expect(b.isGenerating, isTrue);
    expect(b.messages.last['text'], 'B text');
  });

  test('history hydrate is skipped while session is generating', () {
    final store = ChatSessionStore(initialSessionId: 'a');
    final a = store.ensure('a');
    a.beginStream(client: _FakeClient());
    applyChatStreamDelta(a.messages, 'Live');

    store.switchTo('b');
    store.switchTo(
      'a',
      historyEntry: {
        'sessionId': 'a',
        'messages': [
          {'role': 'user', 'text': 'Stale'},
        ],
      },
    );
    expect(store.current.messages.last['text'], 'Live');
  });
}
