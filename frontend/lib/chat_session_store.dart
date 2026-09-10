import 'package:flutter_application_1/chat_stream.dart';
import 'package:flutter_application_1/sermon_sources.dart';
import 'package:http/http.dart' as http;

/// Mutable runtime for one chat thread: messages plus any in-flight stream.
class ChatSessionRuntime {
  ChatSessionRuntime(this.sessionId);

  String sessionId;
  final List<Map<String, dynamic>> messages = [];
  List<String> librarySermons = [];
  List<String> previousSermons = [];
  bool isFirstMessage = true;

  http.Client? activeClient;
  String streamRaw = '';
  bool streamCancelled = false;
  int streamEpoch = 0;
  bool isLoading = false;

  bool get isStreamingReply {
    if (messages.isEmpty) return false;
    return isStreamingAiMessage(messages.last);
  }

  /// True while a reply is requested or tokens are still arriving.
  bool get isGenerating => isLoading || isStreamingReply;

  bool get showThinkingLogo {
    if (!isLoading) return false;
    if (!isStreamingReply) return true;
    final text = (messages.last['text'] as String?) ?? '';
    return text.trim().isEmpty;
  }

  bool isCurrentStream(int epoch) {
    return !streamCancelled &&
        isLoading &&
        activeClient != null &&
        epoch == streamEpoch;
  }

  void clearContent() {
    messages.clear();
    librarySermons.clear();
    previousSermons.clear();
    isFirstMessage = true;
  }

  void loadFromHistoryEntry(Map<String, dynamic> entry) {
    messages
      ..clear()
      ..addAll(
        (entry['messages'] as List<dynamic>? ?? const [])
            .whereType<Map>()
            .map((m) => Map<String, dynamic>.from(m)),
      );
    librarySermons = withoutVideoSermonSources(
      List<String>.from(entry['librarySermons'] ?? const []),
    );
    previousSermons = withoutVideoSermonSources(
      List<String>.from(entry['previousSermons'] ?? const []),
    );
    isFirstMessage = messages.isEmpty;
  }

  Map<String, dynamic> toHistorySnapshot({
    required String title,
    required int updatedAt,
  }) {
    return {
      'sessionId': sessionId,
      'title': title,
      'updatedAt': updatedAt,
      'messages': messages.map((m) => Map<String, dynamic>.from(m)).toList(),
      'librarySermons': withoutVideoSermonSources(librarySermons),
      'previousSermons': withoutVideoSermonSources(previousSermons),
    };
  }

  /// Begins a new stream for this chat. Returns the epoch bound to callbacks.
  /// If a stream is already active, returns null (one stream per chat).
  int? beginStream({required http.Client client}) {
    if (isGenerating) return null;
    streamRaw = '';
    streamCancelled = false;
    final epoch = ++streamEpoch;
    isLoading = true;
    activeClient = client;
    return epoch;
  }

  void stopStream({required String cancelledText}) {
    if (!isLoading && activeClient == null && !isStreamingReply) return;
    streamCancelled = true;
    streamEpoch += 1;
    activeClient?.close();
    isLoading = false;
    activeClient = null;
    finalizeChatStreamOnStop(
      messages,
      cancelledText: cancelledText,
      raw: streamRaw,
    );
    streamRaw = '';
  }

  void finishStreamCleanup(int epoch) {
    if (epoch != streamEpoch) return;
    streamRaw = '';
    isLoading = false;
    activeClient = null;
    if (isStreamingReply) {
      messages.last['streaming'] = false;
    }
  }
}

/// Keeps each chat's messages and stream isolated so switching chats/pages
/// does not cancel or redirect another chat's reply.
class ChatSessionStore {
  ChatSessionStore({required String initialSessionId})
      : currentSessionId = initialSessionId;

  String currentSessionId;
  final Map<String, ChatSessionRuntime> _byId = {};

  ChatSessionRuntime get current => ensure(currentSessionId);

  ChatSessionRuntime ensure(String sessionId) {
    return _byId.putIfAbsent(sessionId, () => ChatSessionRuntime(sessionId));
  }

  ChatSessionRuntime? peek(String sessionId) => _byId[sessionId];

  bool isGenerating(String sessionId) =>
      _byId[sessionId]?.isGenerating ?? false;

  /// Switch the visible chat without stopping other sessions' streams.
  ///
  /// Prefer live runtime messages when this session already has content or is
  /// generating; otherwise hydrate from [historyEntry].
  ChatSessionRuntime switchTo(
    String sessionId, {
    Map<String, dynamic>? historyEntry,
  }) {
    currentSessionId = sessionId;
    final runtime = ensure(sessionId);
    final shouldHydrate = historyEntry != null &&
        !runtime.isGenerating &&
        runtime.messages.isEmpty;
    if (shouldHydrate) {
      runtime.loadFromHistoryEntry(historyEntry);
    }
    return runtime;
  }

  /// Start a blank chat as the visible session (other streams keep running).
  ChatSessionRuntime startNewChat(String newSessionId) {
    currentSessionId = newSessionId;
    return ensure(newSessionId);
  }

  /// Cancel and drop a session (e.g. delete chat or sign-out).
  void disposeSession(String sessionId, {required String cancelledText}) {
    final runtime = _byId.remove(sessionId);
    if (runtime == null) return;
    runtime.stopStream(cancelledText: cancelledText);
  }

  void disposeAll({required String cancelledText}) {
    for (final id in _byId.keys.toList()) {
      disposeSession(id, cancelledText: cancelledText);
    }
  }
}
