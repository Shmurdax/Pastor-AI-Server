import 'package:flutter/material.dart';
import 'package:flutter_application_1/models/church_event.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:intl/intl.dart';

const _navy = Color(0xFF1B264F);
const _gold = Color(0xFFD4AF37);
const _pink = Color(0xFFa1375a);

class ChurchEventsPanel extends StatefulWidget {
  const ChurchEventsPanel({
    super.key,
    required this.apiService,
    required this.isStaff,
    this.embeddedInSidebar = false,
    this.enablePullToRefresh = true,
  });

  final ApiService apiService;
  final bool isStaff;
  final bool embeddedInSidebar;
  /// Pull-to-refresh can paint a grey stretch behind the app; disable in nav overlay.
  final bool enablePullToRefresh;

  @override
  State<ChurchEventsPanel> createState() => _ChurchEventsPanelState();
}

class _ChurchEventsPanelState extends State<ChurchEventsPanel> {
  bool _loading = true;
  String? _error;
  List<ChurchEventItem> _events = [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(covariant ChurchEventsPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.isStaff != widget.isStaff) {
      _load();
    }
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final list = await widget.apiService.listChurchEvents();
      if (!mounted) return;
      final sorted = List<ChurchEventItem>.from(list)
        ..sort((a, b) => a.startsAt.compareTo(b.startsAt));
      setState(() {
        _events = sorted;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = 'Could not load events.';
        _loading = false;
      });
    }
  }

  Future<void> _openEditor({ChurchEventItem? existing}) async {
    if (!widget.isStaff) return;
    final saved = await showDialog<bool>(
      context: context,
      builder: (ctx) => ChurchEventEditorDialog(
        existing: existing,
        onSave: (payload) async {
          if (existing != null) {
            await widget.apiService.updateChurchEvent(existing.id, payload);
          } else {
            await widget.apiService.createChurchEvent(payload);
          }
        },
        onDelete: existing != null
            ? () async {
                await widget.apiService.deleteChurchEvent(existing.id);
              }
            : null,
      ),
    );
    if (saved == true && mounted) await _load();
  }

  @override
  Widget build(BuildContext context) {
    final sidebar = widget.embeddedInSidebar;

    if (_loading) {
      return Center(
        child: CircularProgressIndicator(color: sidebar ? _gold : _navy),
      );
    }
    if (_error != null) {
      if (sidebar) {
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(_error!, style: GoogleFonts.figtree(color: Colors.white70, fontSize: 14)),
            const SizedBox(height: 12),
            OutlinedButton(
              onPressed: _load,
              style: OutlinedButton.styleFrom(foregroundColor: _gold, side: const BorderSide(color: _gold)),
              child: const Text('Retry'),
            ),
          ],
        );
      }
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(_error!, style: GoogleFonts.figtree(color: Colors.black54, fontSize: 15)),
              const SizedBox(height: 16),
              FilledButton(
                onPressed: _load,
                style: FilledButton.styleFrom(backgroundColor: _navy),
                child: const Text('Retry'),
              ),
            ],
          ),
        ),
      );
    }

    final now = DateTime.now();
    final upcoming = _events.where((e) => !e.startsAt.isBefore(now)).toList()
      ..sort((a, b) => a.startsAt.compareTo(b.startsAt));
    final past = _events.where((e) => e.startsAt.isBefore(now)).toList()
      ..sort((a, b) => b.startsAt.compareTo(a.startsAt));

    final listChildren = <Widget>[
      if (widget.isStaff)
        Padding(
          padding: EdgeInsets.only(bottom: sidebar ? 12 : 16),
          child: FilledButton.icon(
            onPressed: () => _openEditor(),
            icon: const Icon(Icons.add, size: 18),
            label: Text('Add event', style: GoogleFonts.figtree(fontWeight: FontWeight.bold)),
            style: FilledButton.styleFrom(
              backgroundColor: _gold,
              foregroundColor: _navy,
              padding: EdgeInsets.symmetric(vertical: sidebar ? 12 : 14),
            ),
          ),
        ),
      if (_events.isEmpty)
        Padding(
          padding: EdgeInsets.only(top: sidebar ? 8 : 48),
          child: Text(
            'No events scheduled yet.${widget.isStaff ? ' Tap Add event to create one.' : ''}',
            textAlign: sidebar ? TextAlign.start : TextAlign.center,
            style: GoogleFonts.figtree(
              color: sidebar ? Colors.white70 : Colors.black54,
              fontSize: sidebar ? 14 : 15,
            ),
          ),
        )
      else ...[
        if (upcoming.isNotEmpty) ...[
          _sectionLabel('Upcoming', sidebar: sidebar),
          ...upcoming.map((e) => ChurchEventTile(
                event: e,
                isStaff: widget.isStaff,
                sidebarStyle: sidebar,
                onEdit: () => _openEditor(existing: e),
              )),
        ],
        if (past.isNotEmpty) ...[
          SizedBox(height: sidebar ? 16 : 20),
          _sectionLabel('Past', sidebar: sidebar),
          ...past.map((e) => Opacity(
                opacity: sidebar ? 0.75 : 0.85,
                child: ChurchEventTile(
                  event: e,
                  isStaff: widget.isStaff,
                  sidebarStyle: sidebar,
                  onEdit: () => _openEditor(existing: e),
                ),
              )),
        ],
      ],
    ];

    if (sidebar) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Expanded(
            child: ListView(
              children: listChildren,
            ),
          ),
        ],
      );
    }

    final listView = ListView(
      physics: const ClampingScrollPhysics(),
      padding: const EdgeInsets.fromLTRB(20, 8, 20, 32),
      children: listChildren,
    );

    if (!widget.enablePullToRefresh) {
      return listView;
    }

    return RefreshIndicator(
      color: _navy,
      onRefresh: _load,
      child: listView,
    );
  }

  Widget _sectionLabel(String text, {required bool sidebar}) {
    return Padding(
      padding: EdgeInsets.only(left: 4, bottom: sidebar ? 8 : 10, top: 4),
      child: Text(
        text,
        style: GoogleFonts.figtree(
          color: sidebar ? _gold : _navy,
          fontSize: sidebar ? 12 : 13,
          fontWeight: FontWeight.bold,
          letterSpacing: 0.5,
        ),
      ),
    );
  }
}

