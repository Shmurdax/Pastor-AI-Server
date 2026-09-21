import 'package:flutter/material.dart';

/// Copy / regenerate / report control under an AI chat bubble.
///
/// Hover is stored on [State] so parent rebuilds (chat history polling) do not
/// clear the highlight while the pointer is still on the button.
class ChatResponseActionButton extends StatefulWidget {
  const ChatResponseActionButton({
    super.key,
    required this.icon,
    required this.tooltip,
    required this.onTap,
  });

  final IconData icon;
  final String tooltip;
  final VoidCallback? onTap;

  @override
  State<ChatResponseActionButton> createState() => ChatResponseActionButtonState();
}

class ChatResponseActionButtonState extends State<ChatResponseActionButton> {
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
      cursor: widget.onTap == null
          ? SystemMouseCursors.basic
          : SystemMouseCursors.click,
      onEnter: (_) => _setHovered(true),
      onHover: (_) => _setHovered(true),
      onExit: (_) => _setHovered(false),
      child: Tooltip(
        message: widget.tooltip,
        waitDuration: const Duration(milliseconds: 500),
        ignorePointer: true,
        child: AnimatedContainer(
          key: const ValueKey('chatResponseActionHover'),
          duration: _hovered ? const Duration(milliseconds: 150) : Duration.zero,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(8),
            boxShadow: _hovered
                ? [
                    BoxShadow(
                      color: Colors.black.withValues(alpha: 0.15),
                      blurRadius: 6,
                      spreadRadius: 1,
                    ),
                  ]
                : const [],
          ),
          child: InkWell(
            onTap: widget.onTap,
            hoverColor: Colors.transparent,
            overlayColor: const WidgetStatePropertyAll(Colors.transparent),
            borderRadius: BorderRadius.circular(8),
            child: Padding(
              padding: const EdgeInsets.all(6.0),
              child: Icon(widget.icon, size: 18, color: Colors.black45),
            ),
          ),
        ),
      ),
    );
  }
}
