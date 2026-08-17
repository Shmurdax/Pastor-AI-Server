import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/data/media_catalog.dart';
import 'package:flutter_application_1/models/media_item.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

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
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  test('premium media stays locked for free and guest accounts', () {
    final item = _premiumItem();
    expect(item.isLockedForUser(hasPremiumAccess: false), isTrue);
    expect(item.isPlayable, isTrue);
  });

  test('premium media unlocks for paid Premium and staff access', () {
    final item = _premiumItem();
    expect(item.isLockedForUser(hasPremiumAccess: true), isFalse);
  });

  test('paid subscription grants premium access even if isPremium is stale', () {
    final auth = AuthController();
    auth.user = const AuthUser(
      id: '1',
      email: 'premium@test.com',
      name: 'Premium User',
      isPremium: false,
      subscriptionStatus: 'active',
    );
    expect(auth.user!.isPaidPremium, isTrue);
    expect(auth.hasPremiumAccess, isTrue);
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
}
