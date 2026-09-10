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

  test('parseSermonSourceRef extracts stem and seek seconds', () {
    final ref = parseSermonSourceRef('June 30 [08:50–09:30]');
    expect(ref.displayStem, 'June 30');
    expect(ref.seekSeconds, 8 * 60 + 50);

    final long = parseSermonSourceRef('Sunday Gathering [01:01:01-01:02:10]');
    expect(long.displayStem, 'Sunday Gathering');
    expect(long.seekSeconds, 1 * 3600 + 1 * 60 + 1);

    final doc = parseSermonSourceRef('Pregnant With a Promise.pdf');
    expect(doc.displayStem, 'Pregnant With a Promise');
    expect(doc.seekSeconds, isNull);
  });

  test('appendMediaSeekFragment adds HTML5 media fragment', () {
    expect(
      appendMediaSeekFragment('https://example.com/a.mp4', 530),
      'https://example.com/a.mp4#t=530',
    );
    expect(
      appendMediaSeekFragment('https://example.com/a.mp4', null),
      'https://example.com/a.mp4',
    );
  });

  test('isVideoFileUrl uses source_kind and extension', () {
    expect(
      isVideoFileUrl('https://x/file.bin', sourceKind: 'video'),
      isTrue,
    );
    expect(isVideoFileUrl('https://x/clip.MP4'), isTrue);
    expect(isVideoFileUrl('https://x/notes.pdf'), isFalse);
  });
}
