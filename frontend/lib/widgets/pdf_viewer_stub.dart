import 'dart:typed_data';

import 'package:flutter/widgets.dart';

Widget buildPdfViewer({
  required Uint8List bytes,
  required String viewKey,
}) {
  return const SizedBox.expand(
    child: Center(
      child: Text(
        'PDF viewing is available on web.',
        textAlign: TextAlign.center,
      ),
    ),
  );
}

void downloadPdfBytes(Uint8List bytes, String filename) {}
