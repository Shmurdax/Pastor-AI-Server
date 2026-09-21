import 'package:flutter/material.dart';
import 'package:flutter_application_1/sermon_sources.dart';
import 'package:google_fonts/google_fonts.dart';

const _gold = Color(0xFFD4AF37);

/// One sermon-source row in the left sidebar library.
///
/// Hover is stored on [State] so parent rebuilds (chat history polling) do not
/// clear the highlight while the pointer is still on the row.
class SermonSourceLink extends StatefulWidget {
  const SermonSourceLink({
    super.key,
    required this.title,
    required this.onTap,
  });

  final String title;
  final VoidCallback onTap;

  @override
  State<SermonSourceLink> createState() => SermonSourceLinkState();
}

class SermonSourceLinkState extends State<SermonSourceLink> {
  bool _hovered = false;

  @visibleForTesting
  bool get hovered => _hovered;

  void _setHovered(bool value) {
    if (_hovered == value) return;
    setState(() => _hovered = value);
  }

  @override
  Widget build(BuildContext context) {
    return MouseRegion(
      cursor: SystemMouseCursors.click,
      onEnter: (_) => _setHovered(true),
      onHover: (_) => _setHovered(true),
      onExit: (_) => _setHovered(false),
      child: AnimatedContainer(
        key: const ValueKey('sermonSourceHover'),
        duration: _hovered ? const Duration(milliseconds: 250) : Duration.zero,
        curve: _hovered ? Curves.easeOut : Curves.linear,
        margin: const EdgeInsets.symmetric(vertical: 4.0, horizontal: 12.0),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(20),
          color: _hovered ? Colors.white.withValues(alpha: 0.07) : Colors.transparent,
          boxShadow: _hovered
              ? [
                  BoxShadow(
                    color: Colors.black.withValues(alpha: 0.2),
                    blurRadius: 15,
                    offset: const Offset(0, 6),
                    spreadRadius: -4,
                  ),
                ]
              : const [],
        ),
        child: Transform.translate(
          offset: _hovered ? const Offset(0, -3) : Offset.zero,
          filterQuality: FilterQuality.low,
          transformHitTests: false,
          child: Material(
            color: Colors.transparent,
            child: InkWell(
              borderRadius: BorderRadius.circular(20),
              hoverColor: Colors.transparent,
              overlayColor: const WidgetStatePropertyAll(Colors.transparent),
              onTap: widget.onTap,
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 12.0, horizontal: 16.0),
                child: Row(
                  children: [
                    Icon(
                      isVideoSermonSource(widget.title)
                          ? Icons.videocam_outlined
                          : Icons.description_outlined,
                      color: _gold,
                      size: 18,
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        widget.title,
                        style: GoogleFonts.figtree(
                          color: Colors.white,
                          fontSize: 14,
                          fontWeight: FontWeight.w400,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
