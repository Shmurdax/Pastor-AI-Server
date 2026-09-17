import 'package:flutter_application_1/models/ingested_document.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('fromJson maps view_only and file urls', () {
    final doc = IngestedDocumentItem.fromJson({
      'id': 12,
      'title': 'Book Transcript',
      'source_name': 'book.pdf',
      'source_kind': 'document',
      'view_only': true,
      'file_url': 'https://example.test/api/ingested-documents/12/file/',
    });
    expect(doc.id, 12);
    expect(doc.title, 'Book Transcript');
    expect(doc.viewOnly, isTrue);
    expect(doc.fileUrl, contains('/12/file/'));
  });

  test('parseIngestedDocuments skips invalid rows', () {
    final docs = parseIngestedDocuments({
      'documents': [
        {'id': 1, 'title': 'A', 'view_only': false},
        {'title': 'Missing id'},
        {'id': '2', 'title': 'B', 'view_only': true},
      ],
    });
    expect(docs.map((d) => d.id).toList(), [1, 2]);
    expect(docs.last.viewOnly, isTrue);
  });
}
