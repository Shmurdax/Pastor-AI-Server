import 'package:flutter_application_1/data/media_catalog.dart';
import 'package:flutter_application_1/models/media_item.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:flutter_test/flutter_test.dart';

MediaItem _premiumItem({bool published = true}) {
  return MediaItem(
    id: 'premium-1',
    title: 'Morning Devotional',
    description: 'Premium episode',
    publishedAt: DateTime(2026, 8, 1),
    contentType: MediaContentType.video,
    accessTier: MediaAccessTier.premium,
    videoAssetPath: published ? 'assets/videos/sample-5s.mp4' : null,
    isPublished: published,
  );
}

void main() {
  test('premium media stays locked for free and guest accounts', () {
    final item = _premiumItem();
    expect(item.isLockedForUser(hasPremiumAccess: false), isTrue);
    expect(item.isPlayable, isTrue);
  });

  test('premium media unlocks for paid Premium and staff access', () {
    final item = _premiumItem();
    expect(item.isLockedForUser(hasPremiumAccess: true), isFalse);
  });

  test('an active subscription is treated as paid Premium', () {
    const user = AuthUser(
      id: '1',
      email: 'premium@test.com',
      name: 'Premium User',
      isPremium: false,
      subscriptionStatus: 'active',
    );
    expect(user.isPaidPremium, isTrue);
    expect(user.isStaff, isFalse);
  });

  test('catalog premium devotionals are playable once unlocked', () {
    final premiumItems = MediaCatalog.allItems
        .where((item) => item.accessTier == MediaAccessTier.premium);
    expect(premiumItems, isNotEmpty);
    for (final item in premiumItems) {
      expect(item.isPlayable, isTrue, reason: '${item.id} should be playable');
      expect(item.isLockedForUser(hasPremiumAccess: true), isFalse);
      expect(item.isLockedForUser(hasPremiumAccess: false), isTrue);
    }
  });

  test('API Vimeo embeds are playable in the media catalog', () {
    final item = MediaItem.fromApiJson({
      'id': '403856658',
      'vimeo_id': '403856658',
      'privacy_hash': '6bce8bb9e6',
      'title': 'April 10',
      'description': '',
      'published_at': '2024-04-10T12:00:00Z',
      'duration_label': '12:04',
      'access_tier': 'premium',
      'is_published': true,
    });
    expect(item.vimeoId, '403856658');
    expect(item.vimeoPrivacyHash, '6bce8bb9e6');
    expect(item.isPlayable, isTrue);
    expect(item.isLockedForUser(hasPremiumAccess: true), isFalse);
    expect(item.isLockedForUser(hasPremiumAccess: false), isTrue);
  });
}
