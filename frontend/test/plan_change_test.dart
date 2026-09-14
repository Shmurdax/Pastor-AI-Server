import 'package:flutter_application_1/screens/checkout_screen.dart';
import 'package:flutter_application_1/screens/subscriptions_screen.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('AuthUser parses a pending yearly switch', () {
    final user = AuthUser.fromJson({
      'id': 9,
      'email': 'monthly@test.com',
      'name': 'Monthly Member',
      'is_premium': true,
      'subscription_status': 'active',
      'billing_period': 'monthly',
      'pending_billing_period': 'yearly',
      'cancel_at_period_end': false,
      'current_period_end': '2026-10-01T00:00:00Z',
    });
    expect(user.isPaidPremium, isTrue);
    expect(user.billingPeriod, 'monthly');
    expect(user.pendingBillingPeriod, 'yearly');
    expect(user.toJson()['pending_billing_period'], 'yearly');
  });

  test('monthly premium CTA invites a yearly upgrade', () {
    expect(
      premiumPlanAction(
        paid: true,
        cancelScheduled: false,
        selected: BillingPeriod.yearly,
        currentPeriod: 'monthly',
        pendingPeriod: '',
      ),
      PremiumPlanAction.changePlan,
    );
    expect(
      premiumPlanCtaLabel(
        paid: true,
        cancelScheduled: false,
        selected: BillingPeriod.yearly,
        currentPeriod: 'monthly',
        pendingPeriod: '',
      ),
      'Switch to yearly →',
    );
  });

  test('current monthly plan is not a checkout action', () {
    expect(
      premiumPlanAction(
        paid: true,
        cancelScheduled: false,
        selected: BillingPeriod.monthly,
        currentPeriod: 'monthly',
        pendingPeriod: '',
      ),
      PremiumPlanAction.none,
    );
    expect(
      premiumPlanCtaLabel(
        paid: true,
        cancelScheduled: false,
        selected: BillingPeriod.monthly,
        currentPeriod: 'monthly',
        pendingPeriod: '',
      ),
      'Your current plan',
    );
  });

  test('pending yearly switch can be reverted from monthly', () {
    expect(
      premiumPlanAction(
        paid: true,
        cancelScheduled: false,
        selected: BillingPeriod.monthly,
        currentPeriod: 'monthly',
        pendingPeriod: 'yearly',
      ),
      PremiumPlanAction.revertPending,
    );
    expect(
      premiumPlanCtaLabel(
        paid: true,
        cancelScheduled: false,
        selected: BillingPeriod.monthly,
        currentPeriod: 'monthly',
        pendingPeriod: 'yearly',
      ),
      'Keep monthly',
    );
    expect(
      premiumPlanCtaLabel(
        paid: true,
        cancelScheduled: false,
        selected: BillingPeriod.yearly,
        currentPeriod: 'monthly',
        pendingPeriod: 'yearly',
      ),
      'Switching on the end of your billing period',
    );
  });

  test('guests still go through checkout', () {
    expect(
      premiumPlanAction(
        paid: false,
        cancelScheduled: false,
        selected: BillingPeriod.yearly,
        currentPeriod: '',
        pendingPeriod: '',
      ),
      PremiumPlanAction.checkout,
    );
    expect(
      premiumPlanCtaLabel(
        paid: false,
        cancelScheduled: false,
        selected: BillingPeriod.yearly,
        currentPeriod: '',
        pendingPeriod: '',
      ),
      'Select plan →',
    );
  });
}
