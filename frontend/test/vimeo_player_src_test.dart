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
}
