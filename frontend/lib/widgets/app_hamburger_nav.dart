import 'package:flutter/material.dart';
import 'package:flutter_application_1/l10n/app_locale.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';

const _navy = Color(0xFF1B264F);

/// Compact replacement for the top-right Home / Chat / Events / Media
/// row on viewports narrower than 1024px.
class AppHamburgerNav extends StatelessWidget {
  const AppHamburgerNav({
    super.key,
    required this.onHome,
    required this.onChat,
    required this.onEvents,
    required this.onMedia,
    this.dense = false,
  });

  final VoidCallback onHome;
  final VoidCallback onChat;
  final VoidCallback onEvents;
  final VoidCallback onMedia;
  final bool dense;

  @override
  Widget build(BuildContext context) {
    final s = context.watch<LocaleController>().strings;

    return Padding(
      padding: dense
          ? const EdgeInsets.only(right: 4)
          : const EdgeInsets.only(right: 8),
      child: MenuAnchor(
        alignmentOffset: const Offset(0, 8),
        style: MenuStyle(
          backgroundColor: WidgetStateProperty.all(Colors.white),
          elevation: WidgetStateProperty.all(8),
          shadowColor: WidgetStateProperty.all(Colors.black26),
          shape: WidgetStateProperty.all(
            RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(12),
              side: BorderSide(color: _navy.withValues(alpha: 0.08)),
            ),
          ),
          padding: WidgetStateProperty.all(
            const EdgeInsets.symmetric(vertical: 8),
          ),
        ),
        menuChildren: [
          _MenuRow(label: s.home, icon: Icons.home_outlined, onPressed: onHome),
          _MenuRow(label: s.chat, icon: Icons.chat_bubble_outline, onPressed: onChat),
          _MenuRow(label: s.events, icon: Icons.event_outlined, onPressed: onEvents),
          _MenuRow(label: s.media, icon: Icons.video_library_outlined, onPressed: onMedia),
        ],
        builder: (context, controller, child) {
          return IconButton(
            tooltip: MaterialLocalizations.of(context).openAppDrawerTooltip,
            icon: const Icon(Icons.menu, color: _navy),
            onPressed: () {
              if (controller.isOpen) {
                controller.close();
              } else {
                controller.open();
              }
            },
          );
        },
      ),
    );
  }
}

class _MenuRow extends StatelessWidget {
  const _MenuRow({
    required this.label,
    required this.icon,
    required this.onPressed,
  });

  final String label;
  final IconData icon;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return MenuItemButton(
      onPressed: onPressed,
      leadingIcon: Icon(icon, color: _navy, size: 20),
      child: Text(
        label,
        style: GoogleFonts.figtree(
          color: _navy,
          fontWeight: FontWeight.w600,
          fontSize: 15,
        ),
      ),
    );
  }
}
