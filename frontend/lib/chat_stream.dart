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
