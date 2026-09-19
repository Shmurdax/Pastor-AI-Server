import 'package:flutter/material.dart';
import 'package:flutter_application_1/models/response_report.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:intl/intl.dart';

const _navy = Color(0xFF1B264F);
const _gold = Color(0xFFD4AF37);
const _pink = Color(0xFFa1375a);
const _surface = Color(0xFFF4F4F9);

enum _ReportsFilter { all, newOnly, reviewed, dismissed }

class ResponseReportsInboxScreen extends StatefulWidget {
  const ResponseReportsInboxScreen({super.key, required this.apiService});

  final ApiService apiService;

  @override
  State<ResponseReportsInboxScreen> createState() => _ResponseReportsInboxScreenState();
}

class _ResponseReportsInboxScreenState extends State<ResponseReportsInboxScreen> {
  _ReportsFilter _filter = _ReportsFilter.all;
  bool _loading = true;
  String? _error;
  List<ResponseReportItem> _items = const [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  String? get _statusQuery {
    switch (_filter) {
      case _ReportsFilter.newOnly:
        return 'new';
      case _ReportsFilter.reviewed:
        return 'reviewed';
      case _ReportsFilter.dismissed:
        return 'dismissed';
      case _ReportsFilter.all:
        return null;
    }
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final items = await widget.apiService.listResponseReports(status: _statusQuery);
      if (!mounted) return;
      setState(() {
        _items = items;
        _loading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = 'Could not load reports. Make sure you are signed in as staff.';
      });
    }
  }

  Future<void> _openDetail(ResponseReportItem item) async {
    final updated = await Navigator.of(context).push<ResponseReportItem>(
      MaterialPageRoute(
        builder: (_) => ResponseReportDetailScreen(
          apiService: widget.apiService,
          initial: item,
        ),
      ),
    );
    if (updated != null && mounted) {
      setState(() {
        _items = _items.map((e) => e.id == updated.id ? updated : e).toList();
      });
      if (_statusQuery != null && updated.status != _statusQuery) {
        _items = _items.where((e) => e.status == _statusQuery).toList();
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final dateFmt = DateFormat('MMM d, y • h:mm a');

    return Scaffold(
      backgroundColor: _surface,
      appBar: AppBar(
        backgroundColor: _navy,
        foregroundColor: Colors.white,
        title: Text('Response reports', style: GoogleFonts.figtree(fontWeight: FontWeight.bold)),
        actions: [
          IconButton(onPressed: _loading ? null : _load, icon: const Icon(Icons.refresh)),
        ],
      ),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
            child: Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                _filterChip('All', _ReportsFilter.all),
                _filterChip('New', _ReportsFilter.newOnly),
                _filterChip('Reviewed', _ReportsFilter.reviewed),
                _filterChip('Dismissed', _ReportsFilter.dismissed),
              ],
            ),
          ),
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator(color: _gold))
                : _error != null
                    ? Center(
                        child: Padding(
                          padding: const EdgeInsets.all(24),
                          child: Text(
                            _error!,
                            textAlign: TextAlign.center,
                            style: GoogleFonts.figtree(color: _navy),
                          ),
                        ),
                      )
                    : _items.isEmpty
                        ? Center(
                            child: Text(
                              'No reports in this view.',
                              style: GoogleFonts.figtree(color: Colors.black54),
                            ),
                          )
                        : ListView.separated(
                            padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
                            itemCount: _items.length,
                            separatorBuilder: (_, __) => const SizedBox(height: 10),
                            itemBuilder: (context, index) {
                              final item = _items[index];
                              return Material(
                                color: Colors.white,
                                borderRadius: BorderRadius.circular(16),
                                child: InkWell(
                                  borderRadius: BorderRadius.circular(16),
                                  onTap: () => _openDetail(item),
                                  child: Padding(
                                    padding: const EdgeInsets.all(16),
                                    child: Column(
                                      crossAxisAlignment: CrossAxisAlignment.start,
                                      children: [
                                        Row(
                                          children: [
                                            Expanded(
                                              child: Text(
                                                item.reasonLabel,
                                                style: GoogleFonts.figtree(
                                                  fontWeight: FontWeight.bold,
                                                  color: _navy,
                                                  fontSize: 15,
                                                ),
                                              ),
                                            ),
                                            Container(
                                              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                                              decoration: BoxDecoration(
                                                color: item.status == 'new'
                                                    ? _pink.withOpacity(0.12)
                                                    : _navy.withOpacity(0.08),
                                                borderRadius: BorderRadius.circular(8),
                                              ),
                                              child: Text(
                                                item.statusLabel,
                                                style: GoogleFonts.figtree(
                                                  fontSize: 12,
                                                  fontWeight: FontWeight.w600,
                                                  color: item.status == 'new' ? _pink : _navy,
                                                ),
                                              ),
                                            ),
                                          ],
                                        ),
                                        const SizedBox(height: 6),
                                        Text(
                                          item.preview,
                                          style: GoogleFonts.figtree(color: Colors.black87, height: 1.35),
                                        ),
                                        const SizedBox(height: 8),
                                        Text(
                                          '${item.reporterLabel} · ${dateFmt.format(item.createdAt.toLocal())}',
                                          style: GoogleFonts.figtree(fontSize: 12, color: Colors.black45),
                                        ),
                                      ],
                                    ),
                                  ),
                                ),
                              );
                            },
                          ),
          ),
        ],
      ),
    );
  }

  Widget _filterChip(String label, _ReportsFilter value) {
    final selected = _filter == value;
    return FilterChip(
      label: Text(label, style: GoogleFonts.figtree(fontWeight: FontWeight.w600)),
      selected: selected,
      onSelected: (_) {
        if (_filter == value) return;
        setState(() => _filter = value);
        _load();
      },
      selectedColor: _gold.withOpacity(0.35),
      checkmarkColor: _navy,
      labelStyle: TextStyle(color: selected ? _navy : Colors.black54),
    );
  }
}

