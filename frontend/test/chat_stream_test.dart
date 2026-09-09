import 'package:flutter_application_1/chat_stream.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('consumeSseChunk parses delta and done events', () {
    final carry = StringBuffer();
    final first = consumeSseChunk(
      carry,
      'data: {"type":"delta","text":"Faith"}\n\n',
    );
    expect(first, hasLength(1));
    expect(first.first.isDelta, isTrue);
    expect(first.first.text, 'Faith');

    final second = consumeSseChunk(
      carry,
      'data: {"type":"delta","text":" is"}\n\ndata: {"type":"done","answer":"Faith is","sources":["Hebrews"],"message_id":9}\n\n',
    );
    expect(second, hasLength(2));
    expect(second[0].text, ' is');
    expect(second[1].isDone, isTrue);
    expect(second[1].answer, 'Faith is');
    expect(second[1].sources, ['Hebrews']);
    expect(second[1].messageId, 9);
  });

  test('consumeSseChunk holds partial frames until a blank line', () {
    final carry = StringBuffer();
    expect(consumeSseChunk(carry, 'data: {"type":"delta"'), isEmpty);
    final events = consumeSseChunk(carry, ',"text":"Hi"}\n\n');
    expect(events, hasLength(1));
    expect(events.first.text, 'Hi');
  });

  test('consumeSseChunk skips keepalives and status events', () {
    final carry = StringBuffer();
    final events = consumeSseChunk(
      carry,
      ': keepalive\n\ndata: {"type":"status","phase":"started"}\n\ndata: {"type":"delta","text":"When"}\n\n',
    );
    expect(events, hasLength(2));
    expect(events[0].type, 'status');
    expect(events[1].isDelta, isTrue);
    expect(events[1].text, 'When');
  });

  test('stop keeps the live bubble instead of opening another', () {
    final messages = <Map<String, dynamic>>[
      {'role': 'user', 'text': 'What is faith?'},
    ];
    applyChatStreamDelta(messages, 'Faith');
    applyChatStreamDelta(messages, 'Faith is');
    expect(messages, hasLength(2));
    expect(messages.last['text'], 'Faith is');

    finalizeChatStreamOnStop(
      messages,
      cancelledText: 'Response cancelled.',
      raw: 'Faith is',
    );
    expect(messages, hasLength(2));
    expect(messages.last['streaming'], isFalse);
    expect(messages.last['text'], 'Faith is');
    expect(indexOfStreamingAi(messages), isNull);
  });

  test('stop before tokens adds a single cancelled bubble', () {
    final messages = <Map<String, dynamic>>[
      {'role': 'user', 'text': 'What is faith?'},
    ];
    finalizeChatStreamOnStop(
      messages,
      cancelledText: 'Response cancelled.',
      raw: '',
    );
    expect(messages, hasLength(2));
    expect(messages.last['localKey'], 'responseCancelled');
    expect(messages.last['text'], 'Response cancelled.');
  });

  test('late tokens after stop do not open another bubble', () {
    final messages = <Map<String, dynamic>>[
      {'role': 'user', 'text': 'What is faith?'},
    ];
    applyChatStreamDelta(messages, 'Faith');
    finalizeChatStreamOnStop(
      messages,
      cancelledText: 'Response cancelled.',
      raw: 'Faith',
    );

    applyChatStreamDelta(messages, 'Faith is the assurance');
    expect(messages, hasLength(2));
    expect(messages.last['text'], 'Faith');
    expect(messages.last['streaming'], isFalse);
  });

  test('a finished payload after stop does not add a second answer', () {
    final messages = <Map<String, dynamic>>[
      {'role': 'user', 'text': 'What is faith?'},
    ];
    applyChatStreamDelta(messages, 'Faith');
    finalizeChatStreamOnStop(
      messages,
      cancelledText: 'Response cancelled.',
      raw: 'Faith',
    );

    expect(
      completeChatStreamAnswer(
        messages,
        answer: 'Faith is the assurance of things hoped for.',
        sources: const ['Hebrews 11'],
        messageId: 9,
      ),
      isFalse,
    );
    expect(messages, hasLength(2));
    expect(messages.last['text'], 'Faith');
    expect(messages.last.containsKey('message_id'), isFalse);
  });
}
