import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';

import 'vimeo_player_stub.dart'
    if (dart.library.html) 'vimeo_player_web.dart' as vimeo_impl;

/// Embeds a Vimeo player with the same `player.vimeo.com` iframe sermon sources use.
class VimeoPlayerEmbed extends StatelessWidget {
  const VimeoPlayerEmbed({
    super.key,
    required this.vimeoId,
    this.privacyHash,
  });

  final String vimeoId;
  final String? privacyHash;

  @override
  Widget build(BuildContext context) {
    if (!kIsWeb) {
      return Center(
        child: Text(
          'Vimeo playback is available on web.\nVideo id: $vimeoId',
          textAlign: TextAlign.center,
          style: const TextStyle(color: Colors.white70),
        ),
      );
    }
    return vimeo_impl.buildVimeoPlayer(vimeoId, privacyHash: privacyHash);
  }
}
