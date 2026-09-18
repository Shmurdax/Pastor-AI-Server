/// Merge local and server chat-history snapshots by [sessionId].
///
/// Prefer the richer live draft over a newer but shorter PUT snapshot so an
/// in-flight answer is not clobbered. Then fall back to [updatedAt].
List<Map<String, dynamic>> mergeChatHistoryEntries(
  List<Map<String, dynamic>> local,
  List<Map<String, dynamic>> remote,
) {
  final byId = <String, Map<String, dynamic>>{};

  void consider(Map<String, dynamic> entry) {
    final id = entry['sessionId']?.toString().trim() ?? '';
    if (id.isEmpty) return;
    final next = Map<String, dynamic>.from(entry);
    final existing = byId[id];
    if (existing == null) {
      byId[id] = next;
      return;
    }
    byId[id] = richerHistoryEntry(existing, next);
  }

  for (final entry in local) {
    consider(entry);
  }
  for (final entry in remote) {
    consider(entry);
  }

  final merged = byId.values.toList()
    ..sort(
      (a, b) =>
          (b['updatedAt'] as int? ?? 0).compareTo(a['updatedAt'] as int? ?? 0),
    );
  return merged;
}

String preferActiveSessionId(String? local, String? remote) {
  final localId = (local ?? '').trim();
  if (localId.isNotEmpty) return localId;
  return (remote ?? '').trim();
}

bool historyEntryIsStreaming(Map<String, dynamic>? entry) {
  if (entry == null) return false;
  final messages = (entry['messages'] as List?) ?? const [];
  for (var i = messages.length - 1; i >= 0; i--) {
    final item = messages[i];
    if (item is Map && item['role'] == 'ai') {
      return item['streaming'] == true;
    }
  }
  return false;
}

Map<String, dynamic> richerHistoryEntry(
  Map<String, dynamic> existing,
  Map<String, dynamic> incoming,
) {
  final existingStream = historyEntryIsStreaming(existing);
  final incomingStream = historyEntryIsStreaming(incoming);
  final existingLen = _lastAiText(existing).length;
  final incomingLen = _lastAiText(incoming).length;
  final existingN = (existing['messages'] as List?)?.length ?? 0;
  final incomingN = (incoming['messages'] as List?)?.length ?? 0;
  final existingAt = existing['updatedAt'] as int? ?? 0;
  final incomingAt = incoming['updatedAt'] as int? ?? 0;

  if (existingStream &&
      !incomingStream &&
      incomingN <= existingN &&
      incomingLen <= existingLen) {
    return existing;
  }
  if (incomingStream &&
      !existingStream &&
      existingN <= incomingN &&
      existingLen <= incomingLen) {
    return incoming;
  }
  if (existingN != incomingN) {
    return incomingN > existingN ? incoming : existing;
  }
  if (existingLen != incomingLen) {
    return incomingLen > existingLen ? incoming : existing;
  }
  if (existingStream != incomingStream) {
    return existingStream ? existing : incoming;
  }
  return incomingAt >= existingAt ? incoming : existing;
}

String _lastAiText(Map<String, dynamic> entry) {
  final messages = (entry['messages'] as List?) ?? const [];
  for (var i = messages.length - 1; i >= 0; i--) {
    final item = messages[i];
    if (item is Map && item['role'] == 'ai') {
      return (item['text'] as String? ?? '');
    }
  }
  return '';
}

/// True when a polled server snapshot should replace the local thread.
///
/// Skip when this tab is the one generating ([localGenerating]). Prefer more
/// messages, then a longer latest AI draft so streaming tokens keep landing.
/// A completed remote draft (streaming false, sources attached) also wins
/// over an equal-length local streaming bubble.
bool remoteHistoryEntryIsAhead({
  required List<Map<String, dynamic>> localMessages,
  required Map<String, dynamic> remoteEntry,
  required bool localGenerating,
}) {
  if (localGenerating) return false;
  final remoteMessages = (remoteEntry['messages'] as List?) ?? const [];
  if (remoteMessages.isEmpty && localMessages.isEmpty) return false;
  if (remoteMessages.length != localMessages.length) {
    return remoteMessages.length > localMessages.length;
  }

  Map? lastAi(List messages) {
    for (var i = messages.length - 1; i >= 0; i--) {
      final item = messages[i];
      if (item is Map && item['role'] == 'ai') return item;
    }
    return null;
  }

  final remoteAi = lastAi(remoteMessages);
  final localAi = lastAi(localMessages);
  final remoteText = (remoteAi?['text'] as String? ?? '');
  final localText = (localAi?['text'] as String? ?? '');
  if (remoteText.length > localText.length) return true;
  if (remoteText.length < localText.length) return false;
  final localStreaming = localAi?['streaming'] == true;
  final remoteStreaming = remoteAi?['streaming'] == true;
  if (localStreaming && !remoteStreaming) return true;
  final remoteSources = (remoteAi?['sources'] as List?)?.length ?? 0;
  final localSources = (localAi?['sources'] as List?)?.length ?? 0;
  return remoteSources > localSources;
}
