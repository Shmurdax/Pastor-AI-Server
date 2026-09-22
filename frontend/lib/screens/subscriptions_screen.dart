import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/l10n/app_locale.dart';
import 'package:flutter_application_1/screens/checkout_screen.dart';
import 'package:flutter_application_1/screens/login_screen.dart';
import 'package:flutter_application_1/screens/media_library_screen.dart';
import 'package:flutter_application_1/screens/prayer_inbox_screen.dart';
import 'package:flutter_application_1/screens/update_payment_method_screen.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:flutter_application_1/widgets/account_profile_chip.dart';
import 'package:flutter_application_1/widgets/app_bar_identity_cluster.dart';
import 'package:flutter_application_1/widgets/church_events_nav_overlay.dart';
import 'package:flutter_application_1/widgets/app_hamburger_nav.dart';
import 'package:flutter_application_1/widgets/user_account_badge.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

const _navy = Color(0xFF1B264F);
const _gold = Color(0xFFD4AF37);
const _pink = Color(0xFFa1375a);

const premiumPerks = [
  'Customized, biblical AI chat experience',
  'Access to Walk through the Word videos',
  'Over 40 years of study notes and preached on material',
];

String billingPeriodApiValue(BillingPeriod period) =>
    period == BillingPeriod.yearly ? 'yearly' : 'monthly';

BillingPeriod billingPeriodFromApi(String value) =>
    value == 'yearly' ? BillingPeriod.yearly : BillingPeriod.monthly;

String billingPeriodLabel(BillingPeriod period) =>
    period == BillingPeriod.yearly ? 'yearly' : 'monthly';

String billingPeriodPriceLabel(BillingPeriod period) =>
    period == BillingPeriod.yearly ? r'$150/year' : r'$15/month';

enum PremiumPlanAction { checkout, none, changePlan, revertPending }

PremiumPlanAction premiumPlanAction({
  required bool paid,
  required bool cancelScheduled,
  required BillingPeriod selected,
  required String currentPeriod,
  required String pendingPeriod,
}) {
  if (!paid) return PremiumPlanAction.checkout;
  final selectedValue = billingPeriodApiValue(selected);
  if (pendingPeriod == selectedValue) return PremiumPlanAction.none;
  if (currentPeriod == selectedValue && pendingPeriod.isEmpty) {
    return PremiumPlanAction.none;
  }
  if (currentPeriod == selectedValue && pendingPeriod.isNotEmpty) {
    return PremiumPlanAction.revertPending;
  }
  if (cancelScheduled && currentPeriod == selectedValue) {
    return PremiumPlanAction.none;
  }
  return PremiumPlanAction.changePlan;
}

String premiumPlanCtaLabel({
  required bool paid,
  required bool cancelScheduled,
  required BillingPeriod selected,
  required String currentPeriod,
  required String pendingPeriod,
  DateTime? periodEnd,
}) {
  if (!paid) return 'Select plan →';
  final selectedValue = billingPeriodApiValue(selected);
  if (cancelScheduled && currentPeriod == selectedValue && pendingPeriod.isEmpty) {
    return 'Current plan · ends ${formatPremiumAccessUntil(periodEnd)}';
  }
  if (pendingPeriod == selectedValue) {
    return 'Switching on ${formatPremiumAccessUntil(periodEnd)}';
  }
  if (currentPeriod == selectedValue && pendingPeriod.isEmpty) {
    return 'Your current plan';
  }
  if (currentPeriod == selectedValue && pendingPeriod.isNotEmpty) {
    return 'Keep ${billingPeriodLabel(selected)}';
  }
  return 'Switch to ${billingPeriodLabel(selected)} →';
}

/// Pricing / plans page styled after the Sermon Library sidebar.
class SubscriptionsScreen extends StatefulWidget {
  const SubscriptionsScreen({super.key});

  @override
  State<SubscriptionsScreen> createState() => _SubscriptionsScreenState();
}

