import 'dart:convert';

class ChatStreamEvent {
  const ChatStreamEvent({
    required this.type,
    this.text = '',
    this.answer = '',
    this.sources = const [],
    this.quotes = const {},
    this.messageId,
    this.error = '',
  });

  final String type;
  final String text;
  final String answer;
  final List<String> sources;
  final Map<String, Map<String, String>> quotes;
  final dynamic messageId;
  final String error;

  bool get isDelta => type == 'delta';
  bool get isReplace => type == 'replace';
  bool get isQuoteCatalog => type == 'quote_catalog';
  bool get isDone => type == 'done';
  bool get isError => type == 'error';

  factory ChatStreamEvent.fromJson(Map<String, dynamic> json) {
    final sources = <String>[];
    final rawSources = json['sources'];
    if (rawSources is List) {
      for (final item in rawSources) {
        final value = item?.toString() ?? '';
        if (value.isNotEmpty) sources.add(value);
      }
    }
    return ChatStreamEvent(
      type: json['type']?.toString() ?? '',
      text: json['text']?.toString() ?? '',
      answer: json['answer']?.toString() ?? '',
      sources: sources,
      quotes: parseQuoteCatalog(json['quotes']),
      messageId: json['message_id'],
      error: json['error']?.toString() ?? '',
    );
  }
}

final _quoteSlotRe = RegExp(r'\{\{\s*([QVqv])(\d+)\s*\}\}');

Map<String, Map<String, String>> parseQuoteCatalog(dynamic raw) {
  final out = <String, Map<String, String>>{};
  if (raw is! Map) return out;
  raw.forEach((key, value) {
    if (value is! Map) return;
    final slot = <String, String>{};
    value.forEach((field, fieldValue) {
      if (fieldValue == null) return;
      slot[field.toString()] = fieldValue.toString();
    });
    if (slot.isEmpty) return;
    out[key.toString()] = slot;
  });
  return out;
}

/// Replace {{Q1}} / {{V1}} with exact retrieved wording from [catalog].
String expandQuoteIds(String text, Map<String, Map<String, String>> catalog) {
  if (text.isEmpty || catalog.isEmpty) return text;
  return text.replaceAllMapped(_quoteSlotRe, (match) {
    final key = '${match.group(1)!.toUpperCase()}${match.group(2)}';
    final slot = catalog[key];
    if (slot == null) return '';
    final wording = slot['text'] ?? '';
    if ((slot['kind'] ?? '') == 'nkjv') {
      final ref = (slot['ref'] ?? '').trim();
      final label = ref.isEmpty ? 'NKJV' : ref;
      return '$label (NKJV): "$wording"';
    }
    return '"$wording"';
  });
}

/// Pull complete SSE `data:` blocks out of [carry] after appending [chunk].
List<ChatStreamEvent> consumeSseChunk(StringBuffer carry, String chunk) {
  carry.write(chunk);
  final events = <ChatStreamEvent>[];
  while (true) {
    final raw = carry.toString().replaceAll('\r\n', '\n');
    final idx = raw.indexOf('\n\n');
    if (idx < 0) {
      carry
        ..clear()
        ..write(raw);
      break;
    }
    final block = raw.substring(0, idx);
    carry
      ..clear()
      ..write(raw.substring(idx + 2));
    for (final line in block.split('\n')) {
      if (!line.startsWith('data:')) continue;
      final data = line.substring(5).trim();
      if (data.isEmpty || data == '[DONE]') continue;
      final decoded = jsonDecode(data);
      if (decoded is Map<String, dynamic>) {
        events.add(ChatStreamEvent.fromJson(decoded));
      } else if (decoded is Map) {
        events.add(ChatStreamEvent.fromJson(Map<String, dynamic>.from(decoded)));
      }
    }
  }
  return events;
}

bool isStreamingAiMessage(Map<String, dynamic> message) {
  return message['role'] == 'ai' && message['streaming'] == true;
}

int? indexOfStreamingAi(List<Map<String, dynamic>> messages) {
  for (var i = messages.length - 1; i >= 0; i--) {
    if (isStreamingAiMessage(messages[i])) return i;
  }
  return null;
}

/// Paints [display] into the live AI bubble. Late tokens after stop must not
/// open a second bubble — if the last AI reply is already frozen, ignore them.
void applyChatStreamDelta(List<Map<String, dynamic>> messages, String display) {
  final index = indexOfStreamingAi(messages);
  if (index != null) {
    messages[index]['text'] = display;
    return;
  }
  if (messages.isNotEmpty && messages.last['role'] == 'ai') {
    return;
  }
  messages.add({
    'role': 'ai',
    'text': display,
    'streaming': true,
    'reported': false,
  });
}

/// Ends the live reply in place. Adds a cancelled bubble only when nothing
/// has started painting yet (thinking / pre-token).
void finalizeChatStreamOnStop(
  List<Map<String, dynamic>> messages, {
  required String cancelledText,
  required String raw,
}) {
  final index = indexOfStreamingAi(messages);
  if (index != null) {
    final msg = messages[index];
    msg['streaming'] = false;
    final existing = (msg['text'] as String?)?.trim() ?? '';
    if (raw.trim().isEmpty && existing.isEmpty) {
      msg['localKey'] = 'responseCancelled';
      msg['text'] = cancelledText;
    }
    return;
  }
  if (messages.isNotEmpty && messages.last['role'] == 'ai') {
    messages.last['streaming'] = false;
    return;
  }
  messages.add({
    'role': 'ai',
    'localKey': 'responseCancelled',
    'text': cancelledText,
  });
}

/// Writes the finished answer into the live bubble. Returns false when that
/// bubble is already gone (stopped), so the caller must not add another.
bool completeChatStreamAnswer(
  List<Map<String, dynamic>> messages, {
  required String answer,
  List<String> sources = const [],
  dynamic messageId,
}) {
  final index = indexOfStreamingAi(messages);
  if (index == null) return false;
  final msg = messages[index];
  msg['text'] = answer;
  msg['streaming'] = false;
  msg['sources'] = List<String>.from(sources);
  msg['reported'] = false;
  if (messageId != null) msg['message_id'] = messageId;
  return true;
}
