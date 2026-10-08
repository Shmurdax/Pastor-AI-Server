import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/data/media_catalog.dart';
import 'package:flutter_application_1/l10n/app_locale.dart';
import 'package:flutter_application_1/l10n/app_strings.dart';
import 'package:flutter_application_1/models/episode_note.dart';
import 'package:flutter_application_1/models/media_item.dart';
import 'package:flutter_application_1/screens/subscriptions_screen.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_application_1/widgets/chat_nav_actions.dart';
import 'package:flutter_application_1/widgets/church_events_nav_overlay.dart';
import 'package:flutter_application_1/episode_note_text.dart';
import 'package:flutter_application_1/widgets/episode_notes_pane.dart';
import 'package:flutter_application_1/widgets/pdf_viewer_embed.dart';
import 'package:flutter_application_1/widgets/vimeo_player_embed.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:video_player/video_player.dart';

const _navy = Color(0xFF1B264F);
const _gold = Color(0xFFD4AF37);
const _surface = Color(0xFFF4F4F9);

/// Tight caption strip under the 16:9 thumbnail (title and date).
const kMediaTileCaptionHeight = 84.0;

/// Extra room when a search snippet is shown under the title.
const kMediaTileCaptionHeightWithSnippet = 132.0;

/// Aspect ratio for a media grid cell so the video fills most of the tile.
double mediaGridChildAspectRatio({
  required double viewportWidth,
  required int crossAxisCount,
  required double horizontalPadding,
  double crossAxisSpacing = 20,
  double captionHeight = kMediaTileCaptionHeight,
}) {
  final gaps = crossAxisSpacing * (crossAxisCount - 1);
  final tileWidth = (viewportWidth - horizontalPadding - gaps) / crossAxisCount;
  if (tileWidth <= 1) return 16 / 10;
  return tileWidth / (tileWidth * 9 / 16 + captionHeight);
}

/// Patreon-style media library for The NORDINS Walk through the Word (video).
/// Catalog loads from GET /api/media/ (Vimeo sync).
class MediaLibraryScreen extends StatefulWidget {
  const MediaLibraryScreen({
    super.key,
    this.openVimeoId,
    this.openSeekSeconds,
    @visibleForTesting ApiService? apiService,
  }) : _injectedApi = apiService;

  /// When set, open this Vimeo episode after the catalog loads (chat source tap).
  final String? openVimeoId;

  /// Optional start offset in seconds for [openVimeoId] (Vimeo `#t=` seek).
  final int? openSeekSeconds;

  final ApiService? _injectedApi;

  @override
  State<MediaLibraryScreen> createState() => _MediaLibraryScreenState();
}

class _MediaLibraryScreenState extends State<MediaLibraryScreen> {
  static const _filterYears = [2026, 2025, 2024, 2023, 2022, 2021, 2020, 2019];

  late final ApiService _apiService = widget._injectedApi ?? ApiService();
  final _searchController = TextEditingController();
  Timer? _searchDebounce;
  bool _eventsOpen = false;
  late final VoidCallback _onPageChange = _closeEventsForPageChange;
  bool _catalogLoading = true;
  bool _openedInitialVideo = false;
  int _catalogRequest = 0;
  List<MediaItem> _catalogItems = const [];
  List<String> _topics = const [];
  String? _topicFilter;

  MediaSortOption _sort = MediaSortOption.newestFirst;
  int? _yearFilter;

  /// Premium unlock from logged-in profile (`is_premium` / staff).
  bool get _hasPremiumAccess => context.watch<AuthController>().hasPremiumAccess;