class ChurchEventTile extends StatelessWidget {
  const ChurchEventTile({
    super.key,
    required this.event,
    required this.isStaff,
    required this.onEdit,
    this.sidebarStyle = false,
  });

  final ChurchEventItem event;
  final bool isStaff;
  final VoidCallback onEdit;
  final bool sidebarStyle;

  @override
  Widget build(BuildContext context) {
    final fmt = DateFormat('EEE, MMM d · h:mm a');
    final range = event.endsAt != null
        ? '${fmt.format(event.startsAt)} – ${DateFormat('h:mm a').format(event.endsAt!)}'
        : fmt.format(event.startsAt);

    return Container(
      margin: EdgeInsets.only(bottom: sidebarStyle ? 4 : 12, top: sidebarStyle ? 4 : 0),
      padding: EdgeInsets.all(sidebarStyle ? 12 : 16),
      decoration: BoxDecoration(
        color: sidebarStyle ? Colors.white.withValues(alpha: 0.08) : Colors.white,
        borderRadius: BorderRadius.circular(sidebarStyle ? 16 : 16),
        border: Border.all(color: sidebarStyle ? Colors.white24 : _gold.withValues(alpha: 0.45)),
        boxShadow: sidebarStyle
            ? null
            : [
                BoxShadow(color: Colors.black.withValues(alpha: 0.06), blurRadius: 12, offset: const Offset(0, 4)),
              ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Text(
                  event.title,
                  style: GoogleFonts.figtree(
                    color: sidebarStyle ? Colors.white : _navy,
                    fontWeight: FontWeight.w600,
                    fontSize: sidebarStyle ? 14 : 16,
                  ),
                ),
              ),
              if (isStaff) ...[
                if (!event.isPublished)
                  Padding(
                    padding: const EdgeInsets.only(right: 4),
                    child: Text(
                      'Draft',
                      style: GoogleFonts.figtree(
                        color: sidebarStyle ? Colors.orange.shade200 : Colors.orange.shade800,
                        fontSize: sidebarStyle ? 10 : 11,
                      ),
                    ),
                  ),
                IconButton(
                  onPressed: onEdit,
                  icon: Icon(Icons.edit_outlined, size: sidebarStyle ? 18 : 20),
                  color: sidebarStyle ? Colors.white54 : _navy.withValues(alpha: 0.55),
                  visualDensity: VisualDensity.compact,
                  padding: EdgeInsets.zero,
                  constraints: BoxConstraints(
                    minWidth: sidebarStyle ? 28 : 32,
                    minHeight: sidebarStyle ? 28 : 32,
                  ),
                  tooltip: 'Edit event',
                ),
              ],
            ],
          ),
          SizedBox(height: sidebarStyle ? 6 : 8),
          _metaRow(Icons.schedule, range, sidebarStyle),
          const SizedBox(height: 4),
          _metaRow(Icons.place_outlined, event.location, sidebarStyle),
          const SizedBox(height: 4),
          _metaRow(Icons.person_outline, 'Host: ${event.hostName}', sidebarStyle),
          if (event.description.trim().isNotEmpty) ...[
            SizedBox(height: sidebarStyle ? 8 : 10),
            Text(
              event.description.trim(),
              maxLines: sidebarStyle ? 3 : null,
              overflow: sidebarStyle ? TextOverflow.ellipsis : null,
              style: GoogleFonts.figtree(
                color: sidebarStyle ? Colors.white54 : Colors.black54,
                fontSize: sidebarStyle ? 11 : 13,
                height: 1.4,
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _metaRow(IconData icon, String text, bool sidebarStyle) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(icon, size: sidebarStyle ? 14 : 16, color: _gold),
        const SizedBox(width: 6),
        Expanded(
          child: Text(
            text,
            style: GoogleFonts.figtree(
              color: sidebarStyle ? Colors.white70 : Colors.black87,
              fontSize: sidebarStyle ? 12 : 13,
            ),
          ),
        ),
      ],
    );
  }
}

class ChurchEventEditorDialog extends StatefulWidget {
  const ChurchEventEditorDialog({
    super.key,
    required this.onSave,
    this.existing,
    this.onDelete,
  });

