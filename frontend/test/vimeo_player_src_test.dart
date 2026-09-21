import 'package:flutter_application_1/models/media_item.dart';
import 'package:flutter_application_1/widgets/vimeo_player_src.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('matches sermon-sources embed URL with privacy hash', () {
    expect(
      vimeoPlayerSrc('1217796650', privacyHash: 'f7fb264484'),
      'https://player.vimeo.com/video/1217796650?h=f7fb264484&dnt=1',
    );
  });

  test('omits h when there is no privacy hash', () {
    expect(
      vimeoPlayerSrc('1217796650'),
      'https://player.vimeo.com/video/1217796650?dnt=1',
    );
  });

  test('appends Vimeo #t= seek fragment', () {
    expect(
      vimeoPlayerSrc('1217796650', privacyHash: 'abc', startSeconds: 530),
      'https://player.vimeo.com/video/1217796650?h=abc&dnt=1#t=530s',
    );
  });

  test('media catalog items open the Vimeo player URL', () {
    final item = MediaItem(
      id: '1',
      title: 'Morning Devotional',
      description: 'Daily word',
      publishedAt: DateTime(2026, 8, 1),
      contentType: MediaContentType.video,
      accessTier: MediaAccessTier.premium,
      vimeoId: '1217796650',
      vimeoPrivacyHash: 'f7fb264484',
      isPublished: true,
    );
    expect(
      mediaItemWatchUrl(item, startSeconds: 12),
      'https://player.vimeo.com/video/1217796650?h=f7fb264484&dnt=1#t=12s',
    );
  });

  test('items without a Vimeo id have no external watch URL', () {
    final item = MediaItem(
      id: 'asset',
      title: 'Preview',
      description: 'Local file',
      publishedAt: DateTime(2026, 8, 1),
      contentType: MediaContentType.video,
      accessTier: MediaAccessTier.freePreview,
      videoAssetPath: 'assets/videos/sample-5s.mp4',
      isPublished: true,
    );
    expect(mediaItemWatchUrl(item), isNull);
  });
}
