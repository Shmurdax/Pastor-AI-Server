import 'package:flutter_application_1/billing_return_query.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('drops checkout return params and keeps the rest of the URL', () {
    final cleaned = uriWithoutBillingReturn(
      Uri.parse(
        'https://dev.thenordins.org/?billing=success&session_id=cs_test&lang=es',
      ),
    );

    expect(cleaned.queryParameters.containsKey('billing'), isFalse);
    expect(cleaned.queryParameters.containsKey('session_id'), isFalse);
    expect(cleaned.queryParameters['lang'], 'es');
    expect(cleaned.toString(), 'https://dev.thenordins.org/?lang=es');
  });

  test('drops a payment-method return URL back to the app root', () {
    final cleaned = uriWithoutBillingReturn(
      Uri.parse(
        'https://dev.thenordins.org/?billing=payment_updated&session_id=cs_test',
      ),
    );

    expect(cleaned.toString(), 'https://dev.thenordins.org/');
  });

  test('leaves unrelated URLs unchanged', () {
    final original = Uri.parse('https://dev.thenordins.org/chat?lang=en');
    expect(uriWithoutBillingReturn(original), original);
  });
}
