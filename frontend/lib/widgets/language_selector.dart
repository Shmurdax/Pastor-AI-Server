import 'package:flutter/material.dart';
import 'package:flutter_application_1/l10n/app_locale.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';

const _navy = Color(0xFF1B264F);
const _gold = Color(0xFFD4AF37);

/// Compact language picker for the display-page AppBar.
class LanguageSelector extends StatelessWidget {
  const LanguageSelector({
    super.key,
    this.isMobile = false,
    this.textColor = _navy,
  });

  final bool isMobile;
  final Color textColor;

  Future<void> _openPicker(BuildContext context) async {
    final locale = context.read<LocaleController>();
    final selected = await showDialog<String>(
      context: context,
      builder: (ctx) {
        return AlertDialog(
          title: Text(
            locale.strings.language,
            style: GoogleFonts.figtree(fontWeight: FontWeight.bold, color: _navy),
          ),
          content: SizedBox(
            width: 320,
            child: ListView(
              shrinkWrap: true,
              children: [
                for (final lang in kSupportedAppLanguages)
                  ListTile(
                    leading: Icon(
                      lang.code == locale.languageCode
                          ? Icons.check_circle
                          : Icons.circle_outlined,
                      color: lang.code == locale.languageCode ? _gold : _navy,
                    ),
                    title: Text(
                      lang.label,
                      style: GoogleFonts.figtree(
                        color: _navy,
                        fontWeight: lang.code == locale.languageCode
                            ? FontWeight.w700
                            : FontWeight.w500,
                      ),
                    ),
                    onTap: () => Navigator.of(ctx).pop(lang.code),
                  ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(),
              child: Text(locale.strings.cancel),
            ),
          ],
        );
      },
    );
    if (selected != null && context.mounted) {
      await locale.setLanguageCode(selected);
    }
  }

  @override
  Widget build(BuildContext context) {
    final locale = context.watch<LocaleController>();
    final s = locale.strings;

    return Padding(
      padding: EdgeInsets.only(
        top: isMobile ? 20 : 45,
        right: isMobile ? 4 : 8,
      ),
      child: Tooltip(
        message: s.language,
        child: Material(
          color: Colors.transparent,
          child: InkWell(
            borderRadius: BorderRadius.circular(20),
            onTap: () => _openPicker(context),
            child: Container(
              padding: EdgeInsets.symmetric(
                horizontal: isMobile ? 8 : 12,
                vertical: 8,
              ),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(20),
                border: Border.all(color: textColor.withValues(alpha: 0.25)),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(Icons.language, size: isMobile ? 18 : 20, color: textColor),
                  if (!isMobile) ...[
                    const SizedBox(width: 6),
                    Text(
                      locale.language.nativeName,
                      style: GoogleFonts.figtree(
                        color: textColor,
                        fontWeight: FontWeight.w600,
                        fontSize: 14,
                      ),
                    ),
                  ],
                  Icon(Icons.arrow_drop_down, size: 18, color: textColor),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
