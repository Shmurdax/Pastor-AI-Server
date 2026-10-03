import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_application_1/site_banner.dart';

/// Hazard yellow used for the public status banner.
const siteBannerHazardYellow = Color(0xFFFFD100);

/// Slate grey used for the public status banner text.
const siteBannerSlateGrey = Color(0xFF475569);

/// Hazard-yellow notice pinned to the top of every website page.
class SiteStatusBanner extends StatelessWidget {
  const SiteStatusBanner({super.key, required this.message});

  final String message;

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
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
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
      ),
    );
  }
}

/// Places [child] under the site banner and keeps the banner above every route.
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

  @override
  Widget build(BuildContext context) {
    final visible = _notice.isVisible;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (visible) SiteStatusBanner(message: _notice.message),
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
