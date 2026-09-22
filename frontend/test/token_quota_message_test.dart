import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_application_1/chat_stream.dart';
import 'package:flutter_application_1/services/api_client.dart';

void main() {
  test('chatApiErrorMessage reads error field', () {
    expect(
      chatApiErrorMessage(
        '{"error":"You have used up your allotted responses currently. Please wait about 2 days.","code":"token_daily_limit"}',
      ),
      'You have used up your allotted responses currently. Please wait about 2 days.',
    );
  });

  test('chatFailureMessageFromException unwraps HTTP bodies', () {
    expect(
      chatFailureMessageFromException(
        Exception(
          'HTTP 429: {"error":"You have used up your allotted responses currently. Please wait about 2 days.","code":"token_cooldown"}',
        ),
      ),
      'You have used up your allotted responses currently. Please wait about 2 days.',
    );
  });

  test('chatFailureMessageFromException keeps plain describeHttpError text', () {
    expect(
      chatFailureMessageFromException(
        Exception(
          'You have used up your allotted responses currently. Please wait about 2 days.',
        ),
      ),
      'You have used up your allotted responses currently. Please wait about 2 days.',
    );
  });

  test('applyChatStreamFailure keeps literal quota text without serverError key', () {
    final messages = <Map<String, dynamic>>[
      {'role': 'user', 'text': 'Hello'},
      {'role': 'ai', 'text': '', 'streaming': true},
    ];
    applyChatStreamFailure(
      messages,
      errorText:
          'You have used up your allotted responses currently. Please wait about 2 days.',
      literalText: true,
    );
    expect(messages.last['localKey'], isNull);
    expect(
      messages.last['text'],
      'You have used up your allotted responses currently. Please wait about 2 days.',
    );
    expect(messages.last['streaming'], isFalse);
  });

  test('applyChatStreamFailure uses serverError key for generic failures', () {
    final messages = <Map<String, dynamic>>[];
    applyChatStreamFailure(
      messages,
      errorText: 'Error: Could not connect to the server.',
    );
    expect(messages.last['localKey'], 'serverError');
  });
}
