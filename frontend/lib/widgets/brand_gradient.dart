import 'package:flutter/material.dart';

const brandPink = Color(0xFFa1375a);
const brandNavy = Color(0xFF1B264F);

/// Red / purple brand wash used on CTAs, chat bubbles, and staff inbox headers.
/// Left-to-right so a short header still shows the red, not only navy.
const brandGradient = LinearGradient(
  colors: [brandPink, brandNavy],
  begin: Alignment.centerLeft,
  end: Alignment.centerRight,
);

PreferredSizeWidget brandGradientAppBar({
  required Widget title,
  List<Widget>? actions,
}) {
  return AppBar(
    backgroundColor: Colors.transparent,
    foregroundColor: Colors.white,
    elevation: 0,
    scrolledUnderElevation: 0,
    surfaceTintColor: Colors.transparent,
    forceMaterialTransparency: true,
    title: title,
    actions: actions,
    flexibleSpace: const SizedBox.expand(
      child: DecoratedBox(
        decoration: BoxDecoration(gradient: brandGradient),
      ),
    ),
  );
}

class BrandGradientFilledButton extends StatelessWidget {
  const BrandGradientFilledButton({
    super.key,
    required this.onPressed,
    required this.label,
    this.icon,
    this.padding = const EdgeInsets.symmetric(vertical: 14),
  });

  final VoidCallback? onPressed;
  final Widget label;
  final Widget? icon;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    final style = FilledButton.styleFrom(
      backgroundColor: Colors.transparent,
      disabledBackgroundColor: Colors.transparent,
      shadowColor: Colors.transparent,
      foregroundColor: Colors.white,
      padding: padding,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
    );
    return DecoratedBox(
      decoration: BoxDecoration(
        gradient: brandGradient,
        borderRadius: BorderRadius.circular(12),
      ),
      child: icon == null
          ? FilledButton(
              onPressed: onPressed,
              style: style,
              child: label,
            )
          : FilledButton.icon(
              onPressed: onPressed,
              icon: icon!,
              label: label,
              style: style,
            ),
    );
  }
}
