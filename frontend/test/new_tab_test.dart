import 'dart:typed_data';

import 'package:flutter_application_1/widgets/new_tab.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('reserved tab can open a URL and a PDF blob', () {
    final tab = openNewTab();
    expect(tab.isOpen, isTrue);
    tab.openUrl('https://player.vimeo.com/video/1?dnt=1');
    expect(tab.isOpen, isTrue);
    tab.openPdfBytes(Uint8List.fromList('%PDF-1.4'.codeUnits));
    expect(tab.isOpen, isTrue);
    tab.close();
    expect(tab.isOpen, isFalse);
  });
}
