// ignore_for_file: avoid_web_libraries_in_flutter, deprecated_member_use

import 'dart:html' as html;
import 'dart:ui_web' as ui_web;

import 'package:flutter/widgets.dart';

import 'vimeo_player_src.dart';

final Set<String> _registeredVimeoViews = <String>{};

/// Iframes `player.vimeo.com` directly, matching admin sermon-sources embeds.
Widget buildVimeoPlayer(
  String vimeoId, {
  String? privacyHash,
  int? startSeconds,
}) {
  final src = vimeoPlayerSrc(
    vimeoId,
    privacyHash: privacyHash,
    startSeconds: startSeconds,
  );
  final hash = (privacyHash ?? '').trim();
  final seekKey = (startSeconds != null && startSeconds >= 0)
      ? '-t$startSeconds'
      : '';
  final viewType = hash.isEmpty
      ? 'vimeo-direct-$vimeoId$seekKey'
      : 'vimeo-direct-$vimeoId-$hash$seekKey';
  if (!_registeredVimeoViews.contains(viewType)) {
    ui_web.platformViewRegistry.registerViewFactory(viewType, (int viewId) {
      final iframe = html.IFrameElement()
        ..src = src
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
