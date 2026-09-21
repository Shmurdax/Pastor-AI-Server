// ignore_for_file: avoid_web_libraries_in_flutter, deprecated_member_use

import 'dart:html' as html;
import 'dart:typed_data';

class NewTabDelegate {
  NewTabDelegate(this._window);

  html.WindowBase? _window;

  bool get isOpen => _window != null;

  void openUrl(String url) {
    final win = _window;
    if (win == null) {
      html.window.open(url, '_blank');
      return;
    }
    win.location.href = url;
  }

  void openPdfBytes(Uint8List bytes) {
    final blob = html.Blob(<dynamic>[bytes], 'application/pdf');
    final url = html.Url.createObjectUrlFromBlob(blob);
    openUrl(url);
  }

  void close() {
    _window?.close();
    _window = null;
  }
}

NewTabDelegate createNewTab() => NewTabDelegate(html.window.open('', '_blank'));
