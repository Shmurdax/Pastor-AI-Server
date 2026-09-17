class IngestedDocumentItem {
  const IngestedDocumentItem({
    required this.id,
    required this.title,
    this.sourceName = '',
    this.sourceKind = 'document',
    this.viewOnly = false,
    this.fileUrl = '',
    this.updatedAt,
  });

  final int id;
  final String title;
  final String sourceName;
  final String sourceKind;
  final bool viewOnly;
  final String fileUrl;
  final DateTime? updatedAt;

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
    );
  }
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
