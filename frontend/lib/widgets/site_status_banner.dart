import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_application_1/site_banner.dart';

/// Hazard yellow used for the public status banner.
const siteBannerHazardYellow = Color(0xFFFFD100);

/// Slate grey used for the public status banner text.
const siteBannerSlateGrey = Color(0xFF475569);

/// Hazard-yellow notice pinned to the top of every website page.
class SiteStatusBanner extends StatelessWidget {
  const SiteStatusBanner({
    super.key,
    required this.message,
    this.onDismiss,
  });

  final String message;
  final VoidCallback? onDismiss;

  @override
  Widget build(BuildContext context) {
    final base = Theme.of(context).textTheme.bodyLarge ?? const TextStyle();
    return Semantics(
      liveRegion: true,
      child: ColoredBox(
        key: const Key('site-status-banner'),
        color: siteBannerHazardYellow,
        child: SafeArea(
          bottom: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(8, 4, 4, 4),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 8,
                      vertical: 6,
                    ),
                    child: Text(
                      message,
                      textAlign: TextAlign.center,
                      style: base.copyWith(
                        color: siteBannerSlateGrey,
                        fontSize: 15,
                        fontWeight: FontWeight.w600,
                        height: 1.35,
                      ),
                    ),
                  ),
                ),
                if (onDismiss != null)
                  // Avoid IconButton: tooltips need Overlay, and this banner
                  // lives in MaterialApp.builder above the navigator overlay.
                  Semantics(
                    button: true,
                    label: 'Dismiss',
                    child: GestureDetector(
                      key: const Key('site-status-banner-dismiss'),
                      behavior: HitTestBehavior.opaque,
                      onTap: onDismiss,
                      child: const Padding(
                        padding: EdgeInsets.all(8),
                        child: Icon(
                          Icons.close,
                          color: siteBannerSlateGrey,
                          size: 20,
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// Places [child] under the site banner and keeps the banner above every route.
///
/// Closing the banner hides it for the rest of this visit (including route
/// changes). A fresh page load / app start shows it again when enabled.
class SiteBannerFrame extends StatefulWidget {
  const SiteBannerFrame({
    super.key,
    required this.child,
    required this.load,
  });

  final Widget child;
  final Future<SiteBannerNotice> Function() load;

  @override
  State<SiteBannerFrame> createState() => _SiteBannerFrameState();
}

class _SiteBannerFrameState extends State<SiteBannerFrame> {
  SiteBannerNotice _notice = SiteBannerNotice.hidden;
  bool _dismissed = false;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  Future<void> _load() async {
    SiteBannerNotice notice;
    try {
      notice = await widget.load().timeout(const Duration(seconds: 8));
    } catch (_) {
      notice = SiteBannerNotice.hidden;
    }
    if (!mounted || _notice == notice) return;
    setState(() => _notice = notice);
  }

  void _dismiss() {
    if (_dismissed) return;
    setState(() => _dismissed = true);
  }

  @override
  Widget build(BuildContext context) {
    final visible = _notice.isVisible && !_dismissed;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (visible)
          SiteStatusBanner(
            message: _notice.message,
            onDismiss: _dismiss,
          ),
        Expanded(
          child: visible
              ? LayoutBuilder(
                  builder: (context, constraints) {
                    final media = MediaQuery.of(context);
                    return MediaQuery(
                      data: media.copyWith(
                        size: Size(constraints.maxWidth, constraints.maxHeight),
                        padding: media.padding.copyWith(top: 0),
                        viewPadding: media.viewPadding.copyWith(top: 0),
                      ),
                      child: widget.child,
                    );
                  },
                )
              : widget.child,
        ),
      ],
    );
  }
}
