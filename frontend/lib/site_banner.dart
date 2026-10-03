/// Notice returned by `GET /api/site-banner/`.
class SiteBannerNotice {
  const SiteBannerNotice({required this.enabled, required this.message});

  final bool enabled;
  final String message;

  static const hidden = SiteBannerNotice(enabled: false, message: '');

  bool get isVisible => enabled && message.trim().isNotEmpty;

  factory SiteBannerNotice.fromJson(Object? data) {
    if (data is! Map) return hidden;
    final enabled = data['enabled'] == true;
    final message = (data['message'] as String?)?.trim() ?? '';
    if (!enabled || message.isEmpty) return hidden;
    return SiteBannerNotice(enabled: true, message: message);
  }

  @override
  bool operator ==(Object other) =>
      other is SiteBannerNotice &&
      other.enabled == enabled &&
      other.message == message;

  @override
  int get hashCode => Object.hash(enabled, message);
}
