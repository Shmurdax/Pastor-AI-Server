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
}
