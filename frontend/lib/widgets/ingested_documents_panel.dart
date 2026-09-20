import 'package:flutter/material.dart';
import 'package:flutter_application_1/l10n/app_strings.dart';
import 'package:flutter_application_1/models/ingested_document.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_application_1/verse_search.dart';
import 'package:google_fonts/google_fonts.dart';

const _navy = Color(0xFF1B264F);
const _gold = Color(0xFFD4AF37);
const _pink = Color(0xFFa1375a);

typedef IngestedDocumentsLoader = Future<List<IngestedDocumentItem>> Function();

/// Scrollable catalog of ingested PDFs, opened from the sermon-library chevron.
class IngestedDocumentsPanel extends StatefulWidget {
  const IngestedDocumentsPanel({
    super.key,
    required this.apiService,
    required this.strings,
    required this.onClose,
    required this.onOpenDocument,
    this.embeddedInSidebar = false,
    this.documentsLoader,
  });

  final ApiService apiService;
  final AppStrings strings;
  final VoidCallback onClose;
  final ValueChanged<IngestedDocumentItem> onOpenDocument;
  final bool embeddedInSidebar;
  final IngestedDocumentsLoader? documentsLoader;

  @override
  State<IngestedDocumentsPanel> createState() => _IngestedDocumentsPanelState();
}

class _IngestedDocumentsPanelState extends State<IngestedDocumentsPanel> {
  final _searchController = TextEditingController();
  final _scrollController = ScrollController();
  bool _loading = true;
  String? _error;
  int _loadAttempts = 0;
  List<IngestedDocumentItem> _documents = const [];

  AppStrings get _s => widget.strings;

  @override
  void initState() {
    super.initState();
    _searchController.addListener(() {
      if (mounted) setState(() {});
    });
    _load();
  }

  @override
  void dispose() {
    _searchController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final loader = widget.documentsLoader;
      final docs = loader != null
          ? await loader()
          : parseIngestedDocuments(
              await widget.apiService.getIngestedDocuments(
                sourceKind: 'document',
              ),
            );
      if (!mounted) return;
      setState(() {
        _documents = docs;
        _loading = false;
        _loadAttempts = 0;
      });
    } catch (error) {
      if (!mounted) return;
      final message = error.toString().toLowerCase();
      final throttled = message.contains('throttl') || message.contains('429');
      if (throttled && _loadAttempts < 2) {
        _loadAttempts += 1;
        Future<void>.delayed(Duration(seconds: _loadAttempts), () {
          if (mounted) _load();
        });
        return;
      }
      setState(() {
        _error = _s.ingestedDocumentsLoadFailed;
        _loading = false;
      });
    }
  }

  List<IngestedDocumentItem> get _filtered {
    return catalogDocuments(
      _documents,
      query: _searchController.text,
    );
  }

  @override
  Widget build(BuildContext context) {
    final panel = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 10, 4, 4),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  _s.allDocuments,
                  style: GoogleFonts.figtree(
                    color: Colors.white,
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
              IconButton(
                tooltip: _s.closeDocumentsCatalog,
                onPressed: widget.onClose,
                icon: const Icon(Icons.close, color: Colors.white70, size: 20),
                visualDensity: VisualDensity.compact,
              ),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
          child: TextField(
            controller: _searchController,
            style: GoogleFonts.figtree(color: Colors.white, fontSize: 14),
            cursorColor: _gold,
            decoration: InputDecoration(
              isDense: true,
              hintText: _s.searchDocuments,
              hintStyle: GoogleFonts.figtree(color: Colors.white54, fontSize: 14),
              prefixIcon: const Icon(Icons.search, color: Colors.white70, size: 20),
              prefixIconConstraints: const BoxConstraints(minWidth: 36, minHeight: 36),
              filled: true,
              fillColor: Colors.white.withValues(alpha: 0.12),
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(12),
                borderSide: BorderSide.none,
              ),
              contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            ),
          ),
        ),
        const Divider(height: 1, color: Colors.white24),
        Expanded(child: _buildBody()),
      ],
    );

    if (widget.embeddedInSidebar) {
      return DecoratedBox(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            colors: [_pink, _navy],
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
          ),
        ),
        child: panel,
      );
    }

    return Material(
      elevation: 12,
      borderRadius: BorderRadius.circular(32),
      clipBehavior: Clip.antiAlias,
      child: DecoratedBox(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            colors: [_pink, _navy],
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
          ),
        ),
        child: panel,
      ),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator(color: _gold));
    }
    if (_error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                _error!,
                textAlign: TextAlign.center,
                style: GoogleFonts.figtree(color: Colors.white70, fontSize: 14),
              ),
              const SizedBox(height: 12),
              TextButton(
                onPressed: _load,
                child: Text(
                  _s.retry,
                  style: GoogleFonts.figtree(color: _gold, fontWeight: FontWeight.bold),
                ),
              ),
            ],
          ),
        ),
      );
    }
    final items = _filtered;
    if (items.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Text(
            _s.ingestedDocumentsEmpty,
            textAlign: TextAlign.center,
            style: GoogleFonts.figtree(color: Colors.white70, fontSize: 14),
          ),
        ),
      );
    }
    return RawScrollbar(
      controller: _scrollController,
      thumbVisibility: true,
      trackVisibility: true,
      interactive: true,
      thickness: 12,
      radius: const Radius.circular(8),
      thumbColor: _gold.withValues(alpha: 0.9),
      trackColor: Colors.white.withValues(alpha: 0.16),
      trackBorderColor: Colors.white24,
      padding: const EdgeInsets.fromLTRB(4, 8, 4, 22),
      child: ListView.builder(
        controller: _scrollController,
        primary: false,
        padding: const EdgeInsets.fromLTRB(0, 8, 18, 8),
        itemCount: items.length,
        itemBuilder: (context, index) {
          final doc = items[index];
          final query = _searchController.text.trim();
          final mention = mentionedVerseLabel(doc, query);
          final showMention = mention != null &&
              !doc.title.toLowerCase().contains(query.toLowerCase());
          final subtitleParts = <String>[
            if (doc.viewOnly) _s.viewOnly,
            if (showMention) _s.mentionsVerse(mention!),
          ];
          return ListTile(
            dense: true,
            leading: Icon(
              doc.viewOnly ? Icons.visibility_outlined : Icons.description_outlined,
              color: _gold,
              size: 18,
            ),
            title: Text(
              doc.title,
              style: GoogleFonts.figtree(color: Colors.white, fontSize: 14),
            ),
            subtitle: subtitleParts.isEmpty
                ? null
                : Text(
                    subtitleParts.join(' · '),
                    style: GoogleFonts.figtree(color: _gold, fontSize: 11),
                  ),
            onTap: () => widget.onOpenDocument(doc),
          );
        },
      ),
    );
  }
}
