import 'package:flutter/material.dart';
import 'package:flutter_application_1/services/auth_service.dart';

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

/// User's name with a staff hammer and/or Premium star beside it.
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
    return Text(
      displayNameWithBadge(user, firstNameOnly: firstNameOnly),
      style: style,
      overflow: overflow,
      maxLines: maxLines,
    );
  }
}