  @override
  void initState() {
    super.initState();
    AppPageNavigation.addListener(_onPageChange);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _loadCatalog();
      _loadTopics();
    });
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _apiService.setAccessToken(context.read<AuthController>().token);
  }

  @override
  void dispose() {
    AppPageNavigation.removeListener(_onPageChange);
    _searchDebounce?.cancel();
    _searchController.dispose();
    super.dispose();
  }

  void _scheduleSearch() {
    _searchDebounce?.cancel();
    _searchDebounce = Timer(const Duration(milliseconds: 300), () {
      if (mounted) _loadCatalog();
    });
  }

  Future<void> _loadTopics() async {
    final auth = context.read<AuthController>();
    _apiService.setAccessToken(auth.token);
    try {
      final topics = await _apiService.listMediaTopics();
      if (!mounted) return;
      setState(() => _topics = topics);
    } catch (_) {}
  }

  Future<void> _loadCatalog() async {
    final requestId = ++_catalogRequest;
    final auth = context.read<AuthController>();
    _apiService.setAccessToken(auth.token);
    final query = _searchController.text.trim();
    final topic = _topicFilter;
    try {
      final items = await _apiService.listMediaVideos(
        query: query.isEmpty ? null : query,
        topic: topic,
      );
      if (!mounted || requestId != _catalogRequest) return;
      setState(() {
        _catalogItems = items;
        _catalogLoading = false;
      });
    } catch (_) {
      if (!mounted || requestId != _catalogRequest) return;
      setState(() {
        _catalogItems = const [];
        _catalogLoading = false;
      });
    }
    _maybeOpenInitialVideo();
  }

  void _maybeOpenInitialVideo() {
    if (_openedInitialVideo || _catalogLoading) return;
    final targetId = (widget.openVimeoId ?? '').trim();
    if (targetId.isEmpty) return;
    _openedInitialVideo = true;

    MediaItem? inCatalog;
    for (final item in _catalogItems) {
      if ((item.vimeoId ?? '').trim() == targetId) {
        inCatalog = item;
        break;
      }
    }

    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      if (inCatalog == null) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              'That sermon was not found in the media library.',
              style: GoogleFonts.figtree(),
            ),
          ),
        );
        return;
      }
      final item = inCatalog;
      final allowed = _accessibleItems.any(
        (entry) => (entry.vimeoId ?? '').trim() == targetId,
      );
      if (!allowed) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              'This episode is for Premium members. Subscribe to unlock.',
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
      _openItem(item, seekSeconds: widget.openSeekSeconds);
    });
  }

  Future<void> _launchUrl(String urlString) async {
    final url = Uri.parse(urlString);
    if (await canLaunchUrl(url)) {
      await launchUrl(url, mode: LaunchMode.externalApplication);
    }
  }

  void _openSubscriptions() {
    _closeEventsForPageChange();
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(builder: (_) => const SubscriptionsScreen()),
    );
  }

  void _goToAiHome() {
    _closeEventsForPageChange();
    Navigator.of(context).popUntil((route) => route.isFirst);
  }

  void _closeEventsForPageChange() {
    if (!mounted || !_eventsOpen) return;
    setState(() => _eventsOpen = false);
  }

  void _toggleEvents({bool? open}) {
    final auth = context.read<AuthController>();
    _apiService.setAccessToken(auth.token);
    setState(() => _eventsOpen = open ?? !_eventsOpen);
  }

  List<Widget> _mediaNavButtons(AppStrings s) {
    return [
      _NavButton(label: s.home, onTap: () => _launchUrl('https://thenordins.org/')),
      _NavButton(label: s.chat, onTap: _goToAiHome),
      _NavButton(
        label: s.media,
        onTap: () => _toggleEvents(open: false),
        active: true,
      ),
      _NavButton(
        label: s.events,
        onTap: () => _toggleEvents(),
        active: _eventsOpen,
      ),
    ];
  }

  /// Catalog visible for the current access level (video-only).
  List<MediaItem> get _accessibleItems {
    return _catalogItems.where((item) {
      if (item.contentType != MediaContentType.video) return false;
      if (!_hasPremiumAccess && item.accessTier != MediaAccessTier.freePreview) {
        return false;
      }
      return true;
    }).toList();
  }

  List<MediaItem> get _filteredItems {
    var items = _accessibleItems.where((item) {
      if (_yearFilter != null && item.publishedAt.year != _yearFilter) return false;
      return true;
    }).toList();

    final searching = _searchController.text.trim().isNotEmpty;
    items.sort((a, b) {
      if (searching) {
        final rank = a.matchRank.compareTo(b.matchRank);
        if (rank != 0) return rank;
      }
      switch (_sort) {
        case MediaSortOption.newestFirst:
          return b.publishedAt.compareTo(a.publishedAt);
        case MediaSortOption.oldestFirst:
          return a.publishedAt.compareTo(b.publishedAt);
        case MediaSortOption.titleAZ:
          return a.title.toLowerCase().compareTo(b.title.toLowerCase());
      }
    });
    return items;
  }

  int get _activeFilterCount {
    var n = 0;
    if (_yearFilter != null) n++;
    if (_topicFilter != null) n++;
    return n;
  }

  void _clearFilters() {
    final hadTopic = _topicFilter != null;
    setState(() {
      _yearFilter = null;
      _topicFilter = null;
    });
    if (hadTopic) _loadCatalog();
  }

  String get _noteHighlightQuery {
    final query = _searchController.text.trim();
    if (query.isNotEmpty) return query;
    return _topicFilter ?? '';
  }

  void _openItem(MediaItem item, {int? seekSeconds}) {
    if (item.isPlayable) {
      _closeEventsForPageChange();
      Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => WatchEpisodeScreen(
            item: item,
            startSeconds: seekSeconds,
            highlightQuery: _noteHighlightQuery,
            apiService: _apiService,
          ),
        ),
      );
      return;
    }
    if (item.accessTier == MediaAccessTier.premium) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            'This episode is for Premium members. Subscribe to unlock when media goes live.',
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
    var year = _yearFilter;
    var topic = _topicFilter;

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
            return SingleChildScrollView(
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
                  if (_topics.isNotEmpty) ...[
                    const SizedBox(height: 20),
                    Text('Topic', style: _sheetLabelStyle()),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        for (final item in _topics)
                          _FilterChip(
                            label: displayTopicLabel(item),
                            selected: topic == item,
                            onTap: () => setSheetState(() {
                              topic = topic == item ? null : item;
                            }),
                          ),
                      ],
                    ),
                  ],
                  const SizedBox(height: 24),
                  Row(
                    children: [
                      TextButton(
                        onPressed: () {
                          setSheetState(() {
                            year = null;
                            topic = null;
                          });
                        },
                        child: Text('Clear all', style: GoogleFonts.figtree(color: _navy)),
                      ),
                      const Spacer(),
                      FilledButton(
                        onPressed: () {
                          final topicChanged = _topicFilter != topic;
                          setState(() {
                            _yearFilter = year;
                            _topicFilter = topic;
                          });
                          Navigator.pop(ctx);
                          if (topicChanged) _loadCatalog();
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
    final auth = context.watch<AuthController>();
    _apiService.setAccessToken(auth.token);
    final screenWidth = MediaQuery.of(context).size.width;
    final isMobileOrTablet = screenWidth < 1024;
    final isMobile = screenWidth < 600;
    final items = _filteredItems;
    final useGrid = screenWidth >= 720;
    final s = context.watch<LocaleController>().strings;

    final logo = GestureDetector(
      onTap: () => _launchUrl('https://thenordins.org/'),
      child: MouseRegion(
        cursor: SystemMouseCursors.click,
        child: Image.asset(
          'assets/images/nordins_main_logo.png',
          height: isMobile ? 72 : (isMobileOrTablet ? 80 : 95),
          fit: BoxFit.contain,
        ),
      ),
    );

    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        centerTitle: false,
        backgroundColor: Colors.white,
        elevation: 0,
        toolbarHeight: isMobileOrTablet ? 100 : 120,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, color: _navy),
          onPressed: () {
            _closeEventsForPageChange();
            Navigator.of(context).pop();
          },
        ),
        title: isMobile
            ? const SizedBox.shrink()
            : Padding(
                padding: EdgeInsets.only(left: isMobileOrTablet ? 0.0 : 12.0),
                child: logo,
              ),
        flexibleSpace: isMobile
            ? SafeArea(
                child: Align(
                  alignment: Alignment.topCenter,
                  child: SizedBox(
                    height: 100,
                    child: Center(child: logo),
                  ),
                ),
              )
            : null,
        actions: [
          if (!isMobile)
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                ..._mediaNavButtons(s),
                const SizedBox(width: 40),
              ],
            ),
        ],
        bottom: isMobile
            ? PreferredSize(
                preferredSize: const Size.fromHeight(40),
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(8, 0, 8, 6),
                  child: Align(
                    alignment: Alignment.center,
                    child: FittedBox(
                      fit: BoxFit.scaleDown,
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: _mediaNavButtons(s),
                      ),
                    ),
                  ),
                ),
              )
            : null,
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
                            _CreatorHeader(),
                            const SizedBox(height: 28),
                            _SearchBar(
                              controller: _searchController,
                              onChanged: (_) => _scheduleSearch(),
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
                                  if (_yearFilter != null)
                                    _ActiveFilterPill(
                                      label: '$_yearFilter',
                                      onRemove: () => setState(() => _yearFilter = null),
                                    ),
                                  if (_topicFilter != null)
                                    _ActiveFilterPill(
                                      label: displayTopicLabel(_topicFilter!),
                                      onRemove: () {
                                        setState(() => _topicFilter = null);
                                        _loadCatalog();
                                      },
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
                              _catalogLoading
                                  ? 'Loading Walk through the Word…'
                                  : _hasPremiumAccess
                                      ? '${_sort.label} · ${_catalogItems.length} videos in catalog'
                                      : 'Free preview · Subscribe to unlock the full library',
                              style: GoogleFonts.figtree(fontSize: 13, color: Colors.black45),
                            ),
                            const SizedBox(height: 28),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
                if (!_catalogLoading && items.isEmpty)
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
                                _searchDebounce?.cancel();
                                setState(() => _topicFilter = null);
                                _clearFilters();
                                _loadCatalog();
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
                        childAspectRatio: mediaGridChildAspectRatio(
                          viewportWidth: screenWidth,
                          crossAxisCount: screenWidth >= 1100 ? 3 : 2,
                          horizontalPadding: isMobile ? 32 : 64,
                          captionHeight: items.any(
                            (item) => (item.note?.snippet ?? '').trim().isNotEmpty,
                          )
                              ? kMediaTileCaptionHeightWithSnippet
                              : kMediaTileCaptionHeight,
                        ),
                      ),
                      delegate: SliverChildBuilderDelegate(
                        (context, index) => _MediaPostCard(
                          item: items[index],
                          compact: true,
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
              left: 0,
              right: 0,
              child: ChurchEventsNavOverlay(
                apiService: _apiService,
                isStaff: auth.isAuthenticated && (auth.user?.isStaff ?? false),
                onClose: () => _toggleEvents(open: false),
              ),
            ),
        ],
      ),
    );
  }
}

