import 'package:flutter/material.dart';
import 'package:flutter_application_1/screens/subscriptions_screen.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_application_1/widgets/church_events_nav_overlay.dart';
import 'package:flutter_application_1/widgets/nordins_ai_nav_menu.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:video_player/video_player.dart';

const _navy = Color(0xFF1B264F);
const _gold = Color(0xFFD4AF37);

class _MockEpisode {
  const _MockEpisode({
    required this.id,
    required this.title,
    required this.description,
    required this.durationLabel,
    required this.assetPath,
  });

  final String id;
  final String title;
  final String description;
  final String durationLabel;
  final String assetPath;
}

const _sampleEpisode = _MockEpisode(
  id: 'sample-1',
  title: 'Welcome to Media',
  description:
      'A short sample episode for the Media library mock. '
      'Exclusive teaching and podcast episodes will live here for supporters.',
  durationLabel: '0:05',
  assetPath: 'assets/videos/sample-5s.mp4',
);

/// Local-only Media library. Open to all users for now.
/// TODO: gate on Premium subscription.
class MediaLibraryScreen extends StatefulWidget {
  const MediaLibraryScreen({super.key});

  @override
  State<MediaLibraryScreen> createState() => _MediaLibraryScreenState();
}

class _MediaLibraryScreenState extends State<MediaLibraryScreen> {
  final _apiService = ApiService();
  bool _eventsOpen = false;

  Future<void> _launchUrl(String urlString) async {
    final url = Uri.parse(urlString);
    if (await canLaunchUrl(url)) {
      await launchUrl(url, mode: LaunchMode.externalApplication);
    }
  }

  void _openWatch() {
    // TODO: gate on Premium subscription.
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => const _WatchEpisodeScreen(episode: _sampleEpisode),
      ),
    );
  }

  void _openSubscriptions() {
    // Replace so back / stack does not keep Media under Subscribe.
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(builder: (_) => const SubscriptionsScreen()),
    );
  }

  void _goToAiHome() {
    Navigator.of(context).popUntil((route) => route.isFirst);
  }

  void _toggleEvents({bool? open}) {
    setState(() => _eventsOpen = open ?? !_eventsOpen);
  }

  @override
  Widget build(BuildContext context) {
    final screenWidth = MediaQuery.of(context).size.width;
    final isMobileOrTablet = screenWidth < 1024;
    final isMobile = screenWidth < 600;

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
                  constraints: const BoxConstraints(maxWidth: 900),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Text(
                        'Media',
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
                      const SizedBox(height: 16),
                      Center(
                        child: Container(
                          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                          decoration: BoxDecoration(
                            color: _gold.withValues(alpha: 0.15),
                            borderRadius: BorderRadius.circular(8),
                            border: Border.all(color: _gold.withValues(alpha: 0.5)),
                          ),
                          child: Text(
                            'Members preview',
                            style: GoogleFonts.figtree(
                              fontSize: 13,
                              fontWeight: FontWeight.w600,
                              color: _navy,
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(height: 12),
                      Text(
                        'Podcast and teaching episodes for supporters. '
                        'Preview is open to everyone for now.',
                        textAlign: TextAlign.center,
                        style: GoogleFonts.figtree(
                          fontSize: 15,
                          color: Colors.black54,
                        ),
                      ),
                      const SizedBox(height: 36),
                      _EpisodeCard(
                        episode: _sampleEpisode,
                        onTap: _openWatch,
                      ),
                      const SizedBox(height: 20),
                      TextButton(
                        onPressed: _openSubscriptions,
                        child: Text(
                          'Included with Premium',
                          style: GoogleFonts.figtree(
                            color: _navy,
                            fontWeight: FontWeight.w600,
                            decoration: TextDecoration.underline,
                            decorationColor: _gold,
                          ),
                        ),
                      ),
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

class _EpisodeCard extends StatelessWidget {
  const _EpisodeCard({
    required this.episode,
    required this.onTap,
  });

  final _MockEpisode episode;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(16),
        child: Ink(
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: _navy.withValues(alpha: 0.12)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              ClipRRect(
                borderRadius: const BorderRadius.vertical(top: Radius.circular(16)),
                child: AspectRatio(
                  aspectRatio: 16 / 9,
                  child: Container(
                    decoration: const BoxDecoration(
                      gradient: LinearGradient(
                        colors: [_navy, Color(0xFF2F3F6E)],
                        begin: Alignment.topLeft,
                        end: Alignment.bottomRight,
                      ),
                    ),
                    child: Stack(
                      alignment: Alignment.center,
                      children: [
                        Icon(
                          Icons.play_circle_filled,
                          size: 72,
                          color: _gold.withValues(alpha: 0.95),
                        ),
                        Positioned(
                          right: 12,
                          bottom: 12,
                          child: Container(
                            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                            decoration: BoxDecoration(
                              color: Colors.black54,
                              borderRadius: BorderRadius.circular(6),
                            ),
                            child: Text(
                              episode.durationLabel,
                              style: GoogleFonts.figtree(
                                color: Colors.white,
                                fontSize: 12,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 18, 20, 20),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      episode.title,
                      style: GoogleFonts.figtree(
                        fontSize: 20,
                        fontWeight: FontWeight.bold,
                        color: _navy,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      episode.description,
                      style: GoogleFonts.figtree(
                        fontSize: 14,
                        height: 1.45,
                        color: Colors.black54,
                      ),
                    ),
                    const SizedBox(height: 12),
                    Text(
                      'Sample episode',
                      style: GoogleFonts.figtree(
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                        color: _gold,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _WatchEpisodeScreen extends StatefulWidget {
  const _WatchEpisodeScreen({required this.episode});

  final _MockEpisode episode;

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
    // TODO: gate on Premium subscription.
    _controller = VideoPlayerController.asset(widget.episode.assetPath);
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
          style: GoogleFonts.figtree(
            color: _navy,
            fontWeight: FontWeight.bold,
          ),
        ),
      ),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: EdgeInsets.symmetric(
              horizontal: isMobile ? 16 : 32,
              vertical: 16,
            ),
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
                                child: Padding(
                                  padding: const EdgeInsets.all(24),
                                  child: Text(
                                    'Unable to load sample video.',
                                    style: GoogleFonts.figtree(color: Colors.white70),
                                    textAlign: TextAlign.center,
                                  ),
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
                    widget.episode.title,
                    style: GoogleFonts.figtree(
                      fontSize: isMobile ? 22 : 28,
                      fontWeight: FontWeight.bold,
                      color: _navy,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    widget.episode.description,
                    style: GoogleFonts.figtree(
                      fontSize: 15,
                      height: 1.45,
                      color: Colors.black54,
                    ),
                  ),
                  const SizedBox(height: 28),
                  Text(
                    'More episodes',
                    style: GoogleFonts.figtree(
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                      color: _navy,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Container(height: 2, width: 40, color: _gold),
                  const SizedBox(height: 16),
                  Text(
                    'More episodes coming soon.',
                    style: GoogleFonts.figtree(
                      fontSize: 14,
                      color: Colors.black45,
                    ),
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
