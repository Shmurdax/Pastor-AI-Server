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
  final List<String> tags;
  /// True when a playable file is wired up; false for coming-soon placeholders.
  final bool isPublished;

  bool get isPlayable => isPublished && videoAssetPath != null;

  bool get isLocked => accessTier == MediaAccessTier.premium && !isPlayable;
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
