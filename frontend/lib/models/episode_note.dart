/// Study notes linked to one Walk through the Word episode.
class EpisodeNoteSummary {
  const EpisodeNoteSummary({
    required this.id,
    required this.episodeDate,
    this.topics = const [],
    this.hasNotes = true,
    this.snippet,
  });

  final int id;
  final String episodeDate;
  final List<String> topics;
  final bool hasNotes;
  final String? snippet;

  bool get showNotes => hasNotes && id > 0;

  static EpisodeNoteSummary? tryParse(Object? raw) {
    if (raw is! Map) return null;
    final note = EpisodeNoteSummary.fromJson(Map<String, dynamic>.from(raw));
    if (!note.showNotes) return null;
    return note;
  }

  factory EpisodeNoteSummary.fromJson(Map<String, dynamic> json) {
    final topics = <String>[];
    final topicsRaw = json['topics'];
    if (topicsRaw is List) {
      for (final item in topicsRaw) {
        final label = item?.toString().trim() ?? '';
        if (label.isNotEmpty) topics.add(label);
      }
    }
    final snippet = (json['snippet'] as String?)?.trim();
    return EpisodeNoteSummary(
      id: (json['id'] as num?)?.toInt() ?? 0,
      episodeDate: json['episode_date'] as String? ?? '',
      topics: topics,
      hasNotes: json['has_notes'] != false,
      snippet: (snippet == null || snippet.isEmpty) ? null : snippet,
    );
  }
}

class EpisodeNoteDetail {
  const EpisodeNoteDetail({
    required this.id,
    required this.episodeDate,
    required this.body,
    required this.originalFilename,
    this.topics = const [],
  });

  final int id;
  final String episodeDate;
  final String body;
  final String originalFilename;
  final List<String> topics;

  factory EpisodeNoteDetail.fromJson(Map<String, dynamic> json) {
    final summary = EpisodeNoteSummary.fromJson(json);
    return EpisodeNoteDetail(
      id: summary.id,
      episodeDate: summary.episodeDate,
      topics: summary.topics,
      body: json['body'] as String? ?? '',
      originalFilename: json['original_filename'] as String? ?? 'notes.pdf',
    );
  }
}
