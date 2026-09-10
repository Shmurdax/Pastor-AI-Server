/// Merge local and server chat-history snapshots by [sessionId].
///
/// Newer [updatedAt] wins. Equal timestamps prefer the entry with more messages
/// so a partial local write cannot clobber a fuller server copy.
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
    final existingAt = existing['updatedAt'] as int? ?? 0;
    final nextAt = next['updatedAt'] as int? ?? 0;
    if (nextAt > existingAt) {
      byId[id] = next;
      return;
    }
    if (nextAt < existingAt) return;
    final existingMsgs = (existing['messages'] as List?)?.length ?? 0;
    final nextMsgs = (next['messages'] as List?)?.length ?? 0;
    if (nextMsgs > existingMsgs) {
      byId[id] = next;
    }
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