  final ChurchEventItem? existing;
  final Future<void> Function(Map<String, dynamic> payload) onSave;
  final Future<void> Function()? onDelete;

  @override
  State<ChurchEventEditorDialog> createState() => _ChurchEventEditorDialogState();
}

class _ChurchEventEditorDialogState extends State<ChurchEventEditorDialog> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _title;
  late final TextEditingController _location;
  late final TextEditingController _host;
  late final TextEditingController _description;
  late DateTime _startsAt;
  DateTime? _endsAt;
  bool _published = true;
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    final e = widget.existing;
    _title = TextEditingController(text: e?.title ?? '');
    _location = TextEditingController(text: e?.location ?? '');
    _host = TextEditingController(text: e?.hostName ?? '');
    _description = TextEditingController(text: e?.description ?? '');
    _startsAt = e?.startsAt ?? DateTime.now().add(const Duration(days: 7));
    _endsAt = e?.endsAt;
    _published = e?.isPublished ?? true;
  }

  @override
  void dispose() {
    _title.dispose();
    _location.dispose();
    _host.dispose();
    _description.dispose();
    super.dispose();
  }

  Future<void> _pickStartDate() async {
    final date = await showDatePicker(
      context: context,
      initialDate: _startsAt,
      firstDate: DateTime(2020),
      lastDate: DateTime(2100),
    );
    if (date == null || !mounted) return;
    final time = await showTimePicker(context: context, initialTime: TimeOfDay.fromDateTime(_startsAt));
    if (time == null || !mounted) return;
    setState(() {
      _startsAt = DateTime(date.year, date.month, date.day, time.hour, time.minute);
    });
  }

  Future<void> _pickEndDate() async {
    final base = _endsAt ?? _startsAt.add(const Duration(hours: 1));
    final date = await showDatePicker(
      context: context,
      initialDate: base,
      firstDate: DateTime(2020),
      lastDate: DateTime(2100),
    );
    if (date == null || !mounted) return;
    final time = await showTimePicker(context: context, initialTime: TimeOfDay.fromDateTime(base));
    if (time == null || !mounted) return;
    setState(() {
      _endsAt = DateTime(date.year, date.month, date.day, time.hour, time.minute);
    });
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    if (_endsAt != null && _endsAt!.isBefore(_startsAt)) {
      setState(() => _error = 'End time must be after start time.');
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await widget.onSave({
        'title': _title.text.trim(),
        'location': _location.text.trim(),
        'host_name': _host.text.trim(),
        'description': _description.text.trim(),
        'starts_at': _startsAt.toUtc().toIso8601String(),
        if (_endsAt != null) 'ends_at': _endsAt!.toUtc().toIso8601String(),
        'is_published': _published,
      });
      if (mounted) Navigator.of(context).pop(true);
    } catch (_) {
      if (mounted) {
        setState(() {
          _saving = false;
          _error = 'Could not save event. Are you signed in as staff?';
        });
      }
    }
  }

  Future<void> _delete() async {
    if (widget.onDelete == null) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete event?'),
        content: const Text('This removes the event for everyone.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: FilledButton.styleFrom(backgroundColor: _pink),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    setState(() => _saving = true);
    try {
      await widget.onDelete!();
      if (mounted) Navigator.of(context).pop(true);
    } catch (_) {
      if (mounted) {
        setState(() {
          _saving = false;
          _error = 'Could not delete event.';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final fmt = DateFormat('MMM d, yyyy · h:mm a');
    return AlertDialog(
      title: Text(
        widget.existing == null ? 'Add church event' : 'Edit church event',
        style: GoogleFonts.figtree(fontWeight: FontWeight.bold, color: _navy),
      ),
      content: SizedBox(
        width: 420,
        child: Form(
          key: _formKey,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                if (_error != null) ...[
                  Text(_error!, style: GoogleFonts.figtree(color: Colors.red.shade700, fontSize: 13)),
                  const SizedBox(height: 8),
                ],
                TextFormField(
                  controller: _title,
                  decoration: const InputDecoration(labelText: 'Event title'),
                  validator: (v) => (v == null || v.trim().isEmpty) ? 'Required' : null,
                ),
                TextFormField(
                  controller: _location,
                  decoration: const InputDecoration(labelText: 'Location'),
                  validator: (v) => (v == null || v.trim().isEmpty) ? 'Required' : null,
                ),
                TextFormField(
                  controller: _host,
                  decoration: const InputDecoration(labelText: 'Host / ministry'),
                  validator: (v) => (v == null || v.trim().isEmpty) ? 'Required' : null,
                ),
                TextFormField(
                  controller: _description,
                  decoration: const InputDecoration(labelText: 'Details (optional)'),
                  maxLines: 3,
                ),
                const SizedBox(height: 8),
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Starts'),
                  subtitle: Text(fmt.format(_startsAt)),
                  trailing: const Icon(Icons.calendar_month),
                  onTap: _saving ? null : _pickStartDate,
                ),
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Ends (optional)'),
                  subtitle: Text(_endsAt != null ? fmt.format(_endsAt!) : 'Not set'),
                  trailing: IconButton(
                    icon: const Icon(Icons.clear),
                    onPressed: _saving ? null : () => setState(() => _endsAt = null),
                  ),
                  onTap: _saving ? null : _pickEndDate,
                ),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Published (visible to everyone)'),
                  value: _published,
                  onChanged: _saving ? null : (v) => setState(() => _published = v),
                ),
              ],
            ),
          ),
        ),
      ),
      actions: [
        if (widget.onDelete != null)
          TextButton(
            onPressed: _saving ? null : _delete,
            child: Text('Delete', style: TextStyle(color: Colors.red.shade700)),
          ),
        TextButton(onPressed: _saving ? null : () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(
          onPressed: _saving ? null : _submit,
          style: FilledButton.styleFrom(backgroundColor: _navy),
          child: _saving
              ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
              : const Text('Save'),
        ),
      ],
    );
  }
}
