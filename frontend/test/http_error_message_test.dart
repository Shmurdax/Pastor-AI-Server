import 'package:flutter_application_1/services/api_client.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

void main() {
  test('JSON detail is shown for billing errors', () {
    final res = http.Response(
      '{"detail":"You need an active Premium subscription to change plans."}',
      400,
      headers: {'content-type': 'application/json'},
    );
    expect(
      describeHttpError(res),
      'You need an active Premium subscription to change plans.',
    );
  });

  test('RunPod HTML 502 is not dumped into the UI', () {
    const html =
        '<!DOCTYPE html><html lang="en"><head>'
        '<title>Waiting for server to respond | RunPod</title>'
        '</head><body>HTTP 502</body></html>';
    final res = http.Response(
      html,
      502,
      headers: {'content-type': 'text/html; charset=utf-8'},
    );
    expect(
      describeHttpError(res),
      'The server did not respond in time. Please try again.',
    );
    expect(describeHttpError(res).contains('<html'), isFalse);
    expect(describeHttpError(res).contains('RunPod'), isFalse);
  });
}
