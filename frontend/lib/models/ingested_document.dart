class IngestedDocumentItem {
  const IngestedDocumentItem({
    required this.id,
    required this.title,
    this.sourceName = '',
    this.sourceKind = 'document',
    this.viewOnly = false,
    this.fileUrl = '',
    this.updatedAt,
    this.scriptureRefs = const [],
  });

  final int id;
  final String title;
  final String sourceName;
  final String sourceKind;
  final bool viewOnly;
  final String fileUrl;
  final DateTime? updatedAt;
  final List<String> scriptureRefs;

  factory IngestedDocumentItem.fromJson(Map<String, dynamic> json) {
    final idRaw = json['id'];
    final id = idRaw is int ? idRaw : int.tryParse('$idRaw') ?? 0;
    return IngestedDocumentItem(
      id: id,
      title: (json['title'] ?? json['source_name'] ?? '').toString().trim(),
      sourceName: (json['source_name'] ?? '').toString(),
      sourceKind: (json['source_kind'] ?? 'document').toString(),
      viewOnly: json['view_only'] == true,
      fileUrl: (json['file_url'] ?? json['file_path'] ?? '').toString(),
      updatedAt: DateTime.tryParse((json['updated_at'] ?? '').toString()),
      scriptureRefs: _scriptureRefsFromJson(json),
    );
  }
}

List<String> _scriptureRefsFromJson(Map<String, dynamic> json) {
  final out = <String>[];
  final seen = <String>{};
  void addAll(dynamic raw) {
    if (raw is! List) return;
    for (final item in raw) {
      final label = item?.toString().trim() ?? '';
      if (label.isEmpty) continue;
      if (!seen.add(label.toLowerCase())) continue;
      out.add(label);
    }
  }

  addAll(json['scripture_refs']);
  final meta = json['topic_metadata'];
  if (meta is Map) {
    addAll(meta['scripture_refs']);
  }
  return out;
}

List<IngestedDocumentItem> parseIngestedDocuments(dynamic data) {
  final raw = data is Map<String, dynamic> ? data['documents'] : data;
  final out = <IngestedDocumentItem>[];
  for (final item in List<dynamic>.from(raw ?? const [])) {
    if (item is! Map) continue;
    final doc = IngestedDocumentItem.fromJson(Map<String, dynamic>.from(item));
    if (doc.id <= 0) continue;
    out.add(doc);
  }
  return out;
}
