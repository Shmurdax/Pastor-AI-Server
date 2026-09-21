import 'dart:typed_data';

class NewTabDelegate {
  bool isOpen = true;

  void openUrl(String url) {
    isOpen = url.isNotEmpty;
  }

  void openPdfBytes(Uint8List bytes) {
    isOpen = bytes.isNotEmpty;
  }

  void close() {
    isOpen = false;
  }
}

NewTabDelegate createNewTab() => NewTabDelegate();
