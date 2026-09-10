import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/l10n/app_locale.dart';
import 'package:flutter_application_1/screens/checkout_screen.dart';
import 'package:flutter_application_1/screens/login_screen.dart';
import 'package:flutter_application_1/screens/media_library_screen.dart';
import 'package:flutter_application_1/screens/prayer_inbox_screen.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:flutter_application_1/widgets/account_profile_chip.dart';
import 'package:flutter_application_1/widgets/language_selector.dart';
import 'package:flutter_application_1/widgets/church_events_nav_overlay.dart';
import 'package:flutter_application_1/widgets/nordins_ai_nav_menu.dart';
import 'package:flutter_application_1/widgets/user_account_badge.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

const _navy = Color(0xFF1B264F);
const _gold = Color(0xFFD4AF37);
const _pink = Color(0xFFa1375a);

const _freePerks = [
  'Access to most recent chat history',
];

const _premiumPerks = [
  'Unlimited Chat history',
  'Access to daily 15-minute video devotional video',
  "the Nordin's study notes",
  'Daily Bible reading assignment.',
];

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

  Future<void> _onPremiumSelected() async {
    final auth = context.read<AuthController>();
    if (auth.user?.isPaidPremium == true) return;
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
          'After that, your account returns to the Free plan and auto-renewal stops.',
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
        SnackBar(content: Text(e.toString().replaceFirst(RegExp(r'^Exception:\s*'), ''))),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final screenWidth = MediaQuery.of(context).size.width;
    final isMobileOrTablet = screenWidth < 1024;
    final isMobile = screenWidth < 600;
    final isNarrow = screenWidth < 900;

    final premiumSubtitle =
        _billingPeriod == BillingPeriod.monthly ? 'Monthly' : 'Yearly';
    final premiumPrice =
        _billingPeriod == BillingPeriod.monthly ? '\$15.00' : '\$150.00';
    final premiumPeriod =
        _billingPeriod == BillingPeriod.monthly ? '/ month' : '/ year';
    final auth = context.watch<AuthController>();
    final s = context.watch<LocaleController>().strings;
    final paid = auth.user?.isPaidPremium == true;
    final cancelScheduled = paid && (auth.user?.cancelAtPeriodEnd ?? false);
    final premiumCta = paid
        ? (cancelScheduled
            ? 'Current plan · ends ${formatPremiumAccessUntil(auth.user?.currentPeriodEnd)}'
            : 'Your current plan')
        : 'Select plan →';

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
          LanguageSelector(isMobile: isMobile),
          if (auth.isAuthenticated && auth.user!.isStaff)
            Padding(
              padding: EdgeInsets.only(top: isMobile ? 20 : 45, right: 4),
              child: IconButton(
                tooltip: s.prayerInbox,
                onPressed: _openPrayerInbox,
                icon: const Icon(Icons.volunteer_activism_outlined, color: _navy),
              ),
            ),
          if (auth.isAuthenticated)
            AccountProfileChip(
              apiService: _apiService,
              isMobile: isMobile,
              onOpenMedia: _openMedia,
              onOpenPrayerInbox: _openPrayerInbox,
              onSignedOut: () {
                if (mounted) Navigator.of(context).popUntil((route) => route.isFirst);
              },
            ),
          if (!isMobile)
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
                    label: s.store,
                    onTap: () => _launchUrl('https://thenordins.org/store'),
                  ),
                  _NavButton(
                    label: s.events,
                    onTap: () => _toggleEvents(open: true),
                    active: _eventsOpen,
                  ),
                  NordinsAiNavMenu(
                    onAiHome: _goToAiHome,
                    onMedia: _openMedia,
                    onSubscribe: () => _toggleEvents(open: false),
                    active: true,
                  ),
                  const SizedBox(width: 40),
                ],
              ),
            ),
          if (isMobile)
            Padding(
              padding: const EdgeInsets.only(top: 20.0, right: 4),
              child: IconButton(
                tooltip: s.events,
                onPressed: () => _toggleEvents(open: true),
                icon: Icon(
                  Icons.event_outlined,
                  color: _eventsOpen ? _gold : _navy,
                ),
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
                        'Support the ministry and unlock more of Nordin\'s AI.',
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
                        Column(
                          children: [
                            _TierCard(
                              title: 'Free',
                              subtitle: 'Get Started',
                              priceLabel: '\$0',
                              pricePeriod: 'forever',
                              perks: _freePerks,
                              style: _TierVisualStyle.outlined,
                            ),
                            const SizedBox(height: 20),
                            _TierCard(
                              title: 'Premium',
                              subtitle: premiumSubtitle,
                              priceLabel: premiumPrice,
                              pricePeriod: premiumPeriod,
                              perks: _premiumPerks,
                              style: _TierVisualStyle.filled,
                              ctaLabel: premiumCta,
                              onTap: paid ? null : _onPremiumSelected,
                            ),
                          ],
                        )
                      else
                        IntrinsicHeight(
                          child: Row(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [
                              Expanded(
                                child: _TierCard(
                                  title: 'Free',
                                  subtitle: 'Get Started',
                                  priceLabel: '\$0',
                                  pricePeriod: 'forever',
                                  perks: _freePerks,
                                  style: _TierVisualStyle.outlined,
                                ),
                              ),
                              const SizedBox(width: 24),
                              Expanded(
                                child: _TierCard(
                                  title: 'Premium',
                                  subtitle: premiumSubtitle,
                                  priceLabel: premiumPrice,
                                  pricePeriod: premiumPeriod,
                                  perks: _premiumPerks,
                                  style: _TierVisualStyle.filled,
                                  ctaLabel: premiumCta,
                                  onTap: paid ? null : _onPremiumSelected,
                                ),
                              ),
                            ],
                          ),
                        ),
                      if (paid && !cancelScheduled) ...[
                        const SizedBox(height: 28),
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
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

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
          child: Text(
            label,
            style: GoogleFonts.figtree(
              fontSize: 14,
              fontWeight: FontWeight.w700,
              color: selected ? Colors.white : _navy,
            ),
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
