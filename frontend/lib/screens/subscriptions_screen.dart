import 'package:flutter/material.dart';
import 'package:flutter_application_1/screens/media_library_screen.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_application_1/widgets/church_events_nav_overlay.dart';
import 'package:flutter_application_1/widgets/nordins_ai_nav_menu.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:url_launcher/url_launcher.dart';

const _navy = Color(0xFF1B264F);
const _gold = Color(0xFFD4AF37);
const _pink = Color(0xFFa1375a);

const _benefits = [
  'Unlimited messages',
  'Access to media content',
  'Prayer requests',
  'More',
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
    // Replace so back / stack does not keep Subscribe under Media.
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(builder: (_) => const MediaLibraryScreen()),
    );
  }

  void _toggleEvents({bool? open}) {
    setState(() => _eventsOpen = open ?? !_eventsOpen);
  }

  @override
  Widget build(BuildContext context) {
    final screenWidth = MediaQuery.of(context).size.width;
    final isMobileOrTablet = screenWidth < 1024;
    final isMobile = screenWidth < 600;
    final isNarrow = screenWidth < 900;

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
          if (!isMobile)
            Padding(
              padding: const EdgeInsets.only(top: 45.0),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  _NavButton(
                    label: 'Home',
                    onTap: () => _launchUrl('https://thenordins.org/'),
                  ),
                  _NavButton(
                    label: 'Store',
                    onTap: () => _launchUrl('https://thenordins.org/store'),
                  ),
                  _NavButton(
                    label: 'Events',
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
                tooltip: 'Events',
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
                  constraints: const BoxConstraints(maxWidth: 1100),
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
                      const SizedBox(height: 36),
                      if (isNarrow)
                        _NarrowPlansLayout(benefits: _benefits)
                      else
                        _WidePlansLayout(benefits: _benefits),
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
                isStaff: false,
                onClose: () => _toggleEvents(open: false),
              ),
            ),
        ],
      ),
    );
  }
}

/// Desktop layout: tier columns + benefits labels on the right.
class _WidePlansLayout extends StatelessWidget {
  const _WidePlansLayout({required this.benefits});

  final List<String> benefits;

  static const _headerHeight = 148.0;

  @override
  Widget build(BuildContext context) {
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Expanded(
            child: _TierCard(
              title: 'Free',
              subtitle: 'Get started',
              priceLabel: '\$0',
              pricePeriod: 'forever',
              style: _TierVisualStyle.outlined,
              benefitCount: benefits.length,
              headerHeight: _headerHeight,
            ),
          ),
          const SizedBox(width: 20),
          Expanded(
            child: _TierCard(
              title: 'Premium',
              subtitle: 'Monthly',
              priceLabel: '\$9.99',
              pricePeriod: '/ month',
              style: _TierVisualStyle.filled,
              benefitCount: benefits.length,
              headerHeight: _headerHeight,
            ),
          ),
          const SizedBox(width: 20),
          Expanded(
            child: _TierCard(
              title: 'Premium',
              subtitle: 'Yearly',
              priceLabel: '\$99',
              pricePeriod: '/ year',
              badge: 'Best value',
              style: _TierVisualStyle.filled,
              benefitCount: benefits.length,
              headerHeight: _headerHeight,
            ),
          ),
          const SizedBox(width: 24),
          SizedBox(
            width: 200,
            child: _BenefitsColumn(
              benefits: benefits,
              headerHeight: _headerHeight,
            ),
          ),
        ],
      ),
    );
  }
}

/// Mobile / narrow: stack tiers; benefits sit beside each tier's blank rows.
class _NarrowPlansLayout extends StatelessWidget {
  const _NarrowPlansLayout({required this.benefits});

  final List<String> benefits;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        _TierCard(
          title: 'Free',
          subtitle: 'Get started',
          priceLabel: '\$0',
          pricePeriod: 'forever',
          style: _TierVisualStyle.outlined,
          benefitCount: benefits.length,
          benefitLabels: benefits,
        ),
        const SizedBox(height: 20),
        _TierCard(
          title: 'Premium',
          subtitle: 'Monthly',
          priceLabel: '\$9.99',
          pricePeriod: '/ month',
          style: _TierVisualStyle.filled,
          benefitCount: benefits.length,
          benefitLabels: benefits,
        ),
        const SizedBox(height: 20),
        _TierCard(
          title: 'Premium',
          subtitle: 'Yearly',
          priceLabel: '\$99',
          pricePeriod: '/ year',
          badge: 'Best value',
          style: _TierVisualStyle.filled,
          benefitCount: benefits.length,
          benefitLabels: benefits,
        ),
      ],
    );
  }
}