class _CreatorHeader extends StatelessWidget {
  const _CreatorHeader();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: _surface,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: _navy.withValues(alpha: 0.08)),
      ),
      child: Row(
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
        hintText: 'Search videos by title, topic, or keyword…',
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
    this.compact = false,
  });

  final MediaItem item;
  final VoidCallback onTap;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final locked = !item.isPlayable && item.accessTier == MediaAccessTier.premium;

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
                      if (item.thumbnailUrl != null && item.thumbnailUrl!.isNotEmpty)
                        Image.network(
                          item.thumbnailUrl!,
                          fit: BoxFit.cover,
                          errorBuilder: (_, __, ___) => Container(
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
                        )
                      else
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
                      Container(color: Colors.black.withValues(alpha: 0.28)),
                      Center(
                        child: Icon(
                          locked ? Icons.lock_outline : Icons.play_circle_filled,
                          size: compact ? 48 : 64,
                          color: _gold.withValues(alpha: 0.95),
                        ),
                      ),
                      if (item.accessTier == MediaAccessTier.premium)
                        Positioned(
                          right: 10,
                          top: 10,
                          child: _Badge(
                            label: 'Premium',
                            highlight: !item.isPlayable,
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
                Flexible(
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(10, 8, 10, 8),
                    child: _MediaPostCardBody(item: item, compact: true),
                  ),
                )
              else
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 14),
                  child: _MediaPostCardBody(item: item, compact: false),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _MediaPostCardBody extends StatelessWidget {
  const _MediaPostCardBody({required this.item, required this.compact});

  final MediaItem item;
  final bool compact;

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
        if (!compact) ...[
          const SizedBox(height: 8),
          Text(
            item.description,
            maxLines: 3,
            overflow: TextOverflow.ellipsis,
            style: GoogleFonts.figtree(
              fontSize: 13,
              height: 1.4,
              color: Colors.black54,
            ),
          ),
          const SizedBox(height: 12),
        ] else
          const SizedBox(height: 6),
        if ((item.note?.snippet ?? '').trim().isNotEmpty) ...[
          Text(
            item.note!.snippet!,
            maxLines: compact ? 2 : 3,
            overflow: TextOverflow.ellipsis,
            style: GoogleFonts.figtree(
              fontSize: 12,
              height: 1.35,
              color: Colors.black87,
            ),
          ),
          const SizedBox(height: 6),
        ],
        Row(
          children: [
            Expanded(
              child: Text(
                kMediaCollectionLabel,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: GoogleFonts.figtree(
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                  color: _gold,
                ),
              ),
            ),
            const SizedBox(width: 8),
            Text(
              dateLabel,
              style: GoogleFonts.figtree(fontSize: 11, color: Colors.black45),
            ),
          ],
        ),
        if (!compact && !item.isPlayable) ...[
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

class WatchEpisodeScreen extends StatefulWidget {
  const WatchEpisodeScreen({
    super.key,
    required this.item,
    this.startSeconds,
    this.highlightQuery = '',
    this.apiService,
  });

  final MediaItem item;
  final int? startSeconds;
  final String highlightQuery;
  final ApiService? apiService;

  @override
  State<WatchEpisodeScreen> createState() => _WatchEpisodeScreenState();
}

class _WatchEpisodeScreenState extends State<WatchEpisodeScreen> {
  VideoPlayerController? _controller;
  Future<void>? _initializeFuture;
  bool _showControls = true;
  EpisodeNoteDetail? _detail;
  bool _noteLoading = false;
  bool _noteError = false;

  bool get _useVimeo =>
      widget.item.vimeoId != null && widget.item.vimeoId!.trim().isNotEmpty;

  bool get _hasNotes => widget.item.note?.showNotes == true;

  @override
  void initState() {
    super.initState();
    final noteId = widget.item.note?.id;
    if (_hasNotes && noteId != null) {
      _noteLoading = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _loadNote(noteId);
      });
    }
    if (!_useVimeo && widget.item.videoAssetPath != null) {
      final controller = VideoPlayerController.asset(widget.item.videoAssetPath!);
      _controller = controller;
      _initializeFuture = controller.initialize().then((_) {
        if (!mounted) return;
        setState(() {});
        controller.play();
      });
      controller.addListener(() {
        if (mounted) setState(() {});
      });
    }
  }

  @override
  void dispose() {
    _controller?.dispose();
    super.dispose();
  }

  Future<void> _loadNote(int id) async {
    final api = widget.apiService;
    if (api == null) {
      if (!mounted) return;
      setState(() {
        _noteLoading = false;
        _noteError = true;
      });
      return;
    }
    try {
      final detail = await api.getEpisodeNote(id);
      if (!mounted) return;
      setState(() {
        _detail = detail;
        _noteLoading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _noteLoading = false;
        _noteError = true;
      });
    }
  }

  Future<void> _openOriginalPdf() async {
    final note = widget.item.note;
    final api = widget.apiService;
    if (note == null || api == null) return;
    try {
      final bytes = await api.getEpisodeNoteFile(note.id);
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        builder: (ctx) {
          return Dialog(
            insetPadding: const EdgeInsets.all(24),
            child: SizedBox(
              width: 840,
              height: 640,
              child: Column(
                children: [
                  Align(
                    alignment: Alignment.centerRight,
                    child: IconButton(
                      onPressed: () => Navigator.of(ctx).pop(),
                      icon: const Icon(Icons.close, color: _navy),
                    ),
                  ),
                  Expanded(
                    child: PdfViewerEmbed(
                      bytes: bytes,
                      viewKey: 'episode-note-${note.id}',
                    ),
                  ),
                ],
              ),
            ),
          );
        },
      );
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            'Could not open the original notes PDF.',
            style: GoogleFonts.figtree(),
          ),
        ),
      );
    }
  }

  String _formatDuration(Duration d) {
    final m = d.inMinutes.remainder(60).toString().padLeft(1, '0');
    final s = d.inSeconds.remainder(60).toString().padLeft(2, '0');
    return '$m:$s';
  }

  Widget _buildPlayer() {
    if (_useVimeo) {
      return VimeoPlayerEmbed(
        vimeoId: widget.item.vimeoId!.trim(),
        privacyHash: widget.item.vimeoPrivacyHash,
        startSeconds: widget.startSeconds,
      );
    }

    final future = _initializeFuture;
    final controller = _controller;
    if (future == null || controller == null) {
      return Center(
        child: Text(
          'No playable video for this episode.',
          style: GoogleFonts.figtree(color: Colors.white70),
        ),
      );
    }

    return FutureBuilder<void>(
      future: future,
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
                  width: controller.value.size.width,
                  height: controller.value.size.height,
                  child: VideoPlayer(controller),
                ),
              ),
              if (_showControls) ...[
                IconButton(
                  iconSize: 64,
                  color: Colors.white,
                  onPressed: () {
                    setState(() {
                      if (controller.value.isPlaying) {
                        controller.pause();
                      } else {
                        controller.play();
                      }
                    });
                  },
                  icon: Icon(
                    controller.value.isPlaying
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
                        controller,
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
                          '${_formatDuration(controller.value.position)} / '
                          '${_formatDuration(controller.value.duration)}',
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
    );
  }

  Widget _playerCard() {
    return ClipRRect(
      key: const Key('episode-player'),
      borderRadius: BorderRadius.circular(12),
      child: AspectRatio(
        aspectRatio: 16 / 9,
        child: ColoredBox(
          color: Colors.black,
          child: _buildPlayer(),
        ),
      ),
    );
  }

  Widget _heading(bool isMobile, {bool compactDescription = false}) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
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
          maxLines: compactDescription ? 2 : null,
          overflow: compactDescription ? TextOverflow.ellipsis : TextOverflow.clip,
          style: GoogleFonts.figtree(fontSize: 15, height: 1.45, color: Colors.black54),
        ),
      ],
    );
  }

  Widget _notesPane() {
    final note = widget.item.note!;
    return EpisodeNotesPane(
      key: const Key('episode-notes-pane'),
      episodeDate: _detail?.episodeDate ?? note.episodeDate,
      topics: _detail?.topics ?? note.topics,
      body: _detail?.body ?? '',
      loading: _noteLoading,
      error: _noteError,
      highlightQuery: widget.highlightQuery,
      onViewPdf: _openOriginalPdf,
    );
  }

  Widget _buildPlain(bool isMobile) {
    return Center(
      child: SingleChildScrollView(
        padding: EdgeInsets.symmetric(horizontal: isMobile ? 16 : 32, vertical: 16),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 900),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _playerCard(),
              const SizedBox(height: 24),
              _heading(isMobile),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildWithNotes(bool isMobile, {required bool wide}) {
    if (wide) {
      return Padding(
        padding: const EdgeInsets.fromLTRB(32, 16, 32, 16),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Expanded(
              flex: 5,
              child: SingleChildScrollView(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    _playerCard(),
                    const SizedBox(height: 24),
                    _heading(isMobile),
                  ],
                ),
              ),
            ),
            const SizedBox(width: 24),
            Expanded(flex: 4, child: _notesPane()),
          ],
        ),
      );
    }
    return Padding(
      padding: EdgeInsets.fromLTRB(isMobile ? 16 : 32, 16, isMobile ? 16 : 32, 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _playerCard(),
          const SizedBox(height: 16),
          _heading(isMobile, compactDescription: true),
          const SizedBox(height: 16),
          Expanded(child: _notesPane()),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    final isMobile = width < 600;
    final wide = width >= 900;

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
        child: _hasNotes ? _buildWithNotes(isMobile, wide: wide) : _buildPlain(isMobile),
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
