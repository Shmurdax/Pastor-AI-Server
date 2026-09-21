import 'dart:typed_data';

import 'new_tab_stub.dart' if (dart.library.html) 'new_tab_web.dart' as impl;

/// A browser tab reserved during a click so later async work can still open it.
class NewTabSession {
  NewTabSession._(this._delegate);

  final impl.NewTabDelegate _delegate;

  bool get isOpen => _delegate.isOpen;

  void openUrl(String url) => _delegate.openUrl(url);

  void openPdfBytes(Uint8List bytes) => _delegate.openPdfBytes(bytes);

  void close() => _delegate.close();
}

/// Opens a blank tab immediately. Call this before any `await` in a click handler.
NewTabSession openNewTab() => NewTabSession._(impl.createNewTab());
