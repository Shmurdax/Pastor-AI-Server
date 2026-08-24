import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/l10n/app_locale.dart';
import 'package:flutter_application_1/data/media_catalog.dart';
import 'package:flutter_application_1/models/media_item.dart';
import 'package:flutter_application_1/screens/prayer_inbox_screen.dart';
import 'package:flutter_application_1/screens/subscriptions_screen.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_application_1/widgets/account_profile_chip.dart';
import 'package:flutter_application_1/widgets/language_selector.dart';
import 'package:flutter_application_1/widgets/church_events_nav_overlay.dart';
import 'package:flutter_application_1/widgets/nordins_ai_nav_menu.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:video_player/video_player.dart';

const _navy = Color(0xFF1B264F);
const _gold = Color(0xFFD4AF37);
const _surface = Color(0xFFF4F4F9);

/// Patreon-style media library for The NORDINS Daily Devotionals (video).
/// Catalog is mock/placeholder until real media is ingested.
class MediaLibraryScreen extends StatefulWidget {
  const MediaLibraryScreen({super.key});

  @override
  State<MediaLibraryScreen> createState() => _MediaLibraryScreenState();
}

class _MediaLibraryScreenState extends State<MediaLibraryScreen> {
  static const _filterYears = [2026, 2025, 2024, 2023, 2022, 2021, 2020, 2019];

  final _apiService = ApiService();
  final _searchController = TextEditingController();
  bool _eventsOpen = false;

  MediaSortOption _sort = MediaSortOption.newestFirst;
  MediaAccessTier? _tierFilter;
  int? _yearFilter;

  bool get _hasPremiumAccess => context.watch<AuthController>().hasPremiumAccess;

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _launchUrl(String urlString) async {
    final url = Uri.parse(urlString);
    if (await canLaunchUrl(url)) {
      await launchUrl(url, mode: LaunchMode.externalApplication);
    }
  }

