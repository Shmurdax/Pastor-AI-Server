// ignore_for_file: avoid_web_libraries_in_flutter, deprecated_member_use

import 'dart:html' as html;
import 'dart:ui_web' as ui_web;

import 'package:flutter/widgets.dart';

final Set<String> _registeredVimeoViews = <String>{};

/// Loads Vimeo through a same-origin relay page (`/vimeo_embed.html`) so the
/// player receives a real localhost/site referrer for domain privacy checks.
Widget buildVimeoPlayer(String vimeoId, {String? privacyHash}) {
  final hash = (privacyHash ?? '').trim();
  final viewType = hash.isEmpty ? 'vimeo-relay-$vimeoId' : 'vimeo-relay-$vimeoId-$hash';
  if (!_registeredVimeoViews.contains(viewType)) {
    ui_web.platformViewRegistry.registerViewFactory(viewType, (int viewId) {
      final qp = StringBuffer('id=${Uri.encodeQueryComponent(vimeoId)}');
      if (hash.isNotEmpty) {
        qp.write('&h=${Uri.encodeQueryComponent(hash)}');
      }
      final iframe = html.IFrameElement()
        ..src = '/vimeo_embed.html?$qp'
        ..style.border = 'none'
        ..style.width = '100%'
        ..style.height = '100%'
        ..allow =
            'autoplay; fullscreen; picture-in-picture; clipboard-write; encrypted-media; web-share'
        ..allowFullscreen = true
        ..referrerPolicy = 'strict-origin-when-cross-origin';
      return iframe;
    });
    _registeredVimeoViews.add(viewType);
  }
  return HtmlElementView(viewType: viewType);
}