class _SubscriptionsScreenState extends State<SubscriptionsScreen> {
  final _apiService = ApiService();
  bool _eventsOpen = false;
  BillingPeriod _billingPeriod = BillingPeriod.monthly;
  bool _syncing = false;
  bool _changingPlan = false;
  bool _didInitPeriod = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      unawaited(_syncSubscriptionIfNeeded());
    });
  }

  Future<void> _syncSubscriptionIfNeeded() async {
    if (!mounted || _syncing) return;
    final auth = context.read<AuthController>();
    _syncBillingPeriodFromUser(auth.user);
    if (!auth.isAuthenticated || auth.hasPremiumAccess) return;
    setState(() => _syncing = true);
    try {
      _apiService.setAccessToken(auth.token);
      final result = await _apiService.syncSubscription();
      final userJson = result['user'];
      if (userJson is Map<String, dynamic>) {
        await auth.applyUser(AuthUser.fromJson(userJson));
      } else {
        await auth.refreshMe();
      }
    } catch (_) {
      // Non-fatal — user can still subscribe manually.
    } finally {
      if (mounted) setState(() => _syncing = false);
    }
  }

  Future<void> _launchUrl(String urlString) async {
    final url = Uri.parse(urlString);
    if (await canLaunchUrl(url)) {
      await launchUrl(url, mode: LaunchMode.externalApplication);
    }
  }

  void _syncBillingPeriodFromUser(AuthUser? user) {
    if (_didInitPeriod || user == null) return;
    if (user.billingPeriod != 'yearly' && user.billingPeriod != 'monthly') return;
    _didInitPeriod = true;
    final next = billingPeriodFromApi(user.billingPeriod);
    if (next == _billingPeriod) return;
    setState(() => _billingPeriod = next);
  }

  void _goToAiHome() {
    Navigator.of(context).popUntil((route) => route.isFirst);
  }

  void _openMedia() {
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(builder: (_) => const MediaLibraryScreen()),
    );
  }

  void _openPrayerInbox() {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => PrayerInboxScreen(apiService: _apiService),
      ),
    );
  }

  void _toggleEvents({bool? open}) {
    setState(() => _eventsOpen = open ?? !_eventsOpen);
  }

  void _openCheckout() {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => CheckoutScreen(billingPeriod: _billingPeriod),
      ),
    );
  }

  void _openPaymentMethodUpdate() {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => const UpdatePaymentMethodScreen(),
      ),
    );
  }

  Future<void> _onPremiumSelected() async {
    final auth = context.read<AuthController>();
    final user = auth.user;
    if (user?.isPaidPremium == true) {
      await _onPaidPlanSelected(user!);
      return;
    }
    if (auth.isAuthenticated) {
      _openCheckout();
      return;
    }

    final signedIn = await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
    );
    if (!mounted) return;
    if (signedIn == true && context.read<AuthController>().isAuthenticated) {
      _openCheckout();
    }
  }

  Future<void> _onPaidPlanSelected(AuthUser user) async {
    if (_changingPlan) return;
    final action = premiumPlanAction(
      paid: true,
      cancelScheduled: user.cancelAtPeriodEnd,
      selected: _billingPeriod,
      currentPeriod: user.billingPeriod,
      pendingPeriod: user.pendingBillingPeriod,
    );
    if (action == PremiumPlanAction.none) return;

    final target = billingPeriodApiValue(_billingPeriod);
    final confirmed = await _confirmPlanChange(
      user: user,
      action: action,
      targetPeriod: _billingPeriod,
    );
    if (confirmed != true || !mounted) return;

    setState(() => _changingPlan = true);
    final auth = context.read<AuthController>();
    try {
      _apiService.setAccessToken(auth.token);
      final result = await _apiService.changeSubscriptionPlan(billingPeriod: target);
      final userJson = result['user'];
      if (userJson is Map<String, dynamic>) {
        await auth.applyUser(AuthUser.fromJson(userJson));
      } else {
        await auth.refreshMe();
      }
      if (!mounted) return;
      final updated = auth.user;
      final snack = action == PremiumPlanAction.revertPending
          ? 'You will stay on ${billingPeriodLabel(_billingPeriod)} Premium.'
          : 'You will switch to ${billingPeriodLabel(_billingPeriod)} '
              '(${billingPeriodPriceLabel(_billingPeriod)}) on '
              '${formatPremiumAccessUntil(updated?.currentPeriodEnd)}.';
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(snack)));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            e.toString().replaceFirst(RegExp(r'^Exception:\s*'), ''),
            maxLines: 4,
            overflow: TextOverflow.ellipsis,
          ),
        ),
      );
    } finally {
      if (mounted) setState(() => _changingPlan = false);
    }
  }

  Future<bool?> _confirmPlanChange({
    required AuthUser user,
    required PremiumPlanAction action,
    required BillingPeriod targetPeriod,
  }) {
    final when = formatPremiumAccessUntil(user.currentPeriodEnd);
    final title = action == PremiumPlanAction.revertPending
        ? 'Keep ${billingPeriodLabel(targetPeriod)} Premium?'
        : 'Switch to ${billingPeriodLabel(targetPeriod)}?';
    final body = action == PremiumPlanAction.revertPending
        ? 'Cancel the scheduled switch. You will stay on '
            '${billingPeriodLabel(targetPeriod)} Premium '
            '(${billingPeriodPriceLabel(targetPeriod)}).'
        : 'You keep your current ${user.billingPeriod.isEmpty ? 'Premium' : user.billingPeriod} '
            'plan until $when. Starting then, you will be billed '
            '${billingPeriodPriceLabel(targetPeriod)} instead. Premium access does not stop.';
    final confirmLabel =
        action == PremiumPlanAction.revertPending ? 'Keep this plan' : 'Switch plan';

    return showDialog<bool>(
      context: context,
      builder: (dialogCtx) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        title: Text(title, style: GoogleFonts.figtree(color: _navy, fontWeight: FontWeight.bold)),
        content: Text(body, style: GoogleFonts.figtree(height: 1.45)),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogCtx).pop(false),
            child: Text('Not now', style: GoogleFonts.figtree(color: _navy, fontWeight: FontWeight.w600)),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogCtx).pop(true),
            style: FilledButton.styleFrom(backgroundColor: _navy),
            child: Text(confirmLabel, style: GoogleFonts.figtree(fontWeight: FontWeight.bold)),
          ),
        ],
      ),
    );
  }

  Future<void> _unsubscribe() async {
    final auth = context.read<AuthController>();
    final user = auth.user;
    if (user == null || !user.isPaidPremium || user.cancelAtPeriodEnd) return;

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogCtx) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        title: Text('Unsubscribe from Premium?', style: GoogleFonts.figtree(color: _navy, fontWeight: FontWeight.bold)),
        content: Text(
          'You will keep Premium benefits until ${formatPremiumAccessUntil(user.currentPeriodEnd)}. '
          'After that, access to Nordin\'s AI ends and auto-renewal stops.',
          style: GoogleFonts.figtree(height: 1.45),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogCtx).pop(false),
            child: Text('Keep Premium', style: GoogleFonts.figtree(color: _navy, fontWeight: FontWeight.w600)),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogCtx).pop(true),
            style: FilledButton.styleFrom(backgroundColor: _pink),
            child: Text('Unsubscribe', style: GoogleFonts.figtree(fontWeight: FontWeight.bold)),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    try {
      _apiService.setAccessToken(auth.token);
      final result = await _apiService.cancelSubscription();
      final userJson = result['user'];
      if (userJson is Map<String, dynamic>) {
        await auth.applyUser(AuthUser.fromJson(userJson));
      } else {
        await auth.refreshMe();
      }
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            'Auto-renewal is off. Premium stays until ${formatPremiumAccessUntil(auth.user?.currentPeriodEnd)}.',
          ),
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            e.toString().replaceFirst(RegExp(r'^Exception:\s*'), ''),
            maxLines: 4,
            overflow: TextOverflow.ellipsis,
          ),
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final screenWidth = MediaQuery.of(context).size.width;
    final isMobileOrTablet = screenWidth < 1024;
    final isMobile = screenWidth < 600;
    final isNarrow = screenWidth < 900;

    final premiumSubtitle = _billingPeriod == BillingPeriod.monthly
        ? 'Monthly'
        : 'Yearly · ${yearlyBillingDiscountVsMonthlyLabel()}';
    final premiumPrice =
        _billingPeriod == BillingPeriod.monthly ? '\$15.00' : '\$150.00';
    final premiumPeriod =
        _billingPeriod == BillingPeriod.monthly ? '/ month' : '/ year';
    final auth = context.watch<AuthController>();
    final s = context.watch<LocaleController>().strings;
    final paid = auth.user?.isPaidPremium == true;
    final canUpdatePayment = auth.user?.canManagePaymentMethod == true;
    final cancelScheduled = paid && (auth.user?.cancelAtPeriodEnd ?? false);
    final currentPeriod = auth.user?.billingPeriod ?? '';
    final pendingPeriod = auth.user?.pendingBillingPeriod ?? '';
    final planAction = premiumPlanAction(
      paid: paid,
      cancelScheduled: cancelScheduled,
      selected: _billingPeriod,
      currentPeriod: currentPeriod,
      pendingPeriod: pendingPeriod,
    );
    final premiumCta = _changingPlan
        ? 'Updating plan…'
        : premiumPlanCtaLabel(
            paid: paid,
            cancelScheduled: cancelScheduled,
            selected: _billingPeriod,
            currentPeriod: currentPeriod,
            pendingPeriod: pendingPeriod,
            periodEnd: auth.user?.currentPeriodEnd,
          );
    final premiumTap = planAction == PremiumPlanAction.none || _changingPlan
        ? null
        : _onPremiumSelected;

    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        centerTitle: false,
        backgroundColor: Colors.white,
        elevation: 0,
        toolbarHeight: isMobileOrTablet ? 100 : 120,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, color: _navy),
          onPressed: () => Navigator.of(context).pop(),
        ),
        automaticallyImplyLeading: true,
        title: Padding(
          padding: EdgeInsets.only(
            top: isMobileOrTablet ? 10.0 : 20.0,
            left: isMobileOrTablet ? 0.0 : 12.0,
          ),
          child: GestureDetector(
            onTap: () => _launchUrl('https://thenordins.org/'),
            child: MouseRegion(
              cursor: SystemMouseCursors.click,
              child: Image.asset(
                'assets/images/nordins_main_logo.png',
                height: isMobileOrTablet ? 80 : 95,
                fit: BoxFit.contain,
              ),
            ),
          ),
        ),
        actions: [
          if (auth.isAuthenticated && auth.user!.isStaff && screenWidth > 600)
            Padding(
              padding: EdgeInsets.only(top: isMobile ? 20 : 45, right: 4),
              child: IconButton(
                tooltip: s.prayerInbox,
                onPressed: _openPrayerInbox,
                icon: const Icon(Icons.volunteer_activism_outlined, color: _navy),
              ),
            ),
          AppBarIdentityCluster(
            isMobile: isMobile,
            account: auth.isAuthenticated
                ? AccountProfileChip(
                    apiService: _apiService,
                    isMobile: isMobile,
                    dense: isMobile,
                    onOpenMedia: _openMedia,
                    onOpenPrayerInbox: _openPrayerInbox,
                    onSignedOut: () {
                      if (mounted) Navigator.of(context).popUntil((route) => route.isFirst);
                    },
                  )
                : null,
            menu: isMobileOrTablet
                ? AppHamburgerNav(
                    isMobile: isMobile,
                    dense: isMobile,
                    onHome: () => _launchUrl('https://thenordins.org/'),
                    onChat: _goToAiHome,
                    onEvents: () => _toggleEvents(open: true),
                    onMedia: _openMedia,
                  )
                : null,
          ),
          if (!isMobileOrTablet)
            Padding(
              padding: const EdgeInsets.only(top: 45.0),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  _NavButton(
                    label: s.home,
                    onTap: () => _launchUrl('https://thenordins.org/'),
                  ),
                  _NavButton(
                    label: s.chat,
                    onTap: _goToAiHome,
                  ),
                  _NavButton(
                    label: s.events,
                    onTap: () => _toggleEvents(open: true),
                    active: _eventsOpen,
                  ),
                  _NavButton(
                    label: s.media,
                    onTap: _openMedia,
                  ),
                  const SizedBox(width: 40),
                ],
              ),
            ),
        ],
      ),
      body: Stack(
        children: [
          SafeArea(
            child: Center(
              child: SingleChildScrollView(
                padding: EdgeInsets.symmetric(
                  horizontal: isMobile ? 16 : 32,
                  vertical: isMobile ? 24 : 40,
                ),
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 900),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Text(
                        'Choose your plan',
                        textAlign: TextAlign.center,
                        style: GoogleFonts.figtree(
                          fontSize: isMobile ? 28 : 36,
                          fontWeight: FontWeight.bold,
                          color: _navy,
                        ),
                      ),
                      const SizedBox(height: 8),
                      Center(
                        child: Container(height: 2, width: 48, color: _gold),
                      ),
                      const SizedBox(height: 12),
                      Text(
                        'Manage your Nordin\'s AI subscription.',
                        textAlign: TextAlign.center,
                        style: GoogleFonts.figtree(
                          fontSize: 15,
                          color: Colors.black54,
                        ),
                      ),
                      const SizedBox(height: 28),
                      Center(
                        child: _BillingPeriodToggle(
                          value: _billingPeriod,
                          onChanged: (period) {
                            setState(() => _billingPeriod = period);
                          },
                        ),
                      ),
                      const SizedBox(height: 36),
                      if (isNarrow)
                        _TierCard(
                          title: 'Premium',
                          subtitle: premiumSubtitle,
                          priceLabel: premiumPrice,
                          pricePeriod: premiumPeriod,
                          perks: premiumPerks,
                          style: _TierVisualStyle.filled,
                          ctaLabel: premiumCta,
                          onTap: premiumTap,
                        )
                      else
                        Center(
                          child: ConstrainedBox(
                            constraints: const BoxConstraints(maxWidth: 420),
                            child: _TierCard(
                              title: 'Premium',
                              subtitle: premiumSubtitle,
                              priceLabel: premiumPrice,
                              pricePeriod: premiumPeriod,
                              perks: premiumPerks,
                              style: _TierVisualStyle.filled,
                              ctaLabel: premiumCta,
                              onTap: premiumTap,
                            ),
                          ),
                        ),
                      if (pendingPeriod.isNotEmpty) ...[
                        const SizedBox(height: 24),
                        Text(
                          'Your plan switches to ${pendingPeriod == 'yearly' ? 'yearly (\$150/year)' : 'monthly (\$15/month)'} '
                          'on ${formatPremiumAccessUntil(auth.user?.currentPeriodEnd)}. '
                          'Until then you stay on ${currentPeriod.isEmpty ? 'your current plan' : currentPeriod}.',
                          textAlign: TextAlign.center,
                          style: GoogleFonts.figtree(fontSize: 14, color: _navy, height: 1.45),
                        ),
                      ],
                      if (canUpdatePayment) ...[
                        const SizedBox(height: 28),
                        Center(
                          child: TextButton(
                            onPressed: _openPaymentMethodUpdate,
                            child: Text(
                              'Update payment method',
                              style: GoogleFonts.figtree(
                                color: _navy,
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          'Replace a card that is expired or about to expire. '
                          'Future renewals use the new card.',
                          textAlign: TextAlign.center,
                          style: GoogleFonts.figtree(fontSize: 13, color: Colors.black54),
                        ),
                      ],
                      if (paid && !cancelScheduled) ...[
                        const SizedBox(height: 12),
                        Center(
                          child: TextButton(
                            onPressed: _unsubscribe,
                            child: Text(
                              'Unsubscribe from Premium',
                              style: GoogleFonts.figtree(
                                color: _pink,
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          'You will keep Premium until the end of the current billing period.',
                          textAlign: TextAlign.center,
                          style: GoogleFonts.figtree(fontSize: 13, color: Colors.black54),
                        ),
                      ],
                    ],
                  ),
                ),
              ),
            ),
          ),
          if (_eventsOpen)
            Positioned(
              top: 0,
              right: 0,
              child: ChurchEventsNavOverlay(
                apiService: _apiService,
                isStaff: context.watch<AuthController>().user?.isStaff ?? false,
                onClose: () => _toggleEvents(open: false),
              ),
            ),
        ],
      ),
    );
  }
}

