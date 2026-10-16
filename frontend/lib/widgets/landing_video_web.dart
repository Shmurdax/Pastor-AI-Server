// ignore_for_file: avoid_web_libraries_in_flutter, deprecated_member_use

import 'dart:html' as html;
import 'dart:ui_web' as ui_web;

import 'package:flutter/widgets.dart';

const _viewType = 'nordin-landing-video';
bool _registered = false;

/// Native `<video>` so the browser can stream the large mp4 with range requests.
Widget buildLandingVideo({required String src}) {
  if (!_registered) {
    ui_web.platformViewRegistry.registerViewFactory(_viewType, (int viewId) {
      return html.VideoElement()
        ..src = src
        ..controls = true
        ..preload = 'metadata'
        ..title = "Nordin's AI"
        ..style.border = 'none'
        ..style.width = '100%'
        ..style.height = '100%'
        ..style.display = 'block'
        ..style.backgroundColor = '#1B264F'
        ..style.objectFit = 'contain'
        ..setAttribute('playsinline', 'true');
    });
    _registered = true;
  }
  return const HtmlElementView(viewType: _viewType);
}
