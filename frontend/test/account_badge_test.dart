import 'package:flutter/material.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:flutter_application_1/widgets/user_account_badge.dart';
import 'package:flutter_test/flutter_test.dart';

AuthUser _user({
  required String name,
  bool isStaff = false,
  bool isPremium = false,
  String subscriptionStatus = 'free',
}) {
  return AuthUser(
    id: '1',
    email: 'user@example.com',
    name: name,
    isStaff: isStaff,
    isPremium: isPremium,
    subscriptionStatus: subscriptionStatus,
  );
}

void main() {
  test('staff accounts show a hammer beside the name', () {
    final user = _user(name: 'Pastor Don', isStaff: true, isPremium: true);
    expect(accountBadgeForUser(user), '🔨');
    expect(displayNameWithBadge(user), 'Pastor Don 🔨');
    expect(displayNameWithBadge(user, firstNameOnly: true), 'Pastor 🔨');
  });

  test('premium accounts show a star beside the name', () {
    final user = _user(
      name: 'Jane Member',
      isPremium: true,
      subscriptionStatus: 'active',
    );
    expect(accountBadgeForUser(user), '⭐');
    expect(displayNameWithBadge(user), 'Jane Member ⭐');
  });

  test('staff with an active subscription show hammer and star', () {
    final user = _user(
      name: 'Staff Paid',
      isStaff: true,
      isPremium: true,
      subscriptionStatus: 'active',
    );
    expect(accountBadgeForUser(user), '🔨⭐');
  });

  test('free members have no badge', () {
    final user = _user(name: 'Free User');
    expect(accountBadgeForUser(user), '');
    expect(displayNameWithBadge(user), 'Free User');
  });

  testWidgets('renders hammer beside a staff name', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: UserNameWithAccountBadge(user: _user(name: 'Pastor Don', isStaff: true)),
        ),
      ),
    );
    expect(find.text('Pastor Don'), findsOneWidget);
    expect(find.text('🔨'), findsOneWidget);
  });
}
