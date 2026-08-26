enum MediaContentType { video, audio }

enum MediaAccessTier { freePreview, premium }

enum MediaSortOption {
  newestFirst('Newest first'),
  oldestFirst('Oldest first'),
  titleAZ('Title A–Z');

  const MediaSortOption(this.label);
  final String label;
}

class MediaItem {
  const MediaItem({
    required this.id,
    required this.title,
    required this.description,
    required this.publishedAt,
    required this.contentType,
    required this.accessTier,
    this.durationLabel,
    this.videoAssetPath,
    this.vimeoId,
    this.vimeoPrivacyHash,
    this.thumbnailUrl,
    this.tags = const [],
    this.isPublished = false,
  });

  final String id;
  final String title;
  final String description;
  final DateTime publishedAt;
  final MediaContentType contentType;
  final MediaAccessTier accessTier;
  final String? durationLabel;
  /// Local asset path when a preview file exists; null for catalog placeholders.
  final String? videoAssetPath;
  /// Vimeo video id for iframe embed playback.
  final String? vimeoId;
  /// Unlisted privacy hash (`h` query param) when present.
  final String? vimeoPrivacyHash;
  final String? thumbnailUrl;
  final List<String> tags;
  /// True when a playable file/embed is wired up; false for coming-soon placeholders.
  final bool isPublished;

  bool get isPlayable =>
      isPublished && (vimeoId != null || videoAssetPath != null);

  bool get isLocked => accessTier == MediaAccessTier.premium && !isPlayable;

  factory MediaItem.fromApiJson(Map<String, dynamic> json) {
    final tierRaw = (json['access_tier'] as String? ?? 'premium').toLowerCase();
    final tier = tierRaw == 'free_preview'
        ? MediaAccessTier.freePreview
        : MediaAccessTier.premium;
    final publishedRaw = json['published_at'] as String?;
    final publishedAt = publishedRaw != null
        ? DateTime.tryParse(publishedRaw)?.toLocal() ?? DateTime.now()
        : DateTime.now();
    final vimeoId = (json['vimeo_id'] as String?)?.trim();
    final hash = (json['privacy_hash'] as String?)?.trim();
    return MediaItem(
      id: '${json['id'] ?? vimeoId ?? ''}',
      title: json['title'] as String? ?? 'Untitled',
      description: json['description'] as String? ?? '',
      publishedAt: publishedAt,
      contentType: MediaContentType.video,
      accessTier: tier,
      durationLabel: json['duration_label'] as String?,
      vimeoId: (vimeoId == null || vimeoId.isEmpty) ? null : vimeoId,
      vimeoPrivacyHash: (hash == null || hash.isEmpty) ? null : hash,
      thumbnailUrl: (json['thumbnail_url'] as String?)?.trim(),
      isPublished: json['is_published'] as bool? ?? true,
      tags: const ['devotional'],
    );
  }
}

class MediaCatalogStats {
  const MediaCatalogStats({
    required this.totalPosts,
    required this.memberCount,
    required this.startingPriceLabel,
  });

  final int totalPosts;
  final int memberCount;
  final String startingPriceLabel;
}

/// Single collection label for all media library content.
const kMediaCollectionLabel = 'Daily Devotionals';
