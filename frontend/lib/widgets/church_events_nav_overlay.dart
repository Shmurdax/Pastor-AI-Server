import 'package:flutter/material.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_application_1/widgets/church_events_panel.dart';
import 'package:google_fonts/google_fonts.dart';

const _navy = Color(0xFF1B264F);
const _surface = Color(0xFFF4F4F9);

/// Top-right Church Events panel used from chat / media / subscribe nav.
class ChurchEventsNavOverlay extends StatelessWidget {
  const ChurchEventsNavOverlay({
    super.key,
    required this.apiService,
    required this.isStaff,
    required this.onClose,
    this.panelKey,
  });

  final ApiService apiService;
  final bool isStaff;
  final VoidCallback onClose;
  final Key? panelKey;

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.of(context).size;
    final screenWidth = size.width;
    final targetWidth = screenWidth * 0.3;
    final panelWidth = targetWidth < 260 ? screenWidth * 0.92 : targetWidth;
    final panelHeight = (size.height * 0.32).clamp(200.0, 340.0);

    return Padding(
      padding: EdgeInsets.fromLTRB(8, 0, screenWidth < 600 ? 8 : 16, 8),
      child: SizedBox(
        width: panelWidth,
        height: panelHeight,
        child: Material(
          color: _surface,
          elevation: 2,
          shadowColor: Colors.black26,
          borderRadius: BorderRadius.circular(16),
          clipBehavior: Clip.antiAlias,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 10, 4, 4),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(
                        'Church Events',
                        style: GoogleFonts.figtree(
                          fontSize: 16,
                          fontWeight: FontWeight.bold,
                          color: _navy,
                        ),
                      ),
                    ),
                    IconButton(
                      tooltip: 'Close events',
                      onPressed: onClose,
                      icon: const Icon(Icons.close, color: _navy, size: 20),
                      visualDensity: VisualDensity.compact,
                    ),
                  ],
                ),
              ),
              const Divider(height: 1),
              Expanded(
                child: ChurchEventsPanel(
                  key: panelKey,
                  apiService: apiService,
                  isStaff: isStaff,
                  enablePullToRefresh: false,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
