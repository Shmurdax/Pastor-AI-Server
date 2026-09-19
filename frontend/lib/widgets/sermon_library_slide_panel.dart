import 'package:flutter/material.dart';
import 'package:flutter_application_1/widgets/brand_gradient.dart';

const _gold = Color(0xFFD4AF37);

/// Peeking sermon-library panel for phone/tablet. A gradient handle stays
/// attached to the panel's trailing edge so it can be tapped or dragged open;
/// the gold arrow flips when the library is showing.
class SermonLibrarySlidePanel extends StatelessWidget {
  const SermonLibrarySlidePanel({
    super.key,
    required this.animation,
    required this.panelWidth,
    required this.panel,
    required this.openTooltip,
    required this.closeTooltip,
  });

  static const handleKey = Key('sermon-library-handle');
  static const handleWidth = 40.0;
  static const handleHeight = 96.0;
  static const handleRadius = 12.0;
  static const _flingVelocity = 280.0;

  final AnimationController animation;
  final double panelWidth;
  final Widget panel;
  final String openTooltip;
  final String closeTooltip;

  bool get _isOpen => animation.value >= 0.5;

  void _toggle() {
    if (_isOpen) {
      animation.reverse();
    } else {
      animation.forward();
    }
  }

  void _onDragUpdate(DragUpdateDetails details) {
    final delta = details.primaryDelta ?? 0;
    if (panelWidth <= 0) return;
    animation.value = (animation.value + delta / panelWidth).clamp(0.0, 1.0);
  }

  void _onDragEnd(DragEndDetails details) {
    final velocity = details.primaryVelocity ?? 0;
    if (velocity.abs() > _flingVelocity) {
      if (velocity > 0) {
        animation.forward();
      } else {
        animation.reverse();
      }
      return;
    }
    if (animation.value >= 0.5) {
      animation.forward();
    } else {
      animation.reverse();
    }
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox.expand(
      child: AnimatedBuilder(
        animation: animation,
        builder: (context, child) {
          final progress = animation.value;
          final isOpen = progress >= 0.5;
          return Stack(
            clipBehavior: Clip.none,
            children: [
              if (progress > 0.001)
                Positioned.fill(
                  child: GestureDetector(
                    onTap: animation.reverse,
                    child: ColoredBox(
                      color: Colors.black.withValues(alpha: 0.45 * progress),
                    ),
                  ),
                ),
              Positioned(
                left: -panelWidth * (1 - progress),
                top: 0,
                bottom: 0,
                width: panelWidth + handleWidth + 12,
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    IgnorePointer(
                      ignoring: progress <= 0.001,
                      child: SizedBox(
                        width: panelWidth,
                        height: double.infinity,
                        child: child,
                      ),
                    ),
                    _LibraryHandle(
                      isOpen: isOpen,
                      tooltip: isOpen ? closeTooltip : openTooltip,
                      onTap: _toggle,
                      onDragUpdate: _onDragUpdate,
                      onDragEnd: _onDragEnd,
                    ),
                  ],
                ),
              ),
            ],
          );
        },
        child: Material(
          color: Colors.transparent,
          child: panel,
        ),
      ),
    );
  }
}

class _LibraryHandle extends StatelessWidget {
  const _LibraryHandle({
    required this.isOpen,
    required this.tooltip,
    required this.onTap,
    required this.onDragUpdate,
    required this.onDragEnd,
  });

  final bool isOpen;
  final String tooltip;
  final VoidCallback onTap;
  final GestureDragUpdateCallback onDragUpdate;
  final GestureDragEndCallback onDragEnd;

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: tooltip,
      child: GestureDetector(
        key: SermonLibrarySlidePanel.handleKey,
        behavior: HitTestBehavior.opaque,
        onTap: onTap,
        onHorizontalDragUpdate: onDragUpdate,
        onHorizontalDragEnd: onDragEnd,
        child: MouseRegion(
          cursor: SystemMouseCursors.click,
          child: Container(
            width: SermonLibrarySlidePanel.handleWidth,
            height: SermonLibrarySlidePanel.handleHeight,
            decoration: const BoxDecoration(
              gradient: brandGradient,
              borderRadius: BorderRadius.only(
                topRight: Radius.circular(SermonLibrarySlidePanel.handleRadius),
                bottomRight: Radius.circular(SermonLibrarySlidePanel.handleRadius),
              ),
              boxShadow: [
                BoxShadow(
                  color: Color(0x38000000),
                  blurRadius: 8,
                  offset: Offset(2, 1),
                ),
              ],
            ),
            child: Icon(
              isOpen ? Icons.arrow_back_rounded : Icons.arrow_forward_rounded,
              color: _gold,
              size: 26,
            ),
          ),
        ),
      ),
    );
  }
}
