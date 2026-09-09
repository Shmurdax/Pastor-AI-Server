import 'package:http/http.dart' as http;

/// One in-memory conversation, including an optional in-flight HTTP stream.
///
/// The visible chat page points at whichever thread matches the current
/// `sessionId`. Other threads keep generating in the background.
class LiveChatThread {
  LiveChatThread({required this.sessionId});

  final String sessionId;
  final List<Map<String, dynamic>> messages = [];
  List<String> librarySermons = [];
  List<String> previousSermons = [];
  bool isLoading = false;
  bool cancelled = false;
  bool isFirstMessage = true;
  http.Client? client;
  String streamRaw = '';

  bool get isStreamingReply {
    if (messages.isEmpty) return false;
    final last = messages.last;
    return last['role'] == 'ai' && last['streaming'] == true;
  }

  bool get showThinkingLogo {
    if (!isLoading) return false;
    if (!isStreamingReply) return true;
    final text = (messages.last['text'] as String?) ?? '';
    return text.trim().isEmpty;
  }

  void appendUser(String text) {
    messages.add({'role': 'user', 'text': text});
    isFirstMessage = false;
  }

  void beginRequest({required http.Client httpClient}) {
    cancelled = false;
    streamRaw = '';
    isLoading = true;
    client = httpClient;
  }

  void appendDelta(String delta, {required String Function(String raw) format}) {
    if (cancelled || delta.isEmpty) return;
    streamRaw += delta;
    final display = format(streamRaw);
    if (isStreamingReply) {
      messages.last['text'] = display;
    } else {
      messages.add({
        'role': 'ai',
        'text': display,
        'streaming': true,
        'reported': false,
      });
    }
  }

  void applySources({required List<String> sources}) {
    if (librarySermons.isNotEmpty) {
      previousSermons = {...librarySermons, ...previousSermons}.take(25).toList();
    }
    if (sources.isNotEmpty) {
      librarySermons = List<String>.from(sources);
      previousSermons.removeWhere(librarySermons.contains);
    }
  }

  void complete({
    required String answer,
    List<String> sources = const [],
    dynamic messageId,
  }) {
    if (cancelled) return;
    if (isStreamingReply) {
      messages.last['text'] = answer;
      messages.last['streaming'] = false;
      messages.last['sources'] = List<String>.from(sources);
      messages.last['reported'] = false;
      if (messageId != null) messages.last['message_id'] = messageId;
    } else if (answer.isNotEmpty) {
      messages.add({
        'role': 'ai',
        'text': answer,
        'sources': List<String>.from(sources),
        if (messageId != null) 'message_id': messageId,
        'reported': false,
      });
    }
    finishRequest();
  }

  void applyServerError({required String localKey, required String text}) {
    if (cancelled) return;
    if (isStreamingReply) {
      messages.last['streaming'] = false;
      if (streamRaw.trim().isEmpty) {
        messages.last['localKey'] = localKey;
        messages.last['text'] = text;
      }
    } else {
      messages.add({'role': 'ai', 'localKey': localKey, 'text': text});
    }
    finishRequest();
  }

  void finishRequest() {
    streamRaw = '';
    isLoading = false;
    client = null;
    if (isStreamingReply) {
      messages.last['streaming'] = false;
    }
  }

  /// Abort the HTTP stream and drop the in-progress AI bubble.
  /// The user question stays; partial model text is not kept in context.
  void stopAndDiscardReply() {
    cancelled = true;
    streamRaw = '';
    isLoading = false;
    final toClose = client;
    client = null;
    toClose?.close();
    if (isStreamingReply) {
      messages.removeLast();
    }
    for (final msg in messages) {
      if (msg['streaming'] == true) msg['streaming'] = false;
    }
  }

  void hydrateFromSnapshot(Map<String, dynamic> entry) {
    messages
      ..clear()
      ..addAll(
        (entry['messages'] as List<dynamic>? ?? const []).whereType<Map>().map((m) {
          final copy = Map<String, dynamic>.from(m);
          copy['streaming'] = false;
          return copy;
        }),
      );
    if (messages.isNotEmpty &&
        messages.last['role'] == 'ai' &&
        messages.last['localKey'] == null &&
        ((messages.last['text'] as String?) ?? '').trim().isEmpty) {
      messages.removeLast();
    }
    librarySermons = List<String>.from(entry['librarySermons'] ?? const []);
    previousSermons = List<String>.from(entry['previousSermons'] ?? const []);
    isFirstMessage = messages.isEmpty;
    isLoading = false;
    cancelled = false;
    streamRaw = '';
  }

  Map<String, dynamic> toSnapshot({required String title}) {
    return {
      'sessionId': sessionId,
      'title': title,
      'updatedAt': DateTime.now().millisecondsSinceEpoch,
      'messages': messages
          .where((m) => m['streaming'] != true)
          .map((m) => Map<String, dynamic>.from(m))
          .toList(),
      'librarySermons': List<String>.from(librarySermons),
      'previousSermons': List<String>.from(previousSermons),
    };
  }
}
