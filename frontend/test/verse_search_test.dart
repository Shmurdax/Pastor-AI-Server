import 'package:flutter_application_1/models/ingested_document.dart';
import 'package:flutter_application_1/verse_search.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  const hope = IngestedDocumentItem(
    id: 1,
    title: 'Hope In Christ',
    scriptureRefs: ['John 3:16', 'John 3:17'],
  );
  const book = IngestedDocumentItem(
    id: 2,
    title: 'Book Transcript',
    viewOnly: true,
  );
  const psalm = IngestedDocumentItem(
    id: 3,
    title: 'Shepherd Notes',
    scriptureRefs: ['Psalm 23:1-6'],
  );

  test('catalog sorts titles A to Z', () {
    final items = catalogDocuments([hope, book, psalm]);
    expect(items.map((d) => d.title).toList(), [
      'Book Transcript',
      'Hope In Christ',
      'Shepherd Notes',
    ]);
  });

  test('title search still filters by name', () {
    final items = catalogDocuments([hope, book, psalm], query: 'book');
    expect(items.map((d) => d.id).toList(), [2]);
  });

  test('verse search returns sermons that cite the verse', () {
    final items = catalogDocuments([hope, book, psalm], query: 'John 3:16');
    expect(items.map((d) => d.id).toList(), [1]);
  });

  test('verse range and chapter queries overlap stored refs', () {
    expect(
      catalogDocuments([hope, psalm], query: 'John 3:16-18').map((d) => d.id),
      [1],
    );
    expect(
      catalogDocuments([hope, psalm], query: 'Psalm 23').map((d) => d.id),
      [3],
    );
    expect(
      catalogDocuments([psalm], query: 'Psalm 23:4').map((d) => d.id),
      [3],
    );
  });

  test('mentionedVerseLabel uses the stored citation', () {
    expect(mentionedVerseLabel(hope, 'john 3:16'), 'John 3:16');
    expect(mentionedVerseLabel(book, 'hope'), isNull);
  });
}
