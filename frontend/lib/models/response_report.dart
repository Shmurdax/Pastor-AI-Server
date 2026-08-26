class ResponseReportItem {
  const ResponseReportItem({
    required this.id,
    required this.reason,
    required this.reasonLabel,
    required this.status,
    required this.statusLabel,
    required this.userQuerySnapshot,
    required this.aiResponseSnapshot,
    required this.details,
    required this.staffNotes,
    required this.createdAt,
    this.chatMessageId,
    this.reviewedAt,
    this.reporterEmail,
    this.reporterName,
  });

  final int id;
  final int? chatMessageId;
  final String reason;
  final String reasonLabel;
  final String status;
  final String statusLabel;
  final String userQuerySnapshot;
  final String aiResponseSnapshot;
  final String details;
  final String staffNotes;
  final DateTime createdAt;
  final DateTime? reviewedAt;
  final String? reporterEmail;
  final String? reporterName;

  factory ResponseReportItem.fromJson(Map<String, dynamic> json) {
    return ResponseReportItem(
      id: json['id'] as int,
      chatMessageId: json['chat_message_id'] as int?,
      reason: json['reason'] as String? ?? '',
      reasonLabel: json['reason_label'] as String? ?? (json['reason'] as String? ?? ''),
      status: json['status'] as String? ?? 'new',
      statusLabel: json['status_label'] as String? ?? (json['status'] as String? ?? ''),
      userQuerySnapshot: json['user_query_snapshot'] as String? ?? '',
      aiResponseSnapshot: json['ai_response_snapshot'] as String? ?? '',
      details: json['details'] as String? ?? '',
      staffNotes: json['staff_notes'] as String? ?? '',
      createdAt: DateTime.parse(json['created_at'] as String),
      reviewedAt: json['reviewed_at'] != null
          ? DateTime.tryParse(json['reviewed_at'] as String)
          : null,
      reporterEmail: json['reporter_email'] as String?,
      reporterName: json['reporter_name'] as String?,
    );
  }

  String get preview {
    final flat = aiResponseSnapshot.replaceAll('\n', ' ').trim();
    if (flat.length <= 100) return flat;
    return '${flat.substring(0, 97)}...';
  }

  String get reporterLabel {
    if (reporterName != null && reporterName!.trim().isNotEmpty) {
      return reporterName!.trim();
    }
    if (reporterEmail != null && reporterEmail!.trim().isNotEmpty) {
      return reporterEmail!.trim();
    }
    return 'Guest';
  }
}

class ReportReasonOption {
  const ReportReasonOption({required this.value, required this.label});
  final String value;
  final String label;
}

const kReportReasonOptions = <ReportReasonOption>[
  ReportReasonOption(value: 'inaccurate', label: 'Inaccurate information'),
  ReportReasonOption(value: 'off_topic', label: 'Off topic'),
  ReportReasonOption(value: 'harmful_unsafe', label: 'Harmful or unsafe'),
  ReportReasonOption(value: 'confusing', label: 'Confusing or unclear'),
  ReportReasonOption(value: 'other', label: 'Other'),
];