  void _openSubscriptions() {
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(builder: (_) => const SubscriptionsScreen()),
    );
  }

  void _openPrayerInbox() {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => PrayerInboxScreen(apiService: _apiService),
      ),
    );
  }

  void _goToAiHome() {
    Navigator.of(context).popUntil((route) => route.isFirst);
  }

  void _toggleEvents({bool? open}) {
    setState(() => _eventsOpen = open ?? !_eventsOpen);
  }

  /// Video catalog. Premium episodes stay visible and locked for free accounts.
  List<MediaItem> get _accessibleItems {
    return MediaCatalog.allItems
        .where((item) => item.contentType == MediaContentType.video)
        .toList();
  }

  List<MediaItem> get _filteredItems {
    final query = _searchController.text.trim().toLowerCase();
    var items = _accessibleItems.where((item) {
      if (_tierFilter != null && item.accessTier != _tierFilter) return false;
      if (_yearFilter != null && item.publishedAt.year != _yearFilter) return false;
      if (query.isEmpty) return true;
      final haystack = [
        item.title,
        item.description,
        ...item.tags,
        kMediaCollectionLabel,
      ].join(' ').toLowerCase();
      return haystack.contains(query);
    }).toList();

    switch (_sort) {
      case MediaSortOption.newestFirst:
        items.sort((a, b) => b.publishedAt.compareTo(a.publishedAt));
      case MediaSortOption.oldestFirst:
        items.sort((a, b) => a.publishedAt.compareTo(b.publishedAt));
      case MediaSortOption.titleAZ:
        items.sort((a, b) => a.title.toLowerCase().compareTo(b.title.toLowerCase()));
    }
    return items;
  }

  int get _activeFilterCount {
    var n = 0;
    if (_tierFilter != null) n++;
    if (_yearFilter != null) n++;
    return n;
  }

  void _clearFilters() {
    setState(() {
      _tierFilter = null;
      _yearFilter = null;
    });
  }

  void _openItem(MediaItem item) {
    final hasPremiumAccess = context.read<AuthController>().hasPremiumAccess;
    if (item.isLockedForUser(hasPremiumAccess: hasPremiumAccess)) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            'This episode is for Premium members. Subscribe to unlock the full library.',
            style: GoogleFonts.figtree(),
          ),
          action: SnackBarAction(
            label: 'Subscribe',
            onPressed: _openSubscriptions,
          ),
          duration: const Duration(seconds: 5),
        ),
      );
      return;
    }
    if (item.isPlayable) {
      Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => _WatchEpisodeScreen(item: item),
        ),
      );
      return;
    }
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          'This episode is coming soon.',
          style: GoogleFonts.figtree(),
        ),
      ),
    );
  }

  Future<void> _openFilterSheet() async {
    var tier = _tierFilter;
    var year = _yearFilter;

    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.white,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) {
        return StatefulBuilder(
          builder: (context, setSheetState) {
            return Padding(
              padding: EdgeInsets.fromLTRB(
                24,
                16,
                24,
                24 + MediaQuery.of(context).viewInsets.bottom,
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Center(
                    child: Container(
                      width: 40,
                      height: 4,
                      decoration: BoxDecoration(
                        color: Colors.black26,
                        borderRadius: BorderRadius.circular(2),
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                  Text(
                    'Filters',
                    style: GoogleFonts.figtree(
                      fontSize: 20,
                      fontWeight: FontWeight.bold,
                      color: _navy,
                    ),
                  ),
                  const SizedBox(height: 20),
                  Text('Access', style: _sheetLabelStyle()),
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 8,
                    children: [
                      _FilterChip(
                        label: 'All',
                        selected: tier == null,
                        onTap: () => setSheetState(() => tier = null),
                      ),
                      _FilterChip(
                        label: 'Free preview',
                        selected: tier == MediaAccessTier.freePreview,
                        onTap: () => setSheetState(() => tier = MediaAccessTier.freePreview),
                      ),
                      _FilterChip(
                        label: 'Premium',
                        selected: tier == MediaAccessTier.premium,
                        onTap: () => setSheetState(() => tier = MediaAccessTier.premium),
                      ),
                    ],
                  ),
                  const SizedBox(height: 20),
                  Text('Year', style: _sheetLabelStyle()),
                  const SizedBox(height: 8),
                  DropdownButtonFormField<int?>(
                    value: year,
                    decoration: _dropdownDecoration(),
                    items: [
                      const DropdownMenuItem<int?>(
                        value: null,
                        child: Text('Any year'),
                      ),
                      ..._filterYears.map(
                        (y) => DropdownMenuItem<int?>(
                          value: y,
                          child: Text('$y'),
                        ),
                      ),
                    ],
                    onChanged: (v) => setSheetState(() => year = v),
                  ),
                  const SizedBox(height: 24),
                  Row(
                    children: [
                      TextButton(
                        onPressed: () {
                          setSheetState(() {
                            tier = null;
                            year = null;
                          });
                        },
                        child: Text('Clear all', style: GoogleFonts.figtree(color: _navy)),
                      ),
                      const Spacer(),
                      FilledButton(
                        onPressed: () {
                          setState(() {
                            _tierFilter = tier;
                            _yearFilter = year;
                          });
                          Navigator.pop(ctx);
                        },
                        style: FilledButton.styleFrom(
                          backgroundColor: _navy,
                          padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 14),
                        ),
                        child: Text('Apply', style: GoogleFonts.figtree(fontWeight: FontWeight.bold)),
                      ),
                    ],
                  ),
                ],
              ),
            );
          },
        );
      },
    );
  }

  TextStyle _sheetLabelStyle() => GoogleFonts.figtree(
        fontSize: 13,
        fontWeight: FontWeight.w600,
        color: Colors.black54,
        letterSpacing: 0.3,
      );

  InputDecoration _dropdownDecoration() => InputDecoration(
        filled: true,
        fillColor: _surface,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide.none,
        ),
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      );

  @override
  Widget build(BuildContext context) {
    final screenWidth = MediaQuery.of(context).size.width;
    final isMobileOrTablet = screenWidth < 1024;
    final isMobile = screenWidth < 600;
    final items = _filteredItems;
    final useGrid = screenWidth >= 720;
    final auth = context.watch<AuthController>();
    final s = context.watch<LocaleController>().strings;
    final hasPremiumAccess = auth.hasPremiumAccess;

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
              onOpenSubscriptions: _openSubscriptions,
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
                  _NavButton(label: s.home, onTap: () => _launchUrl('https://thenordins.org/')),
                  _NavButton(label: s.store, onTap: () => _launchUrl('https://thenordins.org/store')),
                  _NavButton(
                    label: s.events,
                    onTap: () => _toggleEvents(open: true),
                    active: _eventsOpen,
                  ),
                  NordinsAiNavMenu(
                    onAiHome: _goToAiHome,
                    onMedia: () => _toggleEvents(open: false),
                    onSubscribe: _openSubscriptions,
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
                icon: Icon(Icons.event_outlined, color: _eventsOpen ? _gold : _navy),
              ),
            ),
        ],
      ),
      body: Stack(
        children: [
          SafeArea(
            child: CustomScrollView(
              slivers: [
                SliverToBoxAdapter(
                  child: Padding(
                    padding: EdgeInsets.fromLTRB(
                      isMobile ? 16 : 32,
                      isMobile ? 16 : 28,
                      isMobile ? 16 : 32,
                      0,
                    ),
                    child: Center(
                      child: ConstrainedBox(
                        constraints: const BoxConstraints(maxWidth: 1100),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            _CreatorHeader(
                              onSubscribe: _openSubscriptions,
                              hasPremiumAccess: hasPremiumAccess,
                            ),
                            const SizedBox(height: 28),
                            _SearchBar(
                              controller: _searchController,
                              onChanged: (_) => setState(() {}),
                            ),
                            const SizedBox(height: 16),
                            _ToolbarRow(
                              sort: _sort,
                              onSortChanged: (v) => setState(() => _sort = v),
                              filterCount: _activeFilterCount,
                              onFilterTap: _openFilterSheet,
                              resultCount: items.length,
                            ),
                            if (_activeFilterCount > 0) ...[
                              const SizedBox(height: 12),
                              Wrap(
                                spacing: 8,
                                runSpacing: 8,
                                children: [
                                  if (_tierFilter != null)
                                    _ActiveFilterPill(
                                      label: _tierFilter == MediaAccessTier.premium
                                          ? 'Premium'
                                          : 'Free preview',
                                      onRemove: () => setState(() => _tierFilter = null),
                                    ),
                                  if (_yearFilter != null)
                                    _ActiveFilterPill(
                                      label: '$_yearFilter',
                                      onRemove: () => setState(() => _yearFilter = null),
                                    ),
                                  TextButton(
                                    onPressed: _clearFilters,
                                    child: Text(
                                      'Clear filters',
                                      style: GoogleFonts.figtree(
                                        color: _navy,
                                        fontWeight: FontWeight.w600,
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                            ],
                            const SizedBox(height: 24),
                            Text(
                              kMediaCollectionLabel,
                              style: GoogleFonts.figtree(
                                fontSize: 18,
                                fontWeight: FontWeight.bold,
                                color: _navy,
                              ),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              _hasPremiumAccess
                                  ? '${_sort.label} · ${MediaCatalog.allItems.length} devotionals in catalog'
                                  : 'Free preview · Subscribe to unlock the full library',
                              style: GoogleFonts.figtree(fontSize: 13, color: Colors.black45),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
                if (items.isEmpty)
                  SliverFillRemaining(
                    hasScrollBody: false,
                    child: Center(
                      child: Padding(
                        padding: const EdgeInsets.all(32),
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Icon(Icons.search_off, size: 48, color: _navy.withValues(alpha: 0.35)),
                            const SizedBox(height: 16),
                            Text(
                              'No posts match your filters',
                              style: GoogleFonts.figtree(
                                fontSize: 18,
                                fontWeight: FontWeight.w600,
                                color: _navy,
                              ),
                            ),
                            const SizedBox(height: 8),
                            Text(
                              'Try clearing filters or searching with different keywords.',
                              textAlign: TextAlign.center,
                              style: GoogleFonts.figtree(color: Colors.black54),
                            ),
                            const SizedBox(height: 16),
                            OutlinedButton(
                              onPressed: () {
                                _searchController.clear();
                                _clearFilters();
                                setState(() {});
                              },
                              style: OutlinedButton.styleFrom(
                                foregroundColor: _navy,
                                side: BorderSide(color: _gold.withValues(alpha: 0.6)),
                              ),
                              child: const Text('Reset search & filters'),
                            ),
                          ],
                        ),
                      ),
                    ),
                  )
                else if (items.length == 1)
                  SliverPadding(
                    padding: EdgeInsets.fromLTRB(isMobile ? 16 : 32, 8, isMobile ? 16 : 32, 32),
                    sliver: SliverToBoxAdapter(
                      child: Center(
                        child: ConstrainedBox(
                          constraints: const BoxConstraints(maxWidth: 560),
                          child: _MediaPostCard(
                            item: items.first,
                            hasPremiumAccess: hasPremiumAccess,
                            onTap: () => _openItem(items.first),
                          ),
                        ),
                      ),
                    ),
                  )
                else if (useGrid)
                  SliverPadding(
                    padding: EdgeInsets.fromLTRB(isMobile ? 16 : 32, 0, isMobile ? 16 : 32, 32),
                    sliver: SliverGrid(
                      gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                        crossAxisCount: screenWidth >= 1100 ? 3 : 2,
                        mainAxisSpacing: 20,
                        crossAxisSpacing: 20,
                        childAspectRatio: 0.82,
                      ),
                      delegate: SliverChildBuilderDelegate(
                        (context, index) => _MediaPostCard(
                          item: items[index],
                          compact: true,
                          hasPremiumAccess: hasPremiumAccess,
                          onTap: () => _openItem(items[index]),
                        ),
                        childCount: items.length,
                      ),
                    ),
                  )
                else
                  SliverPadding(
                    padding: EdgeInsets.fromLTRB(isMobile ? 16 : 32, 0, isMobile ? 16 : 32, 32),
                    sliver: SliverList(
                      delegate: SliverChildBuilderDelegate(
                        (context, index) => Padding(
                          padding: const EdgeInsets.only(bottom: 16),
                          child: _MediaPostCard(
                            item: items[index],
                            hasPremiumAccess: hasPremiumAccess,
                            onTap: () => _openItem(items[index]),
                          ),
                        ),
                        childCount: items.length,
                      ),
                    ),
                  ),
              ],
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

class _CreatorHeader extends StatelessWidget {
  const _CreatorHeader({
    required this.onSubscribe,
    required this.hasPremiumAccess,
  });

  final VoidCallback onSubscribe;
  final bool hasPremiumAccess;

  @override
  Widget build(BuildContext context) {
    final stats = MediaCatalog.stats;
    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: _surface,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: _navy.withValues(alpha: 0.08)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Image.asset(
                'assets/images/nordins_transparent_logo.png',
                width: 72,
                height: 72,
                fit: BoxFit.contain,
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'The NORDINS',
                      style: GoogleFonts.figtree(
                        fontSize: 26,
                        fontWeight: FontWeight.bold,
                        color: _navy,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      MediaCatalog.creatorTagline,
                      style: GoogleFonts.figtree(fontSize: 14, color: Colors.black54),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 20),
          Wrap(
            spacing: 12,
            runSpacing: 8,
            children: [
              _StatChip(
                icon: Icons.video_library_outlined,
                label: '${stats.totalPosts} posts on Patreon',
              ),
              _StatChip(
                icon: Icons.people_outline,
                label: '${stats.memberCount} members',
              ),
              _StatChip(
                icon: Icons.workspace_premium_outlined,
                label: 'Starting at ${stats.startingPriceLabel}',
              ),
            ],
          ),
          const SizedBox(height: 20),
          Text(
            'This library hosts Daily Devotionals from The NORDINS Patreon. '
            'Full catalog sync is coming soon — browse, filter, and search now '
            'to preview the experience.',
            style: GoogleFonts.figtree(fontSize: 14, height: 1.5, color: Colors.black87),
          ),
          if (!hasPremiumAccess) ...[
            const SizedBox(height: 16),
            FilledButton.icon(
              onPressed: onSubscribe,
              icon: const Icon(Icons.lock_open_outlined, size: 18),
              label: Text(
                'Unlock with Premium',
                style: GoogleFonts.figtree(fontWeight: FontWeight.bold),
              ),
              style: FilledButton.styleFrom(
                backgroundColor: _navy,
                padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _StatChip extends StatelessWidget {
  const _StatChip({required this.icon, required this.label});

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: _gold.withValues(alpha: 0.45)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 16, color: _navy),
          const SizedBox(width: 6),
          Text(
            label,
            style: GoogleFonts.figtree(fontSize: 12, fontWeight: FontWeight.w600, color: _navy),
          ),
        ],
      ),
    );
  }
}

class _SearchBar extends StatelessWidget {
  const _SearchBar({required this.controller, required this.onChanged});

  final TextEditingController controller;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      onChanged: onChanged,
      decoration: InputDecoration(
        hintText: 'Search posts by title, topic, or tag…',
        hintStyle: GoogleFonts.figtree(color: Colors.black38),
        prefixIcon: const Icon(Icons.search, color: _navy),
        filled: true,
        fillColor: _surface,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: BorderSide.none,
        ),
        contentPadding: const EdgeInsets.symmetric(vertical: 14),
      ),
    );
  }
}

class _ToolbarRow extends StatelessWidget {
  const _ToolbarRow({
    required this.sort,
    required this.onSortChanged,
    required this.filterCount,
    required this.onFilterTap,
    required this.resultCount,
  });

  final MediaSortOption sort;
  final ValueChanged<MediaSortOption> onSortChanged;
  final int filterCount;
  final VoidCallback onFilterTap;
  final int resultCount;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: DropdownButtonHideUnderline(
            child: DropdownButton<MediaSortOption>(
              value: sort,
              isExpanded: true,
              icon: const Icon(Icons.keyboard_arrow_down, color: _navy),
              style: GoogleFonts.figtree(color: _navy, fontWeight: FontWeight.w600),
              items: MediaSortOption.values
                  .map(
                    (o) => DropdownMenuItem(
                      value: o,
                      child: Text(o.label),
                    ),
                  )
                  .toList(),
              onChanged: (v) {
                if (v != null) onSortChanged(v);
              },
            ),
          ),
        ),
        const SizedBox(width: 8),
        OutlinedButton.icon(
          onPressed: onFilterTap,
          icon: Badge(
            isLabelVisible: filterCount > 0,
            label: Text('$filterCount'),
            child: const Icon(Icons.tune, size: 18),
          ),
          label: Text('Filters', style: GoogleFonts.figtree(fontWeight: FontWeight.w600)),
          style: OutlinedButton.styleFrom(
            foregroundColor: _navy,
            side: BorderSide(color: _navy.withValues(alpha: 0.2)),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          ),
        ),
        const SizedBox(width: 8),
        Text(
          '$resultCount shown',
          style: GoogleFonts.figtree(fontSize: 13, color: Colors.black45),
        ),
      ],
    );
  }
}

class _FilterChip extends StatelessWidget {
  const _FilterChip({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return FilterChip(
      label: Text(label),
      selected: selected,
      onSelected: (_) => onTap(),
      selectedColor: _gold.withValues(alpha: 0.35),
      checkmarkColor: _navy,
      labelStyle: GoogleFonts.figtree(
        color: selected ? _navy : Colors.black87,
        fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
      ),
      side: BorderSide(color: selected ? _gold : Colors.black26),
    );
  }
}

class _ActiveFilterPill extends StatelessWidget {
  const _ActiveFilterPill({required this.label, required this.onRemove});

  final String label;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    return InputChip(
      label: Text(label, style: GoogleFonts.figtree(fontSize: 12)),
      deleteIcon: const Icon(Icons.close, size: 16),
      onDeleted: onRemove,
      backgroundColor: _gold.withValues(alpha: 0.2),
      side: BorderSide(color: _gold.withValues(alpha: 0.5)),
    );
  }
}

class _MediaPostCard extends StatelessWidget {
  const _MediaPostCard({
    required this.item,
    required this.onTap,
    required this.hasPremiumAccess,
    this.compact = false,
  });

  final MediaItem item;
  final VoidCallback onTap;
  final bool hasPremiumAccess;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final locked = item.isLockedForUser(hasPremiumAccess: hasPremiumAccess);

    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(16),
        child: Ink(
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: _navy.withValues(alpha: 0.1)),
            color: Colors.white,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              ClipRRect(
                borderRadius: const BorderRadius.vertical(top: Radius.circular(16)),
                child: AspectRatio(
                  aspectRatio: 16 / 9,
                  child: Stack(
                    fit: StackFit.expand,
                    children: [
                      Container(
                        decoration: BoxDecoration(
                          gradient: LinearGradient(
                            colors: [
                              _navy,
                              _navy.withValues(alpha: 0.75),
                            ],
                            begin: Alignment.topLeft,
                            end: Alignment.bottomRight,
                          ),
                        ),
                      ),
                      Center(
                        child: Icon(
                          locked ? Icons.lock_outline : Icons.play_circle_filled,
                          size: compact ? 48 : 64,
                          color: _gold.withValues(alpha: 0.95),
                        ),
                      ),
                      const Positioned(
                        left: 10,
                        top: 10,
                        child: _Badge(label: 'Video'),
                      ),
                      if (item.accessTier == MediaAccessTier.premium)
                        Positioned(
                          right: 10,
                          top: 10,
                          child: _Badge(
                            label: locked ? 'Premium' : 'Member',
                            highlight: locked,
                          ),
                        ),
                      if (item.durationLabel != null)
                        Positioned(
                          right: 10,
                          bottom: 10,
                          child: Container(
                            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                            decoration: BoxDecoration(
                              color: Colors.black54,
                              borderRadius: BorderRadius.circular(6),
                            ),
                            child: Text(
                              item.durationLabel!,
                              style: GoogleFonts.figtree(
                                color: Colors.white,
                                fontSize: 11,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
              ),
              if (compact)
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: _MediaPostCardBody(
                      item: item,
                      compact: true,
                      locked: locked,
                    ),
                  ),
                )
              else
                Padding(
                  padding: const EdgeInsets.all(18),
                  child: _MediaPostCardBody(
                    item: item,
                    compact: false,
                    locked: locked,
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _MediaPostCardBody extends StatelessWidget {
  const _MediaPostCardBody({
    required this.item,
    required this.compact,
    required this.locked,
  });

  final MediaItem item;
  final bool compact;
  final bool locked;

  @override
  Widget build(BuildContext context) {
    final dateLabel = DateFormat.yMMMd().format(item.publishedAt);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          item.title,
          maxLines: compact ? 2 : 3,
          overflow: TextOverflow.ellipsis,
          style: GoogleFonts.figtree(
            fontSize: compact ? 15 : 18,
            fontWeight: FontWeight.bold,
            color: _navy,
          ),
        ),
        SizedBox(height: compact ? 4 : 8),
        Text(
          item.description,
          maxLines: compact ? 2 : 3,
          overflow: TextOverflow.ellipsis,
          style: GoogleFonts.figtree(
            fontSize: compact ? 12 : 13,
            height: 1.4,
            color: Colors.black54,
          ),
        ),
        if (compact) const Spacer(),
        if (!compact) const SizedBox(height: 12),
        Row(
          children: [
            Text(
              kMediaCollectionLabel,
              style: GoogleFonts.figtree(
                fontSize: 11,
                fontWeight: FontWeight.w600,
                color: _gold,
              ),
            ),
            const Spacer(),
            Text(
              dateLabel,
              style: GoogleFonts.figtree(fontSize: 11, color: Colors.black45),
            ),
          ],
        ),
        if (locked) ...[
          const SizedBox(height: 6),
          Text(
            'Premium members only',
            style: GoogleFonts.figtree(
              fontSize: 11,
              fontWeight: FontWeight.w600,
              color: Colors.black38,
            ),
          ),
        ] else if (!item.isPlayable) ...[
          const SizedBox(height: 6),
          Text(
            'Coming soon',
            style: GoogleFonts.figtree(
              fontSize: 11,
              fontWeight: FontWeight.w600,
              color: Colors.black38,
            ),
          ),
        ],
      ],
    );
  }
}

class _Badge extends StatelessWidget {
  const _Badge({required this.label, this.highlight = false});

  final String label;
  final bool highlight;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: highlight ? _gold.withValues(alpha: 0.9) : Colors.black54,
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        label,
        style: GoogleFonts.figtree(
          color: highlight ? _navy : Colors.white,
          fontSize: 10,
          fontWeight: FontWeight.bold,
        ),
      ),
    );
  }
}

class _WatchEpisodeScreen extends StatefulWidget {
  const _WatchEpisodeScreen({required this.item});

  final MediaItem item;

  @override
  State<_WatchEpisodeScreen> createState() => _WatchEpisodeScreenState();
}

class _WatchEpisodeScreenState extends State<_WatchEpisodeScreen> {
  late final VideoPlayerController _controller;
  late final Future<void> _initializeFuture;
  bool _showControls = true;

  @override
  void initState() {
    super.initState();
    _controller = VideoPlayerController.asset(widget.item.videoAssetPath!);
    _initializeFuture = _controller.initialize().then((_) {
      if (!mounted) return;
      setState(() {});
      _controller.play();
    });
    _controller.addListener(() {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  String _formatDuration(Duration d) {
    final m = d.inMinutes.remainder(60).toString().padLeft(1, '0');
    final s = d.inSeconds.remainder(60).toString().padLeft(2, '0');
    return '$m:$s';
  }

  @override
  Widget build(BuildContext context) {
    final isMobile = MediaQuery.of(context).size.width < 600;

    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        backgroundColor: Colors.white,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, color: _navy),
          onPressed: () => Navigator.of(context).pop(),
        ),
        title: Text(
          'Now playing',
          style: GoogleFonts.figtree(color: _navy, fontWeight: FontWeight.bold),
        ),
      ),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: EdgeInsets.symmetric(horizontal: isMobile ? 16 : 32, vertical: 16),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 900),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  ClipRRect(
                    borderRadius: BorderRadius.circular(12),
                    child: AspectRatio(
                      aspectRatio: 16 / 9,
                      child: ColoredBox(
                        color: Colors.black,
                        child: FutureBuilder<void>(
                          future: _initializeFuture,
                          builder: (context, snapshot) {
                            if (snapshot.connectionState != ConnectionState.done) {
                              return const Center(
                                child: CircularProgressIndicator(color: _gold),
                              );
                            }
                            if (snapshot.hasError) {
                              return Center(
                                child: Text(
                                  'Unable to load video.',
                                  style: GoogleFonts.figtree(color: Colors.white70),
                                ),
                              );
                            }
                            return GestureDetector(
                              onTap: () => setState(() => _showControls = !_showControls),
                              child: Stack(
                                alignment: Alignment.center,
                                children: [
                                  FittedBox(
                                    fit: BoxFit.contain,
                                    child: SizedBox(
                                      width: _controller.value.size.width,
                                      height: _controller.value.size.height,
                                      child: VideoPlayer(_controller),
                                    ),
                                  ),
                                  if (_showControls) ...[
                                    IconButton(
                                      iconSize: 64,
                                      color: Colors.white,
                                      onPressed: () {
                                        setState(() {
                                          if (_controller.value.isPlaying) {
                                            _controller.pause();
                                          } else {
                                            _controller.play();
                                          }
                                        });
                                      },
                                      icon: Icon(
                                        _controller.value.isPlaying
                                            ? Icons.pause_circle_filled
                                            : Icons.play_circle_filled,
                                      ),
                                    ),
                                    Positioned(
                                      left: 12,
                                      right: 12,
                                      bottom: 12,
                                      child: Column(
                                        children: [
                                          VideoProgressIndicator(
                                            _controller,
                                            allowScrubbing: true,
                                            colors: const VideoProgressColors(
                                              playedColor: _gold,
                                              bufferedColor: Colors.white38,
                                              backgroundColor: Colors.white24,
                                            ),
                                          ),
                                          const SizedBox(height: 4),
                                          Align(
                                            alignment: Alignment.centerRight,
                                            child: Text(
                                              '${_formatDuration(_controller.value.position)} / '
                                              '${_formatDuration(_controller.value.duration)}',
                                              style: GoogleFonts.figtree(
                                                color: Colors.white70,
                                                fontSize: 12,
                                              ),
                                            ),
                                          ),
                                        ],
                                      ),
                                    ),
                                  ],
                                ],
                              ),
                            );
                          },
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: 24),
                  Text(
                    widget.item.title,
                    style: GoogleFonts.figtree(
                      fontSize: isMobile ? 22 : 28,
                      fontWeight: FontWeight.bold,
                      color: _navy,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    widget.item.description,
                    style: GoogleFonts.figtree(fontSize: 15, height: 1.45, color: Colors.black54),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _NavButton extends StatefulWidget {
  const _NavButton({required this.label, this.onTap, this.active = false});

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
