class ChurchEventItem {
  const ChurchEventItem({
    required this.id,
    required this.title,
    required this.description,
    required this.location,
    required this.hostName,
    required this.startsAt,
    this.endsAt,
    required this.isPublished,
  });

  final int id;
  final String title;
  final String description;
  final String location;
  final String hostName;
  final DateTime startsAt;
  final DateTime? endsAt;
  final bool isPublished;

  factory ChurchEventItem.fromJson(Map<String, dynamic> json) {
    return ChurchEventItem(
      id: json['id'] as int,
      title: json['title'] as String? ?? '',
      description: json['description'] as String? ?? '',
      location: json['location'] as String? ?? '',
      hostName: json['host_name'] as String? ?? '',
      startsAt: DateTime.parse(json['starts_at'] as String).toLocal(),
      endsAt: json['ends_at'] != null ? DateTime.tryParse(json['ends_at'] as String)?.toLocal() : null,
      isPublished: json['is_published'] as bool? ?? true,
    );
  }

  Map<String, dynamic> toWriteJson() => {
        'title': title,
        'description': description,
        'location': location,
        'host_name': hostName,
        'starts_at': startsAt.toUtc().toIso8601String(),
        if (endsAt != null) 'ends_at': endsAt!.toUtc().toIso8601String(),
        'is_published': isPublished,
      };
}
