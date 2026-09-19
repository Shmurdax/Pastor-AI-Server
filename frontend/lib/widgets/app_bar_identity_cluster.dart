import 'package:flutter/material.dart';
import 'package:flutter_application_1/widgets/language_selector.dart';

/// App-bar trailing identity controls.
///
/// On desktop the language picker sits in the action row. When it collapses
/// to the globe + dropdown, it stacks under the account chip so the logo
/// keeps the extra horizontal room. The account chip keeps the same top
/// inset it had in the single-row header.
class AppBarIdentityCluster extends StatelessWidget {
  const AppBarIdentityCluster({
    super.key,
    required this.isMobile,
    this.account,
    this.menu,
  });

  final bool isMobile;
  final Widget? account;
  final Widget? menu;

  static const _accountTopInset = 20.0;

  @override
  Widget build(BuildContext context) {
    final language = LanguageSelector(isMobile: isMobile, dense: isMobile);

    if (!isMobile) {
      return Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          language,
          if (account != null) account!,
          if (menu != null) menu!,
        ],
      );
    }

    final stacked = Padding(
      padding: const EdgeInsets.only(top: _accountTopInset, right: 8),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.start,
        crossAxisAlignment: CrossAxisAlignment.end,
        mainAxisSize: MainAxisSize.min,
        children: [
          if (account != null) account!,
          if (account == null && menu != null) menu!,
          language,
        ],
      ),
    );

    if (account != null && menu != null) {
      return Row(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          menu!,
          stacked,
        ],
      );
    }

    return stacked;
  }
}
