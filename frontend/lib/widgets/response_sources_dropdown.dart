import 'package:flutter/material.dart';
import 'package:flutter_application_1/sermon_sources.dart';
import 'package:google_fonts/google_fonts.dart';

const _navy = Color(0xFF1B264F);

/// Per-response sermon sources control. Full bubble width on mobile; one-third
/// width and left-aligned on desktop so the title-to-chevron row stays compact.
class ResponseSourcesDropdown extends StatelessWidget {
  const ResponseSourcesDropdown({
    super.key,
    required this.sources,
    required this.isMobile,
    required this.title,
    required this.onSourceTap,
  });

  final List<String> sources;
  final bool isMobile;
  final String title;
  final ValueChanged<String> onSourceTap;

  @override
  Widget build(BuildContext context) {
    final dropdown = Theme(
      data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
      child: ExpansionTile(
        tilePadding: EdgeInsets.zero,
        childrenPadding: const EdgeInsets.only(bottom: 4),
        visualDensity: VisualDensity.compact,
        collapsedIconColor: _navy,
        iconColor: _navy,
        collapsedShape: const RoundedRectangleBorder(),
        shape: const RoundedRectangleBorder(),
        title: Text(
          title,
          style: GoogleFonts.figtree(
            fontSize: 14,
            fontWeight: FontWeight.w600,
            color: _navy,
          ),
        ),
        children: [
          for (final source in sources)
            ListTile(
              dense: true,
              minVerticalPadding: 10,
              contentPadding: const EdgeInsets.symmetric(horizontal: 4),
              leading: Icon(
                isVideoSermonSource(source) ? Icons.videocam_outlined : Icons.description_outlined,
                color: _navy,
                size: 20,
              ),
              title: Text(
                source,
                style: GoogleFonts.figtree(
                  fontSize: 14,
                  color: _navy,
                  decoration: TextDecoration.underline,
                  decorationColor: _navy.withValues(alpha: 0.35),
                ),
              ),
              onTap: () => onSourceTap(source),
            ),
        ],
      ),
    );

    if (isMobile) {
      return dropdown;
    }

    return Align(
      alignment: Alignment.centerLeft,
      child: FractionallySizedBox(
        widthFactor: 1 / 3,
        alignment: Alignment.centerLeft,
        child: dropdown,
      ),
    );
  }
}
