import 'package:flutter/material.dart';
import 'package:flutter_application_1/l10n/app_locale.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';

const _navy = Color(0xFF1B264F);
const _gold = Color(0xFFD4AF37);

/// Top-nav "Nordin's AI" control with Chat / Media / Subscribe in a dropdown.
class NordinsAiNavMenu extends StatefulWidget {
  const NordinsAiNavMenu({
    super.key,
    required this.onAiHome,
    required this.onMedia,
    required this.onSubscribe,
    this.textColor = Colors.black,
    this.active = false,
  });

  final VoidCallback onAiHome;
  final VoidCallback onMedia;
  final VoidCallback onSubscribe;
  final Color textColor;
  final bool active;

  @override
  State<NordinsAiNavMenu> createState() => _NordinsAiNavMenuState();
}

class _NordinsAiNavMenuState extends State<NordinsAiNavMenu> {
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    final s = context.watch<LocaleController>().strings;

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 10.0),
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
          _MenuRow(
            label: s.chat,
            icon: Icons.chat_bubble_outline,
            onPressed: widget.onAiHome,
          ),
          _MenuRow(
            label: s.media,
            icon: Icons.video_library_outlined,
            onPressed: widget.onMedia,
          ),
          _MenuRow(
            label: s.subscribe,
            icon: Icons.workspace_premium_outlined,
            onPressed: widget.onSubscribe,
          ),
        ],
        builder: (context, controller, child) {
          final showUnderline = _hovered || widget.active || controller.isOpen;

          return MouseRegion(
            onEnter: (_) => setState(() => _hovered = true),
            onExit: (_) => setState(() => _hovered = false),
            cursor: SystemMouseCursors.click,
            child: GestureDetector(
              onTap: () {
                if (controller.isOpen) {
                  controller.close();
                } else {
                  controller.open();
                }
                setState(() {});
              },
              child: Stack(
                clipBehavior: Clip.none,
                children: [
                  Padding(
                    padding: const EdgeInsets.only(bottom: 6.0),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          s.nordinsAi,
                          style: TextStyle(
                            fontFamily: 'Times New Roman',
                            color: widget.textColor,
                            fontSize: 16,
                            fontWeight: FontWeight.w500,
                          ),
                        ),
                        const SizedBox(width: 2),
                        Icon(
                          controller.isOpen
                              ? Icons.keyboard_arrow_up
                              : Icons.keyboard_arrow_down,
                          size: 18,
                          color: widget.textColor,
                        ),
                      ],
                    ),
                  ),
                  Positioned(
                    bottom: 0,
                    left: 0,
                    right: 0,
                    child: Align(
                      alignment: Alignment.centerLeft,
                      child: AnimatedContainer(
                        duration: const Duration(milliseconds: 300),
                        curve: Curves.easeInOut,
                        height: 2,
                        width: showUnderline ? 200 : 0,
                        color: _gold,
                      ),
                    ),
                  ),
                ],
              ),
            ),
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
