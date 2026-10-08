import 'package:flutter/material.dart';

/// How a topic chip should read. Plain keywords are stored in lowercase
/// (`babel`). A label that already has capitals, such as a hashtag, is left
/// as written.
String displayTopicLabel(String topic) {
  final trimmed = topic.trim().replaceFirst(RegExp(r'^#+'), '');
  if (trimmed.isEmpty || RegExp(r'[A-Z]').hasMatch(trimmed)) return trimmed;
  return trimmed.split(RegExp(r'\s+')).map((word) {
    if (word.isEmpty) return word;
    return word[0].toUpperCase() + word.substring(1);
  }).join(' ');
}

/// Words worth highlighting in a note. The full query comes first so a phrase
/// wins over its individual words at the same position.
List<String> highlightNeedles(String query) {
  final trimmed = query.trim();
  if (trimmed.isEmpty) return const [];
  final words = trimmed.split(RegExp(r'\s+')).where((word) => word.length >= 3).toList();
  if (words.length <= 1) return [trimmed];
  return [trimmed, ...words];
}

TextSpan highlightedNoteSpan({
  required String body,
  required String query,
  required TextStyle style,
  required TextStyle highlightStyle,
}) {
  final needles = highlightNeedles(query);
  if (body.isEmpty || needles.isEmpty) {
    return TextSpan(text: body, style: style);
  }
  final pattern = RegExp(needles.map(RegExp.escape).join('|'), caseSensitive: false);
  final spans = <TextSpan>[];
  var start = 0;
  for (final match in pattern.allMatches(body)) {
    if (match.start > start) {
      spans.add(TextSpan(text: body.substring(start, match.start), style: style));
    }
    spans.add(
      TextSpan(
        text: body.substring(match.start, match.end),
        style: highlightStyle,
      ),
    );
    start = match.end;
  }
  if (start < body.length) {
    spans.add(TextSpan(text: body.substring(start), style: style));
  }
  if (spans.isEmpty) {
    return TextSpan(text: body, style: style);
  }
  return TextSpan(style: style, children: spans);
}
