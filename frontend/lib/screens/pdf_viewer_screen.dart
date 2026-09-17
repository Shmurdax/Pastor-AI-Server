import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_application_1/l10n/app_locale.dart';
import 'package:flutter_application_1/models/ingested_document.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_application_1/widgets/pdf_viewer_embed.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';

const _navy = Color(0xFF1B264F);
const _gold = Color(0xFFD4AF37);

/// Authenticated in-app PDF viewer. View-only documents have no download action.
class PdfViewerScreen extends StatefulWidget {
  const PdfViewerScreen({
    super.key,
    required this.apiService,
    required this.document,
  });

  final ApiService apiService;
  final IngestedDocumentItem document;

  @override
  State<PdfViewerScreen> createState() => _PdfViewerScreenState();
}

class _PdfViewerScreenState extends State<PdfViewerScreen> {
  late Future<Uint8List> _bytesFuture;

  @override
  void initState() {
    super.initState();
    _bytesFuture = widget.apiService.getDocumentFile(widget.document.id);
  }

  String get _downloadName {
    final source = widget.document.sourceName.trim();
    if (source.toLowerCase().endsWith('.pdf')) return source;
    final title = widget.document.title.trim();
    if (title.isEmpty) return 'document.pdf';
    return title.toLowerCase().endsWith('.pdf') ? title : '$title.pdf';
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<LocaleController>().strings;
    final viewOnly = widget.document.viewOnly;

    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        backgroundColor: Colors.white,
        foregroundColor: _navy,
        elevation: 0.5,
        title: Text(
          widget.document.title,
          style: GoogleFonts.figtree(
            color: _navy,
            fontWeight: FontWeight.bold,
            fontSize: 18,
          ),
        ),
        actions: [
          if (viewOnly)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: Center(
                child: Text(
                  s.viewOnly,
                  style: GoogleFonts.figtree(
                    color: _gold,
                    fontWeight: FontWeight.w600,
                    fontSize: 13,
                  ),
                ),
              ),
            )
          else
            IconButton(
              tooltip: s.downloadPdf,
              onPressed: () async {
                final messenger = ScaffoldMessenger.of(context);
                try {
                  final bytes = await _bytesFuture;
                  if (!mounted) return;
                  downloadPdfBytes(bytes, _downloadName);
                } catch (_) {
                  if (!mounted) return;
                  messenger.showSnackBar(
                    SnackBar(content: Text(s.couldNotOpenSource(widget.document.title))),
                  );
                }
              },
              icon: const Icon(Icons.download_outlined, color: _navy),
            ),
        ],
      ),
      body: FutureBuilder<Uint8List>(
        future: _bytesFuture,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator(color: _gold));
          }
          if (snapshot.hasError || snapshot.data == null) {
            return Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Text(
                  s.couldNotOpenSource(widget.document.title),
                  textAlign: TextAlign.center,
                  style: GoogleFonts.figtree(color: _navy, fontSize: 16),
                ),
              ),
            );
          }
          return PdfViewerEmbed(
            bytes: snapshot.data!,
            viewKey: 'doc-${widget.document.id}',
          );
        },
      ),
    );
  }
}
