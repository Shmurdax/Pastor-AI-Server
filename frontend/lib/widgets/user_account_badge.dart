import 'package:flutter/material.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:intl/intl.dart';

/// Hammer for staff accounts, star for paid Premium accounts.

/// Hammer for staff accounts, star for paid Premium accounts.
/// Staff who also have an active subscription get both.
String accountBadgeFor({
  required bool isStaff,
  required bool isPremium,
  String subscriptionStatus = '',
}) {
  final paid = subscriptionStatus == 'active' || (isPremium && !isStaff);
  final marks = <String>[];
  if (isStaff) marks.add('🔨');
  if (paid) marks.add('⭐');
  return marks.join();
}

String accountBadgeForUser(AuthUser user) => accountBadgeFor(
      isStaff: user.isStaff,
      isPremium: user.isPremium,
      subscriptionStatus: user.subscriptionStatus,
    );

String displayNameWithBadge(AuthUser user, {bool firstNameOnly = false}) {
  final name = firstNameOnly ? user.name.split(' ').first : user.name;
  final badge = accountBadgeForUser(user);
  if (badge.isEmpty) return name;
  return '$name $badge';
}

String formatPremiumAccessUntil(DateTime? periodEnd) {
  if (periodEnd == null) return 'the end of your billing period';
  return DateFormat.yMMMMd().format(periodEnd.toLocal());
}

/// User's name with a staff hammer and/or Premium star beside it.
///
/// Badges sit in their own unshrinkable child so chip/box fade overflow
/// cannot clip the emoji.
class UserNameWithAccountBadge extends StatelessWidget {
  const UserNameWithAccountBadge({
    super.key,
    required this.user,
    this.firstNameOnly = false,
    this.style,
    this.overflow,
    this.maxLines,
  });

  final AuthUser user;
  final bool firstNameOnly;
  final TextStyle? style;
  final TextOverflow? overflow;
  final int? maxLines;

  @override
  Widget build(BuildContext context) {
    final name = firstNameOnly ? user.name.split(' ').first : user.name;
    final badge = accountBadgeForUser(user);
    final useEllipsis = overflow == TextOverflow.ellipsis;

    final nameText = Text(
      name,
      style: style,
      overflow: overflow ?? TextOverflow.clip,
      maxLines: maxLines ?? 1,
      softWrap: false,
    );

    if (badge.isEmpty) return nameText;

    return Row(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        if (useEllipsis) Flexible(child: nameText) else nameText,
        const SizedBox(width: 6),
        Text(
          badge,
          style: style,
          maxLines: 1,
          softWrap: false,
          overflow: TextOverflow.visible,
        ),
      ],
    );
  }
}
