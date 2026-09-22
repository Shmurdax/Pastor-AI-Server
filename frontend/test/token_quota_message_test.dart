import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_application_1/services/api_client.dart';

void main() {
  test('chatApiErrorMessage reads error field', () {
    expect(
      chatApiErrorMessage(
        '{"error":"You\'ve run out of responses for now. Please wait about 2 days.","code":"token_daily_limit"}',
      ),
      "You've run out of responses for now. Please wait about 2 days.",
    );
  });

  test('chatFailureMessageFromException unwraps HTTP bodies', () {
    expect(
      chatFailureMessageFromException(
        Exception(
          'HTTP 429: {"error":"You\'ve run out of responses for now.","code":"token_cooldown"}',
        ),
      ),
      "You've run out of responses for now.",
    );
  });

  test('chatFailureMessageFromException keeps plain describeHttpError text', () {
    expect(
      chatFailureMessageFromException(
        Exception("You've run out of responses for now. Please wait about 2 days."),
      ),
      "You've run out of responses for now. Please wait about 2 days.",
    );
  });
}
