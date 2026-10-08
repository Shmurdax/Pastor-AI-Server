import 'package:flutter/material.dart';

/// Topic chip text. Hashtags are shown exactly as written in the PDF, without
/// the leading `#`.
String displayTopicLabel(String topic) {
  var trimmed = topic.trim();
  while (trimmed.startsWith('#')) {
    trimmed = trimmed.substring(1).trimLeft();
  }
  return trimmed;
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
