/// Helpers for chat sermon-source labels shown in the sidebar library.

final _videoTimestampSuffix = RegExp(
  r'\s*\[[0-9:]{4,8}[–-][0-9:]{4,8}\]\s*$',
);

const _documentExtensions = ['.md', '.docx', '.pdf'];

const _videoExtensions = [
  '.mp4',
  '.m4v',
  '.mov',
  '.avi',
  '.mkv',
  '.webm',
  '.wmv',
  '.flv',
  '.mpeg',
  '.mpg',
  '.3gp',
  '.ogv',
];

bool _hasVideoExtension(String value) {
  final lower = value.toLowerCase();
  return _videoExtensions.any(lower.endsWith);
}

/// True for timestamped video chunks and video-file source names.
///
/// Chat labels videos as `Title [00:12–00:34]`. The sermon library uses the
/// same `[` cue for the videocam icon.
bool isVideoSermonSource(String title) {
  final value = title.trim();
  if (value.isEmpty) return false;
  if (_videoTimestampSuffix.hasMatch(value)) return true;
  if (_hasVideoExtension(value)) return true;
  return value.contains('[');
}

String normalizeSermonSourceLabel(String raw) {
  var value = raw.trim();
  for (final ext in [..._documentExtensions, ..._videoExtensions]) {
    if (value.toLowerCase().endsWith(ext)) {
      value = value.substring(0, value.length - ext.length).trim();
      break;
    }
  }
  return value;
}

List<String> parseSermonSources(
  dynamic raw, {
  bool includeVideos = true,
  int limit = 5,
}) {
  final seen = <String>{};
  final out = <String>[];
  for (final item in List<dynamic>.from(raw ?? const [])) {
    final original = item.toString().trim();
    if (original.isEmpty) continue;
    if (!includeVideos && isVideoSermonSource(original)) continue;
    final value = normalizeSermonSourceLabel(original);
    if (value.isEmpty) continue;
    if (!includeVideos && isVideoSermonSource(value)) continue;
    if (!seen.add(value)) continue;
    out.add(value);
    if (out.length >= limit) break;
  }
  return out;
}

List<String> librarySermonSources(dynamic raw) =>
    parseSermonSources(raw, includeVideos: false);

List<String> withoutVideoSermonSources(Iterable<String> titles) {
  return [
    for (final title in titles)
      if (title.trim().isNotEmpty && !isVideoSermonSource(title)) title,
  ];
}
