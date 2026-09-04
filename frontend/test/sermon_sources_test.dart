import 'package:flutter_application_1/sermon_sources.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('isVideoSermonSource detects timestamped video chunks', () {
    expect(isVideoSermonSource('Hope In Christ [00:12–00:34]'), isTrue);
    expect(isVideoSermonSource('Sunday Gathering [01:01:01-01:02:10]'), isTrue);
    expect(isVideoSermonSource('clip.mp4'), isTrue);
    expect(isVideoSermonSource('clip.MOV'), isTrue);
    expect(isVideoSermonSource('Pregnant With a Promise'), isFalse);
    expect(isVideoSermonSource('Teaching Notes.pdf'), isFalse);
  });

  test('librarySermonSources drops videos and keeps document titles', () {
    final sources = librarySermonSources([
      'Hope In Christ [00:12–00:34]',
      'Pregnant With a Promise.pdf',
      'clip.mp4',
      'Faith That Moves Mountains',
      'Sunday Gathering [01:15–02:01]',
    ]);
    expect(sources, [
      'Pregnant With a Promise',
      'Faith That Moves Mountains',
    ]);
  });

  test('librarySermonSources fills document slots after skipping videos', () {
    final sources = librarySermonSources([
      'A.mp4',
      'B [00:01–00:05]',
      'Doc One.pdf',
      'C.mov',
      'Doc Two',
      'Doc Three',
      'Doc Four',
      'Doc Five',
      'Doc Six',
    ]);
    expect(sources, [
      'Doc One',
      'Doc Two',
      'Doc Three',
      'Doc Four',
      'Doc Five',
    ]);
  });

  test('parseSermonSources still includes videos for chat source lists', () {
    final sources = parseSermonSources([
      'Hope In Christ [00:12–00:34]',
      'Pregnant With a Promise.pdf',
    ]);
    expect(sources, [
      'Hope In Christ [00:12–00:34]',
      'Pregnant With a Promise',
    ]);
  });
}
