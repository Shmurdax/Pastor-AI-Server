import 'package:flutter_application_1/live_chat_thread.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

void main() {
  test('stop drops the in-progress AI bubble and keeps the user question', () {
    final thread = LiveChatThread(sessionId: 'a');
    thread.appendUser('What is grace?');
    thread.beginRequest(httpClient: http.Client());
    thread.appendDelta('Grace is', format: (raw) => raw);

    expect(thread.messages, hasLength(2));
    expect(thread.isStreamingReply, isTrue);

    thread.stopAndDiscardReply();

    expect(thread.cancelled, isTrue);
    expect(thread.isLoading, isFalse);
    expect(thread.messages, hasLength(1));
    expect(thread.messages.single['role'], 'user');
    expect(thread.messages.single['text'], 'What is grace?');
    expect(
      thread.toSnapshot(title: 'What is grace?')['messages'],
      [
        {'role': 'user', 'text': 'What is grace?'},
      ],
    );
  });

  test('deltas stay on the thread that started the request', () {
    final first = LiveChatThread(sessionId: 'one');
    final second = LiveChatThread(sessionId: 'two');
    first.appendUser('First question');
    first.beginRequest(httpClient: http.Client());
    first.appendDelta('Answer for one', format: (raw) => raw);

    second.appendUser('Second question');
    second.beginRequest(httpClient: http.Client());
    second.appendDelta('Answer for two', format: (raw) => raw);

    expect(first.messages.last['text'], 'Answer for one');
    expect(second.messages.last['text'], 'Answer for two');
    first.appendDelta(' still going', format: (raw) => raw);
    expect(first.messages.last['text'], 'Answer for one still going');
    expect(second.messages.last['text'], 'Answer for two');
  });

  test('a cancelled thread ignores later deltas and completion', () {
    final thread = LiveChatThread(sessionId: 's');
    thread.appendUser('Q');
    thread.beginRequest(httpClient: http.Client());
    thread.appendDelta('Partial', format: (raw) => raw);
    thread.stopAndDiscardReply();
    thread.appendDelta(' more', format: (raw) => raw);
    thread.complete(answer: 'Partial more', sources: const ['Hebrews']);

    expect(thread.messages, hasLength(1));
    expect(thread.messages.single['role'], 'user');
  });

  test('snapshots omit streaming AI so it never lands in saved context', () {
    final thread = LiveChatThread(sessionId: 's');
    thread.appendUser('Q');
    thread.beginRequest(httpClient: http.Client());
    thread.appendDelta('Not finished', format: (raw) => raw);

    final snapshot = thread.toSnapshot(title: 'Q');
    final messages = snapshot['messages'] as List;
    expect(messages, hasLength(1));
    expect(messages.single['role'], 'user');
  });
}
