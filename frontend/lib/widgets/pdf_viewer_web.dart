// ignore_for_file: avoid_web_libraries_in_flutter, deprecated_member_use

import 'dart:html' as html;
import 'dart:typed_data';
import 'dart:ui_web' as ui_web;

import 'package:flutter/widgets.dart';

final Set<String> _registeredPdfViews = <String>{};

Widget buildPdfViewer({
  required Uint8List bytes,
  required String viewKey,
}) {
  return _BlobPdfIframe(bytes: bytes, viewKey: viewKey);
}

void downloadPdfBytes(Uint8List bytes, String filename) {
  final blob = html.Blob(<dynamic>[bytes], 'application/pdf');
  final url = html.Url.createObjectUrlFromBlob(blob);
  html.AnchorElement(href: url)
    ..setAttribute('download', filename)
    ..click();
  html.Url.revokeObjectUrl(url);
}

class _BlobPdfIframe extends StatefulWidget {
  const _BlobPdfIframe({required this.bytes, required this.viewKey});

  final Uint8List bytes;
  final String viewKey;

  @override
  State<_BlobPdfIframe> createState() => _BlobPdfIframeState();
}

class _BlobPdfIframeState extends State<_BlobPdfIframe> {
  late final String _viewType;
  late final String _objectUrl;

  @override
  void initState() {
    super.initState();
    final blob = html.Blob(<dynamic>[widget.bytes], 'application/pdf');
    _objectUrl = html.Url.createObjectUrlFromBlob(blob);
    _viewType = 'pdf-view-${widget.viewKey}-${identityHashCode(this)}';
    if (!_registeredPdfViews.contains(_viewType)) {
      ui_web.platformViewRegistry.registerViewFactory(_viewType, (int viewId) {
        final iframe = html.IFrameElement()
          ..src = '$_objectUrl#toolbar=0&navpanes=0&scrollbar=1'
          ..style.border = 'none'
          ..style.width = '100%'
          ..style.height = '100%';
        iframe.onContextMenu.listen((html.MouseEvent event) {
          event.preventDefault();
        });
        return iframe;
      });
      _registeredPdfViews.add(_viewType);
    }
  }

  @override
  void dispose() {
    html.Url.revokeObjectUrl(_objectUrl);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return HtmlElementView(viewType: _viewType);
  }
}