class _BillingPeriodToggle extends StatelessWidget {
  const _BillingPeriodToggle({
    required this.value,
    required this.onChanged,
  });

  final BillingPeriod value;
  final ValueChanged<BillingPeriod> onChanged;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: const Color(0xFFF4F4F9),
        borderRadius: BorderRadius.circular(28),
        border: Border.all(color: _gold.withValues(alpha: 0.45)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          _ToggleChip(
            label: 'Monthly',
            selected: value == BillingPeriod.monthly,
            onTap: () => onChanged(BillingPeriod.monthly),
          ),
          _ToggleChip(
            label: 'Yearly',
            selected: value == BillingPeriod.yearly,
            onTap: () => onChanged(BillingPeriod.yearly),
            badge: yearlyBillingDiscountLabel(),
          ),
        ],
      ),
    );
  }
}

class _ToggleChip extends StatelessWidget {
  const _ToggleChip({
    required this.label,
    required this.selected,
    required this.onTap,
    this.badge,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;
  final String? badge;

  @override
  Widget build(BuildContext context) {
    return MouseRegion(
      cursor: SystemMouseCursors.click,
      child: GestureDetector(
        onTap: onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 200),
          curve: Curves.easeOut,
          padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 10),
          decoration: BoxDecoration(
            color: selected ? _navy : Colors.transparent,
            borderRadius: BorderRadius.circular(24),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                label,
                style: GoogleFonts.figtree(
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                  color: selected ? Colors.white : _navy,
                ),
              ),
              if (badge != null) ...[
                const SizedBox(height: 2),
                Text(
                  badge!,
                  style: GoogleFonts.figtree(
                    fontSize: 11,
                    fontWeight: FontWeight.w700,
                    color: selected ? _gold : _pink,
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

enum _TierVisualStyle { outlined, filled }

class _TierCard extends StatefulWidget {
  const _TierCard({
    required this.title,
    required this.subtitle,
    required this.priceLabel,
    required this.pricePeriod,
    required this.perks,
    required this.style,
    this.onTap,
    this.ctaLabel = 'Select plan →',
  });

  final String title;
  final String subtitle;
  final String priceLabel;
  final String pricePeriod;
  final List<String> perks;
  final _TierVisualStyle style;
  final VoidCallback? onTap;
  final String ctaLabel;

  @override
  State<_TierCard> createState() => _TierCardState();
}

class _TierCardState extends State<_TierCard> {
  bool _hovered = false;

  bool get _filled => widget.style == _TierVisualStyle.filled;

  @override
  Widget build(BuildContext context) {
    final titleColor = _filled ? Colors.white : _navy;
    final subtitleColor = _filled ? Colors.white70 : Colors.black54;
    final priceColor = _filled ? Colors.white : _navy;
    final periodColor = _filled ? Colors.white70 : Colors.black54;
    final perkColor = _filled ? Colors.white : _navy;
    final clickable = widget.onTap != null;

    return MouseRegion(
      onEnter: clickable ? (_) => setState(() => _hovered = true) : null,
      onExit: clickable ? (_) => setState(() => _hovered = false) : null,
      cursor: clickable ? SystemMouseCursors.click : SystemMouseCursors.basic,
      child: GestureDetector(
        onTap: widget.onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 180),
          curve: Curves.easeOut,
          transform: Matrix4.translationValues(0, _hovered ? -2 : 0, 0),
          padding: const EdgeInsets.fromLTRB(22, 26, 22, 26),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(32),
            gradient: _filled
                ? const LinearGradient(
                    colors: [_pink, _navy],
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                  )
                : null,
            color: _filled ? null : Colors.white,
            border: _filled
                ? Border.all(
                    color: _hovered ? _gold : Colors.transparent,
                    width: 2,
                  )
                : Border.all(color: _gold, width: 2),
            boxShadow: _hovered
                ? [
                    BoxShadow(
                      color: _navy.withValues(alpha: 0.18),
                      blurRadius: 18,
                      offset: const Offset(0, 8),
                    ),
                  ]
                : null,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                widget.title,
                style: GoogleFonts.figtree(
                  fontSize: 22,
                  fontWeight: FontWeight.bold,
                  color: titleColor,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                widget.subtitle,
                style: GoogleFonts.figtree(fontSize: 13, color: subtitleColor),
              ),
              const SizedBox(height: 18),
              Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(
                    widget.priceLabel,
                    style: GoogleFonts.figtree(
                      fontSize: 32,
                      fontWeight: FontWeight.bold,
                      color: priceColor,
                    ),
                  ),
                  const SizedBox(width: 6),
                  Padding(
                    padding: const EdgeInsets.only(bottom: 6),
                    child: Text(
                      widget.pricePeriod,
                      style: GoogleFonts.figtree(fontSize: 13, color: periodColor),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 10),
              Container(height: 2, width: 40, color: _gold),
              const SizedBox(height: 22),
              for (var i = 0; i < widget.perks.length; i++) ...[
                if (i > 0) const SizedBox(height: 14),
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Padding(
                      padding: const EdgeInsets.only(top: 2),
                      child: Icon(
                        Icons.check_circle_outline,
                        size: 18,
                        color: _filled ? _gold : _navy,
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        widget.perks[i],
                        style: GoogleFonts.figtree(
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                          height: 1.35,
                          color: perkColor,
                        ),
                      ),
                    ),
                  ],
                ),
              ],
              if (clickable || widget.ctaLabel != 'Select plan →') ...[
                const SizedBox(height: 24),
                Align(
                  alignment: Alignment.centerLeft,
                  child: Text(
                    widget.ctaLabel,
                    style: GoogleFonts.figtree(
                      fontSize: 14,
                      fontWeight: FontWeight.w700,
                      color: _gold,
                    ),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _NavButton extends StatefulWidget {
  const _NavButton({
    required this.label,
    this.onTap,
    this.active = false,
  });

  final String label;
  final VoidCallback? onTap;
  final bool active;

  @override
  State<_NavButton> createState() => _NavButtonState();
}

class _NavButtonState extends State<_NavButton> {
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    return MouseRegion(
      onEnter: (_) => setState(() => _hovered = true),
      onExit: (_) => setState(() => _hovered = false),
      cursor: widget.onTap == null ? SystemMouseCursors.basic : SystemMouseCursors.click,
      child: GestureDetector(
        onTap: widget.onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 10.0),
          child: Stack(
            clipBehavior: Clip.none,
            children: [
              Padding(
                padding: const EdgeInsets.only(bottom: 6.0),
                child: Text(
                  widget.label.toUpperCase(),
                  style: const TextStyle(
                    fontFamily: 'Times New Roman',
                    color: Colors.black,
                    fontSize: 16,
                    fontWeight: FontWeight.w500,
                  ),
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
                    width: (_hovered || widget.active) ? 200 : 0,
                    color: _gold,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
