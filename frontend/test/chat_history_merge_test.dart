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

  test('remoteHistoryEntryIsAhead follows a growing AI draft', () {
    expect(
      remoteHistoryEntryIsAhead(
        localMessages: [
          {'role': 'user', 'text': 'What is faith?'},
          {'role': 'ai', 'text': 'Faith', 'streaming': true},
        ],
        remoteEntry: {
          'messages': [
            {'role': 'user', 'text': 'What is faith?'},
            {'role': 'ai', 'text': 'Faith is trust in God.', 'streaming': true},
          ],
        },
        localGenerating: false,
      ),
      isTrue,
    );
    expect(
      remoteHistoryEntryIsAhead(
        localMessages: [
          {'role': 'user', 'text': 'What is faith?'},
        ],
        remoteEntry: {
          'messages': [
            {'role': 'user', 'text': 'What is faith?'},
            {'role': 'ai', 'text': '', 'streaming': true},
          ],
        },
        localGenerating: false,
      ),
      isTrue,
    );
    expect(
      remoteHistoryEntryIsAhead(
        localMessages: [
          {'role': 'user', 'text': 'What is faith?'},
        ],
        remoteEntry: {
          'messages': [
            {'role': 'user', 'text': 'What is faith?'},
            {'role': 'ai', 'text': 'Faith is trust.', 'streaming': true},
          ],
        },
        localGenerating: true,
      ),
      isFalse,
    );
    expect(
      remoteHistoryEntryIsAhead(
        localMessages: [
          {'role': 'user', 'text': 'What is faith?'},
          {'role': 'ai', 'text': 'Faith is trust.', 'streaming': true},
        ],
        remoteEntry: {
          'messages': [
            {'role': 'user', 'text': 'What is faith?'},
            {
              'role': 'ai',
              'text': 'Faith is trust.',
              'streaming': false,
              'sources': ['Faith That Works'],
            },
          ],
        },
        localGenerating: false,
      ),
      isTrue,
    );
  });

  test('merge keeps a live streaming draft over a newer shorter PUT', () {
    final merged = mergeChatHistoryEntries(
      [
        {
          'sessionId': 'a',
          'updatedAt': 10,
          'messages': [
            {'role': 'user', 'text': 'What is faith?'},
            {'role': 'ai', 'text': 'Faith is trust in God.', 'streaming': true},
          ],
        },
      ],
      [
        {
          'sessionId': 'a',
          'updatedAt': 99,
          'messages': [
            {'role': 'user', 'text': 'What is faith?'},
          ],
        },
      ],
    );
    expect((merged.single['messages'] as List).length, 2);
    expect(
      ((merged.single['messages'] as List).last as Map)['text'],
      'Faith is trust in God.',
    );
  });
}
