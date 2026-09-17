import 'dart:typed_data';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';

import 'pdf_viewer_stub.dart'
    if (dart.library.html) 'pdf_viewer_web.dart' as pdf_impl;

/// Renders PDF bytes in an iframe on web (toolbar hidden).
class PdfViewerEmbed extends StatelessWidget {
  const PdfViewerEmbed({
    super.key,
    required this.bytes,
    required this.viewKey,
  });

  final Uint8List bytes;
  final String viewKey;

  @override
  Widget build(BuildContext context) {
    if (!kIsWeb) {
      return const Center(
        child: Text(
          'PDF viewing is available on web.',
          textAlign: TextAlign.center,
        ),
      );
    }
    return pdf_impl.buildPdfViewer(bytes: bytes, viewKey: viewKey);
  }
}

void downloadPdfBytes(Uint8List bytes, String filename) {
  pdf_impl.downloadPdfBytes(bytes, filename);
}
