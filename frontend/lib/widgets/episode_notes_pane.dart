import 'package:flutter/material.dart';
import 'package:flutter_application_1/episode_note_text.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:intl/intl.dart';

const _navy = Color(0xFF1B264F);
const _gold = Color(0xFFD4AF37);

/// Reflowed study notes beside the video. The original PDF is a separate action.
class EpisodeNotesPane extends StatelessWidget {
  const EpisodeNotesPane({
    super.key,
    required this.episodeDate,
    required this.topics,
    required this.body,
    required this.loading,
    required this.highlightQuery,
    required this.onViewPdf,
    this.error = false,
  });

  final String episodeDate;
  final List<String> topics;
  final String body;
  final bool loading;
  final bool error;
  final String highlightQuery;
  final VoidCallback? onViewPdf;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: const Color(0xFFF7F5EF),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _navy.withValues(alpha: 0.08)),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    'Episode notes',
                    style: GoogleFonts.figtree(
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                      color: _navy,
                    ),
                  ),
                ),
                TextButton(
                  onPressed: loading ? null : onViewPdf,
                  child: Text(
                    'View original PDF',
                    style: GoogleFonts.figtree(
                      color: _navy,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ],
            ),
            Text(
              formatEpisodeDate(episodeDate),
              style: GoogleFonts.figtree(fontSize: 13, color: Colors.black54),
            ),
            if (topics.isNotEmpty) ...[
              const SizedBox(height: 10),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: [
                  for (final topic in topics)
                    Chip(
                      label: Text(topic, style: GoogleFonts.figtree(fontSize: 12)),
                      visualDensity: VisualDensity.compact,
                      backgroundColor: _gold.withValues(alpha: 0.2),
                      side: BorderSide(color: _gold.withValues(alpha: 0.45)),
                    ),
                ],
              ),
            ],
            const SizedBox(height: 12),
            Expanded(child: _body()),
          ],
        ),
      ),
    );
  }

  Widget _body() {
    if (loading) {
      return const Center(child: CircularProgressIndicator(color: _gold));
    }
    if (error) {
      return Text(
        'These notes could not be loaded.',
        style: GoogleFonts.figtree(color: Colors.black54, height: 1.4),
      );
    }
    final style = GoogleFonts.figtree(fontSize: 15, height: 1.5, color: _navy);
    return Scrollbar(
      child: SingleChildScrollView(
        child: SelectableText.rich(
          highlightedNoteSpan(
            body: body,
            query: highlightQuery,
            style: style,
            highlightStyle: style.copyWith(
              backgroundColor: _gold.withValues(alpha: 0.45),
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
      ),
    );
  }
}

/// Formats `2026-05-15` without shifting the calendar day across time zones.
String formatEpisodeDate(String iso) {
  final match = RegExp(r'^(\d{4})-(\d{2})-(\d{2})').firstMatch(iso.trim());
  if (match == null) return iso;
  final date = DateTime(
    int.parse(match.group(1)!),
    int.parse(match.group(2)!),
    int.parse(match.group(3)!),
  );
  return DateFormat.yMMMMd().format(date);
}
