/// Helpers for chat sermon-source labels shown in the sidebar library.

final _videoTimestampSuffix = RegExp(
  r'\s*\[[0-9:]{4,8}[–-][0-9:]{4,8}\]\s*$',
);

/// Captures `Title [mm:ss–mm:ss]` or `Title [hh:mm:ss–hh:mm:ss]` ranges.
final _videoTimestampRange = RegExp(
  r'^(.*?)\s*\[([0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?)[–-]([0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?)\]\s*$',
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

/// Parsed chat sermon-source label, including optional video seek time.
class SermonSourceRef {
  const SermonSourceRef({
    required this.displayStem,
    this.seekSeconds,
  });

  /// Filename / title stem used to look up the ingested file.
  final String displayStem;

  /// Start of a video timestamp range, when the label includes `[mm:ss–…]`.
  final int? seekSeconds;
}

/// Parse `mm:ss` / `hh:mm:ss` into whole seconds. Returns null when invalid.
int? parseClockTimestampToSeconds(String raw) {
  final parts = raw.trim().split(':');
  if (parts.length < 2 || parts.length > 3) return null;
  final nums = <int>[];
  for (final part in parts) {
    final value = int.tryParse(part);
    if (value == null || value < 0) return null;
    nums.add(value);
  }
  if (nums.length == 2) {
    final minutes = nums[0];
    final seconds = nums[1];
    if (seconds > 59) return null;
    return minutes * 60 + seconds;
  }
  final hours = nums[0];
  final minutes = nums[1];
  final seconds = nums[2];
  if (minutes > 59 || seconds > 59) return null;
  return hours * 3600 + minutes * 60 + seconds;
}

/// Split a chat source label into lookup stem + optional video seek offset.
SermonSourceRef parseSermonSourceRef(String sermonName) {
  var value = sermonName.trim();
  int? seekSeconds;
  final range = _videoTimestampRange.firstMatch(value);
  if (range != null) {
    value = range.group(1)!.trim();
    seekSeconds = parseClockTimestampToSeconds(range.group(2)!);
  } else {
    value = value.replaceFirst(_videoTimestampSuffix, '').trim();
  }
  value = normalizeSermonSourceLabel(value);
  return SermonSourceRef(displayStem: value, seekSeconds: seekSeconds);
}

/// Append an HTML5 media fragment (`#t=seconds`) for browser video seek.
String appendMediaSeekFragment(String url, int? seekSeconds) {
  if (seekSeconds == null || seekSeconds < 0) return url;
  final uri = Uri.tryParse(url);
  if (uri == null || !uri.hasScheme) {
    final withoutFragment = url.split('#').first;
    return '$withoutFragment#t=$seekSeconds';
  }
  return uri.replace(fragment: 't=$seekSeconds').toString();
}

bool isVideoFileUrl(String url, {String? sourceKind}) {
  if ((sourceKind ?? '').toLowerCase() == 'video') return true;
  final path = (Uri.tryParse(url)?.path ?? url).toLowerCase();
  return _hasVideoExtension(path);
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
