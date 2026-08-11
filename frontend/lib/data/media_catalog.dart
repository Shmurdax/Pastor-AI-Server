import 'package:flutter_application_1/models/media_item.dart';

/// Placeholder catalog for the Daily Devotionals collection (video only).
/// Real video URLs/assets will replace entries when media is ingested.
class MediaCatalog {
  static const stats = MediaCatalogStats(
    totalPosts: 2414,
    memberCount: 138,
    startingPriceLabel: r'$15/month',
  );

  static const creatorTagline = 'Daily Devotionals from The NORDINS';

  /// Free intro shown to everyone; remaining items require Premium.
  static final List<MediaItem> allItems = [
    MediaItem(
      id: 'preview-welcome',
      title: 'Welcome to Media',
      description:
          'A short preview of the Daily Devotionals library. '
          'Full episodes unlock with Premium.',
      publishedAt: DateTime(2026, 8, 1),
      contentType: MediaContentType.video,
      accessTier: MediaAccessTier.freePreview,
      durationLabel: '0:05',
      videoAssetPath: 'assets/videos/sample-5s.mp4',
      tags: ['preview', 'welcome'],
      isPublished: true,
    ),
    MediaItem(
      id: 'placeholder-devotional-2026-1',
      title: 'Morning Devotional — Faith Over Fear',
      description: 'Daily encouragement with scripture and prayer.',
      publishedAt: DateTime(2026, 7, 28),
      contentType: MediaContentType.video,
      accessTier: MediaAccessTier.premium,
      durationLabel: '12:04',
      tags: ['devotional', 'faith'],
    ),
    MediaItem(
      id: 'placeholder-devotional-2025-1',
      title: 'Daily Word — Walking in Grace',
      description: 'Grace-focused devotional for supporters.',
      publishedAt: DateTime(2025, 11, 12),
      contentType: MediaContentType.video,
      accessTier: MediaAccessTier.premium,
      durationLabel: '10:05',
      tags: ['devotional', 'grace'],
    ),
    MediaItem(
      id: 'placeholder-devotional-2024-1',
      title: 'Morning Devotional — Strength for Today',
      description: 'Start the day with encouragement from the Word.',
      publishedAt: DateTime(2024, 6, 18),
      contentType: MediaContentType.video,
      accessTier: MediaAccessTier.premium,
      durationLabel: '11:20',
      tags: ['devotional', 'strength'],
    ),
    MediaItem(
      id: 'placeholder-devotional-2023-1',
      title: 'Daily Word — Hope in Hard Seasons',
      description: 'Finding hope when life feels heavy.',
      publishedAt: DateTime(2023, 9, 4),
      contentType: MediaContentType.video,
      accessTier: MediaAccessTier.premium,
      durationLabel: '13:40',
      tags: ['devotional', 'hope'],
    ),
    MediaItem(
      id: 'placeholder-devotional-2022-1',
      title: 'Morning Devotional — Trust His Timing',
      description: 'Waiting on the Lord with patience and faith.',
      publishedAt: DateTime(2022, 3, 21),
      contentType: MediaContentType.video,
      accessTier: MediaAccessTier.premium,
      durationLabel: '12:55',
      tags: ['devotional', 'trust'],
    ),
    MediaItem(
      id: 'placeholder-devotional-2021-1',
      title: 'Daily Word — Joy in the Journey',
      description: 'Choosing joy through every season of life.',
      publishedAt: DateTime(2021, 8, 9),
      contentType: MediaContentType.video,
      accessTier: MediaAccessTier.premium,
      durationLabel: '9:45',
      tags: ['devotional', 'joy'],
    ),
    MediaItem(
      id: 'placeholder-devotional-2020-1',
      title: 'Morning Devotional — Peace That Passes',
      description: 'Resting in the peace of Christ.',
      publishedAt: DateTime(2020, 5, 14),
      contentType: MediaContentType.video,
      accessTier: MediaAccessTier.premium,
      durationLabel: '11:10',
      tags: ['devotional', 'peace'],
    ),
    MediaItem(
      id: 'placeholder-devotional-2019-1',
      title: 'Daily Word — Abide in Him',
      description: 'Abiding in Christ day by day.',
      publishedAt: DateTime(2019, 2, 27),
      contentType: MediaContentType.video,
      accessTier: MediaAccessTier.premium,
      durationLabel: '10:30',
      tags: ['devotional', 'abide'],
    ),
  ];
}
