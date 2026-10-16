import 'package:flutter/material.dart';

/// Non-web stand-in. The promo file is served with the web build.
Widget buildLandingVideo({required String src}) {
  return Center(
    child: Icon(
      Icons.play_circle_fill,
      key: ValueKey<String>(src),
      color: const Color(0xFFD4AF37),
      size: 72,
    ),
  );
}