class ResponseReportDetailScreen extends StatefulWidget {
  const ResponseReportDetailScreen({
    super.key,
    required this.apiService,
    required this.initial,
  });

  final ApiService apiService;
  final ResponseReportItem initial;

  @override
  State<ResponseReportDetailScreen> createState() => _ResponseReportDetailScreenState();
}

class _ResponseReportDetailScreenState extends State<ResponseReportDetailScreen> {
  late ResponseReportItem _item;
  late TextEditingController _notesController;
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _item = widget.initial;
    _notesController = TextEditingController(text: _item.staffNotes);
  }

  @override
  void dispose() {
    _notesController.dispose();
    super.dispose();
  }

  Future<void> _save({required String status}) async {
    if (_saving) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final updated = await widget.apiService.updateResponseReport(
        _item.id,
        status: status,
        staffNotes: _notesController.text.trim(),
      );
      if (!mounted) return;
      setState(() {
        _item = updated;
        _saving = false;
      });
      Navigator.of(context).pop(updated);
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _error = 'Could not update report.';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final dateFmt = DateFormat('MMM d, y • h:mm a');

    return Scaffold(
      backgroundColor: _surface,
      appBar: AppBar(
        backgroundColor: _navy,
        foregroundColor: Colors.white,
        title: Text('Report detail', style: GoogleFonts.figtree(fontWeight: FontWeight.bold)),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(_item.reasonLabel, style: GoogleFonts.figtree(fontSize: 20, fontWeight: FontWeight.bold, color: _navy)),
          const SizedBox(height: 6),
          Text(
            '${_item.reporterLabel} · ${dateFmt.format(_item.createdAt.toLocal())}',
            style: GoogleFonts.figtree(color: Colors.black54),
          ),
          const SizedBox(height: 16),
          _section('User question', _item.userQuerySnapshot),
          const SizedBox(height: 12),
          _section('AI response', _item.aiResponseSnapshot),
          if (_item.details.trim().isNotEmpty) ...[
            const SizedBox(height: 12),
            _section('Reporter details', _item.details),
          ],
          const SizedBox(height: 16),
          Text('Staff notes', style: GoogleFonts.figtree(fontWeight: FontWeight.bold, color: _navy)),
          const SizedBox(height: 8),
          TextField(
            controller: _notesController,
            maxLines: 4,
            decoration: InputDecoration(
              filled: true,
              fillColor: Colors.white,
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
            ),
          ),
          if (_error != null) ...[
            const SizedBox(height: 8),
            Text(_error!, style: GoogleFonts.figtree(color: _pink)),
          ],
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: _saving ? null : () => _save(status: 'dismissed'),
                  child: Text('Dismiss', style: GoogleFonts.figtree(fontWeight: FontWeight.bold)),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: FilledButton(
                  onPressed: _saving ? null : () => _save(status: 'reviewed'),
                  style: FilledButton.styleFrom(backgroundColor: _navy),
                  child: Text('Mark reviewed', style: GoogleFonts.figtree(fontWeight: FontWeight.bold)),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _section(String title, String body) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: GoogleFonts.figtree(fontWeight: FontWeight.bold, color: _navy)),
          const SizedBox(height: 6),
          Text(body, style: GoogleFonts.figtree(height: 1.4, color: Colors.black87)),
        ],
      ),
    );
  }
}

