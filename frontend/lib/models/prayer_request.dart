class PrayerRequestItem {
  const PrayerRequestItem({
    required this.id,
    required this.name,
    required this.email,
    required this.phone,
    required this.prayerText,
    required this.isAnonymous,
    required this.createdAt,
    required this.followedUp,
    required this.pastorNotes,
    this.contactedAt,
    this.submitterUserEmail,
    this.submitterUserName,
  });

  final int id;
  final String name;
  final String email;
  final String phone;
  final String prayerText;
  final bool isAnonymous;
  final DateTime createdAt;
  final bool followedUp;
  final String pastorNotes;
  final DateTime? contactedAt;
  final String? submitterUserEmail;
  final String? submitterUserName;

  factory PrayerRequestItem.fromJson(Map<String, dynamic> json) {
    return PrayerRequestItem(
      id: json['id'] as int,
      name: json['name'] as String? ?? '',
      email: json['email'] as String? ?? '',
      phone: json['phone'] as String? ?? '',
      prayerText: json['prayer_text'] as String? ?? '',
      isAnonymous: json['is_anonymous'] as bool? ?? false,
      createdAt: DateTime.parse(json['created_at'] as String),
      followedUp: json['followed_up'] as bool? ?? false,
      pastorNotes: json['pastor_notes'] as String? ?? '',
      contactedAt: json['contacted_at'] != null
          ? DateTime.tryParse(json['contacted_at'] as String)
          : null,
      submitterUserEmail: json['submitter_user_email'] as String?,
      submitterUserName: json['submitter_user_name'] as String?,
    );
  }

  String get displayName {
    if (isAnonymous) return 'Anonymous';
    if (name.trim().isNotEmpty) return name.trim();
    if (email.trim().isNotEmpty) return email.trim();
    if (submitterUserName != null && submitterUserName!.trim().isNotEmpty) {
      return submitterUserName!.trim();
    }
    return 'Unknown';
  }

  String? get bestEmail {
    if (email.trim().isNotEmpty) return email.trim();
    if (submitterUserEmail != null && submitterUserEmail!.trim().isNotEmpty) {
      return submitterUserEmail!.trim();
    }
    return null;
  }

  String get preview {
    final flat = prayerText.replaceAll('\n', ' ').trim();
    if (flat.length <= 100) return flat;
    return '${flat.substring(0, 97)}...';
  }
}
