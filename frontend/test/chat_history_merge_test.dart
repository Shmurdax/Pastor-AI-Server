import 'package:flutter_application_1/chat_history_merge.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('newer updatedAt wins for the same session', () {
    final merged = mergeChatHistoryEntries(
      [
        {
          'sessionId': 'a',
          'updatedAt': 10,
          'messages': [
            {'role': 'user', 'text': 'old'},
          ],
        },
      ],
      [
        {
          'sessionId': 'a',
          'updatedAt': 20,
          'messages': [
            {'role': 'user', 'text': 'new'},
            {'role': 'ai', 'text': 'answer'},
          ],
        },
      ],
    );
    expect(merged, hasLength(1));
    expect(merged.single['updatedAt'], 20);
    expect((merged.single['messages'] as List).length, 2);
  });

  test('keeps distinct sessions from both sides', () {
    final merged = mergeChatHistoryEntries(
      [
        {'sessionId': 'local', 'updatedAt': 5, 'messages': <dynamic>[]},
      ],
      [
        {'sessionId': 'remote', 'updatedAt': 8, 'messages': <dynamic>[]},
      ],
    );
    expect(merged.map((e) => e['sessionId']), ['remote', 'local']);
  });

  test('equal timestamps prefer more messages', () {
    final merged = mergeChatHistoryEntries(
      [
        {
          'sessionId': 'a',
          'updatedAt': 10,
          'messages': [
            {'role': 'user', 'text': 'q'},
          ],
        },
      ],
      [
        {
          'sessionId': 'a',
          'updatedAt': 10,
          'messages': [
            {'role': 'user', 'text': 'q'},
            {'role': 'ai', 'text': 'a'},
          ],
        },
      ],
    );
    expect((merged.single['messages'] as List).length, 2);
  });

  test('preferActiveSessionId keeps local when set', () {
    expect(preferActiveSessionId('local', 'remote'), 'local');
    expect(preferActiveSessionId('', 'remote'), 'remote');
    expect(preferActiveSessionId(null, null), '');
  });
}
