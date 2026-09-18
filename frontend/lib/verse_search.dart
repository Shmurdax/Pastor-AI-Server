import 'package:flutter_application_1/models/ingested_document.dart';

class ScriptureRef {
  const ScriptureRef({
    required this.bookKey,
    required this.chapter,
    this.verseStart,
    this.verseEnd,
  });

  final String bookKey;
  final int chapter;
  final int? verseStart;
  final int? verseEnd;

  String get display {
    final book = displayBookName(bookKey);
    if (verseStart == null) return '$book $chapter';
    if (verseEnd != null && verseEnd != verseStart) {
      return '$book $chapter:$verseStart-$verseEnd';
    }
    return '$book $chapter:$verseStart';
  }
}

const _bookAliases = <String, String>{
  'psalms': 'psalm',
  'psalm': 'psalm',
  'song of songs': 'song of solomon',
  'song of solomon': 'song of solomon',
};

const _bibleBooks = <String>[
  'song of solomon',
  'song of songs',
  '1 corinthians',
  '2 corinthians',
  '1 thessalonians',
  '2 thessalonians',
  '1 timothy',
  '2 timothy',
  '1 peter',
  '2 peter',
  '1 john',
  '2 john',
  '3 john',
  '1 samuel',
  '2 samuel',
  '1 kings',
  '2 kings',
  '1 chronicles',
  '2 chronicles',
  'genesis',
  'exodus',
  'leviticus',
  'numbers',
  'deuteronomy',
  'joshua',
  'judges',
  'ruth',
  'ezra',
  'nehemiah',
  'esther',
  'job',
  'psalms',
  'psalm',
  'proverbs',
  'ecclesiastes',
  'isaiah',
  'jeremiah',
  'lamentations',
  'ezekiel',
  'daniel',
  'hosea',
  'joel',
  'amos',
  'obadiah',
  'jonah',
  'micah',
  'nahum',
  'habakkuk',
  'zephaniah',
  'haggai',
  'zechariah',
  'malachi',
  'matthew',
  'mark',
  'luke',
  'john',
  'acts',
  'romans',
  'galatians',
  'ephesians',
  'philippians',
  'colossians',
  'titus',
  'philemon',
  'hebrews',
  'james',
  'jude',
  'revelation',
];

final _bookPattern = _bibleBooks.map(RegExp.escape).join('|');

final _verseRefRe = RegExp(
  '\\b($_bookPattern)\\s+(\\d+):(\\d+)(?:\\s*[-–]\\s*(\\d+))?',
  caseSensitive: false,
);

final _chapterRefRe = RegExp(
  '\\b($_bookPattern)\\s+(\\d+)(?!:)',
  caseSensitive: false,
);

String canonicalBookKey(String name) {
  var key = name.trim().toLowerCase().replaceAll(RegExp(r'\s+'), ' ');
  key = key.replaceFirstMapped(
    RegExp(r'^(\d)(?:st|nd|rd|th)\s+'),
    (match) => '${match[1]} ',
  );
  key = key.replaceFirstMapped(RegExp(r'^iii\s+'), (_) => '3 ');
  key = key.replaceFirstMapped(RegExp(r'^ii\s+'), (_) => '2 ');
  key = key.replaceFirstMapped(RegExp(r'^i\s+'), (_) => '1 ');
  return _bookAliases[key] ?? key;
}

String displayBookName(String name) {
  final key = canonicalBookKey(name);
  if (key == 'psalm') return 'Psalm';
  if (key == 'song of solomon') return 'Song of Solomon';
  return key
      .split(' ')
      .map((part) => part.isEmpty ? part : '${part[0].toUpperCase()}${part.substring(1)}')
      .join(' ');
}

List<ScriptureRef> parseScriptureQuery(String text) {
  final found = <ScriptureRef>[];
  final seen = <String>{};
  final verseSpans = <int>{};

  void add(ScriptureRef ref) {
    final key =
        '${ref.bookKey}|${ref.chapter}|${ref.verseStart ?? ''}|${ref.verseEnd ?? ''}';
    if (!seen.add(key)) return;
    found.add(ref);
  }

  for (final match in _verseRefRe.allMatches(text)) {
    verseSpans.addAll([for (var i = match.start; i < match.end; i++) i]);
    final book = canonicalBookKey(match.group(1)!);
    final chapter = int.parse(match.group(2)!);
    final start = int.parse(match.group(3)!);
    final end = int.parse(match.group(4) ?? '$start');
    add(ScriptureRef(
      bookKey: book,
      chapter: chapter,
      verseStart: start,
      verseEnd: end < start ? start : end,
    ));
  }

  for (final match in _chapterRefRe.allMatches(text)) {
    if (verseSpans.contains(match.start)) continue;
    final book = canonicalBookKey(match.group(1)!);
    final chapter = int.parse(match.group(2)!);
    add(ScriptureRef(bookKey: book, chapter: chapter));
  }
  return found;
}

bool scriptureRefsOverlap(ScriptureRef query, ScriptureRef stored) {
  if (query.bookKey != stored.bookKey || query.chapter != stored.chapter) {
    return false;
  }
  if (query.verseStart == null || stored.verseStart == null) return true;
  final qStart = query.verseStart!;
  final qEnd = query.verseEnd ?? qStart;
  final sStart = stored.verseStart!;
  final sEnd = stored.verseEnd ?? sStart;
  return qStart <= sEnd && sStart <= qEnd;
}

bool documentMatchesCatalogQuery(IngestedDocumentItem doc, String query) {
  final needle = query.trim().toLowerCase();
  if (needle.isEmpty) return true;
  if (doc.title.toLowerCase().contains(needle) ||
      doc.sourceName.toLowerCase().contains(needle)) {
    return true;
  }
  final wanted = parseScriptureQuery(query);
  if (wanted.isEmpty) return false;
  final stored = [
    ...doc.scriptureRefs,
    doc.title,
    doc.sourceName,
  ].expand(parseScriptureQuery);
  return wanted.any(
    (queryRef) => stored.any((storedRef) => scriptureRefsOverlap(queryRef, storedRef)),
  );
}

String? mentionedVerseLabel(IngestedDocumentItem doc, String query) {
  final wanted = parseScriptureQuery(query);
  if (wanted.isEmpty) return null;
  final stored = [
    ...doc.scriptureRefs,
    doc.title,
    doc.sourceName,
  ].expand(parseScriptureQuery);
  for (final queryRef in wanted) {
    for (final storedRef in stored) {
      if (scriptureRefsOverlap(queryRef, storedRef)) {
        return storedRef.display;
      }
    }
  }
  return wanted.first.display;
}

List<IngestedDocumentItem> catalogDocuments(
  Iterable<IngestedDocumentItem> documents, {
  String query = '',
}) {
  final items = documents
      .where((doc) => documentMatchesCatalogQuery(doc, query))
      .toList();
  items.sort(
    (a, b) => a.title.toLowerCase().compareTo(b.title.toLowerCase()),
  );
  return items;
}
