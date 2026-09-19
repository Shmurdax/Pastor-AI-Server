import 'package:flutter_application_1/chat_sanitize.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('strips mid-sentence Chinese from an English reply', () {
    const leaked = '''
Pastor Don Nordin addresses racism as both a personal sin and a structural sin.

One of these foundational truths is the concept of "the image of God." Recognizing this inherent value in each person compels us to reject任何形式的歧视，并努力实现真正的和解。

诺丁牧师强调，种族主义既是个人的罪，也是结构性的罪。
''';
    final cleaned = sanitizeVisibleChatText(leaked, language: 'en');
    expect(cleaned.contains(RegExp(r'[\u3400-\u9fff]')), isFalse);
    expect(cleaned, contains('image of God'));
    expect(cleaned, contains('personal sin'));
    expect(hasUnexpectedCjk(leaked, language: 'en'), isTrue);
    expect(hasUnexpectedCjk(cleaned, language: 'en'), isFalse);
  });

  test('keeps the English lead-in and drops splice junk', () {
    const leaked =
        "God's forgiveness is not conditional on our performance or worthiness. "
        'It is an act of pure grace, extended freely to all who seek it. '
        'Just as the father forgave his son, we are called to forgive those who '
        'have wronged us. This doesnfsp;\n'
        '宽容和怜悯\n'
        '首先，让我们考虑父亲的回应。';
    final cleaned = sanitizeVisibleChatText(leaked, language: 'en');
    expect(cleaned.contains(RegExp(r'[\u3400-\u9fff]')), isFalse);
    expect(cleaned, contains('pure grace'));
    expect(cleaned, contains('wronged us.'));
    expect(cleaned.contains('doesnfsp'), isFalse);
    expect(cleaned.contains('宽容'), isFalse);
  });

  test('keeps Chinese when the UI language is Chinese', () {
    const text = '任何形式的歧视';
    expect(sanitizeVisibleChatText(text, language: 'zh'), text);
  });
}