class _BenefitsColumn extends StatelessWidget {
  const _BenefitsColumn({
    required this.benefits,
    required this.headerHeight,
  });

  final List<String> benefits;
  final double headerHeight;

  @override
  Widget build(BuildContext context) {
    // Match tier card: top padding + header + gap before blank rows.
    return Padding(
      padding: EdgeInsets.only(top: 24 + headerHeight + 20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (var i = 0; i < benefits.length; i++) ...[
            if (i > 0) const SizedBox(height: 12),
            SizedBox(
              height: 48,
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text(
                  benefits[i],
                  style: GoogleFonts.figtree(
                    fontSize: 15,
                    fontWeight: FontWeight.w600,
                    color: _navy,
                  ),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

enum _TierVisualStyle { outlined, filled }

class _TierCard extends StatelessWidget {
  const _TierCard({
    required this.title,
    required this.subtitle,
    required this.priceLabel,
    required this.pricePeriod,
    required this.style,
    required this.benefitCount,
    this.headerHeight = 148,
    this.badge,
    this.benefitLabels,
  });

  final String title;
  final String subtitle;
  final String priceLabel;
  final String pricePeriod;
  final _TierVisualStyle style;
  final int benefitCount;
  final double headerHeight;
  final String? badge;
  final List<String>? benefitLabels;

  bool get _filled => style == _TierVisualStyle.filled;

  @override
  Widget build(BuildContext context) {
    final titleColor = _filled ? Colors.white : _navy;
    final subtitleColor = _filled ? Colors.white70 : Colors.black54;
    final priceColor = _filled ? Colors.white : _navy;
    final periodColor = _filled ? Colors.white70 : Colors.black54;
    final blankBorder = _filled
        ? Colors.white.withValues(alpha: 0.35)
        : _gold.withValues(alpha: 0.55);
    final blankFill = _filled
        ? Colors.white.withValues(alpha: 0.08)
        : Colors.transparent;

    return Container(
      padding: const EdgeInsets.fromLTRB(20, 24, 20, 24),
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
        border: _filled ? null : Border.all(color: _gold, width: 2),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            height: headerHeight,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (badge != null)
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                    decoration: BoxDecoration(
                      color: _gold,
                      borderRadius: BorderRadius.circular(20),
                    ),
                    child: Text(
                      badge!,
                      style: GoogleFonts.figtree(
                        fontSize: 11,
                        fontWeight: FontWeight.bold,
                        color: _navy,
                      ),
                    ),
                  )
                else
                  const SizedBox(height: 23),
                const SizedBox(height: 12),
                Text(
                  title,
                  style: GoogleFonts.figtree(
                    fontSize: 22,
                    fontWeight: FontWeight.bold,
                    color: titleColor,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  subtitle,
                  style: GoogleFonts.figtree(fontSize: 13, color: subtitleColor),
                ),
                const Spacer(),
                Row(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(
                      priceLabel,
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
                        pricePeriod,
                        style: GoogleFonts.figtree(fontSize: 13, color: periodColor),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                Container(height: 2, width: 40, color: _gold),
              ],
            ),
          ),
          const SizedBox(height: 20),
          for (var i = 0; i < benefitCount; i++) ...[
            if (i > 0) const SizedBox(height: 12),
            SizedBox(
              height: 48,
              child: Row(
                children: [
                  Expanded(
                    child: Container(
                      height: 48,
                      decoration: BoxDecoration(
                        color: blankFill,
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: blankBorder, width: 1.5),
                      ),
                    ),
                  ),
                  if (benefitLabels != null) ...[
                    const SizedBox(width: 12),
                    SizedBox(
                      width: 140,
                      child: Text(
                        benefitLabels![i],
                        style: GoogleFonts.figtree(
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                          color: _filled ? Colors.white : _navy,
                        ),
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ],
        ],
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
