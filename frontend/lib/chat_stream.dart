import 'dart:convert';

class ChatStreamEvent {
  const ChatStreamEvent({
    required this.type,
    this.text = '',
    this.answer = '',
    this.sources = const [],
    this.messageId,
    this.error = '',
  });

  final String type;
  final String text;
  final String answer;
  final List<String> sources;
  final dynamic messageId;
  final String error;

  bool get isDelta => type == 'delta';
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
      messageId: json['message_id'],
      error: json['error']?.toString() ?? '',
    );
  }
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
/// call this — they would open a second bubble.
void applyChatStreamDelta(List<Map<String, dynamic>> messages, String display) {
  final index = indexOfStreamingAi(messages);
  if (index != null) {
    messages[index]['text'] = display;
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
  messages.add({
    'role': 'ai',
    'localKey': 'responseCancelled',
    'text': cancelledText,
  });
}
