import 'package:flutter/material.dart';

import 'landing_video_stub.dart'
    if (dart.library.html) 'landing_video_web.dart' as landing_video_impl;

/// Same-origin path for the landing promo.
///
/// The file lives at `web/videos/landing.mp4` so `flutter build web` copies it
/// to `build/web/videos/landing.mp4`. It is too large to store in git.
const String landingVideoSrc = 'videos/landing.mp4';

/// Plays [landingVideoSrc] directly under the landing introduction.
class LandingVideo extends StatelessWidget {
  const LandingVideo({super.key});

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const Key('landing-video'),
      decoration: BoxDecoration(
        color: const Color(0xFF1B264F),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: const Color(0xFFD4AF37), width: 2),
        boxShadow: [
          BoxShadow(
            color: const Color(0xFF1B264F).withValues(alpha: 0.18),
            blurRadius: 24,
            offset: const Offset(0, 10),
          ),
        ],
      ),
      clipBehavior: Clip.antiAlias,
      child: AspectRatio(
        aspectRatio: 16 / 9,
        child: landing_video_impl.buildLandingVideo(src: landingVideoSrc),
      ),
    );
  }
}