Future<bool> showReportResponseSheet({
  required BuildContext context,
  required ApiService apiService,
  required int messageId,
  required String sessionId,
}) async {
  String? selectedReason;
  final detailsController = TextEditingController();
  var submitting = false;
  String? error;

  final submitted = await showModalBottomSheet<bool>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.white,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
    ),
    builder: (ctx) {
      return StatefulBuilder(
        builder: (ctx, setModalState) {
          final bottom = MediaQuery.of(ctx).viewInsets.bottom;
          return Padding(
            padding: EdgeInsets.fromLTRB(20, 16, 20, 20 + bottom),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Center(
                  child: Container(
                    width: 40,
                    height: 4,
                    decoration: BoxDecoration(
                      color: Colors.black12,
                      borderRadius: BorderRadius.circular(999),
                    ),
                  ),
                ),
                const SizedBox(height: 16),
                Text(
                  'Report this response',
                  style: GoogleFonts.figtree(fontSize: 18, fontWeight: FontWeight.bold, color: _navy),
                ),
                const SizedBox(height: 8),
                Text(
                  'Tell us what went wrong so we can improve.',
                  style: GoogleFonts.figtree(color: Colors.black54),
                ),
                const SizedBox(height: 16),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    for (final option in kReportReasonOptions)
                      ChoiceChip(
                        label: Text(option.label, style: GoogleFonts.figtree(fontWeight: FontWeight.w600)),
                        selected: selectedReason == option.value,
                        onSelected: submitting
                            ? null
                            : (_) => setModalState(() => selectedReason = option.value),
                        selectedColor: _gold.withOpacity(0.35),
                      ),
                  ],
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: detailsController,
                  enabled: !submitting,
                  maxLines: 3,
                  maxLength: 2000,
                  decoration: InputDecoration(
                    labelText: 'Tell us more (optional)',
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
                  ),
                ),
                if (error != null) ...[
                  const SizedBox(height: 4),
                  Text(error!, style: GoogleFonts.figtree(color: _pink, fontSize: 13)),
                ],
                const SizedBox(height: 12),
                FilledButton(
                  onPressed: submitting
                      ? null
                      : () async {
                          if (selectedReason == null) {
                            setModalState(() => error = 'Please choose a reason.');
                            return;
                          }
                          setModalState(() {
                            submitting = true;
                            error = null;
                          });
                          try {
                            await apiService.submitResponseReport(
                              messageId: messageId,
                              reason: selectedReason!,
                              sessionId: sessionId,
                              details: detailsController.text.trim(),
                            );
                            if (ctx.mounted) Navigator.of(ctx).pop(true);
                          } catch (_) {
                            setModalState(() {
                              submitting = false;
                              error = 'Could not submit report. Please try again.';
                            });
                          }
                        },
                  style: FilledButton.styleFrom(
                    backgroundColor: _navy,
                    padding: const EdgeInsets.symmetric(vertical: 14),
                  ),
                  child: Text(
                    submitting ? 'Submitting…' : 'Submit report',
                    style: GoogleFonts.figtree(fontWeight: FontWeight.bold),
                  ),
                ),
              ],
            ),
          );
        },
      );
    },
  );

  detailsController.dispose();
  return submitted == true;
}
