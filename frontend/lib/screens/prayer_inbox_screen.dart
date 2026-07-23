import 'package:flutter/material.dart';
import 'package:flutter_application_1/models/prayer_request.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:intl/intl.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher/url_launcher.dart';

const _navy = Color(0xFF1B264F);
const _gold = Color(0xFFD4AF37);
const _pink = Color(0xFFa1375a);
const _surface = Color(0xFFF4F4F9);

const _kPrayerEmailClientPref = 'prayer_inbox_email_client';

enum PrayerEmailClient { gmail, outlook, systemMailto }

PrayerEmailClient prayerEmailClientFromStorage(String? value) {
  switch (value) {
    case 'outlook':
      return PrayerEmailClient.outlook;
    case 'mailto':
      return PrayerEmailClient.systemMailto;
    case 'gmail':
    default:
      return PrayerEmailClient.gmail;
  }
}

String prayerEmailClientStorageKey(PrayerEmailClient client) {
  switch (client) {
    case PrayerEmailClient.outlook:
      return 'outlook';
    case PrayerEmailClient.systemMailto:
      return 'mailto';
    case PrayerEmailClient.gmail:
      return 'gmail';
  }
}

Uri prayerEmailComposeUri(String to, PrayerEmailClient client) {
  final encodedTo = Uri.encodeComponent(to);
  switch (client) {
    case PrayerEmailClient.gmail:
      return Uri.parse('https://mail.google.com/mail/?view=cm&fs=1&to=$encodedTo');
    case PrayerEmailClient.outlook:
      return Uri.parse(
        'https://outlook.office.com/mail/deeplink/compose?to=$encodedTo',
      );
    case PrayerEmailClient.systemMailto:
      return Uri(scheme: 'mailto', path: to);
  }
}

String prayerEmailClientLabel(PrayerEmailClient client) {
  switch (client) {
    case PrayerEmailClient.gmail:
      return 'Gmail';
    case PrayerEmailClient.outlook:
      return 'Outlook';
    case PrayerEmailClient.systemMailto:
      return 'Default app';
  }
}

enum _InboxFilter { all, needsFollowUp, done }

class PrayerInboxScreen extends StatefulWidget {
  const PrayerInboxScreen({super.key, required this.apiService});

  final ApiService apiService;

  @override
  State<PrayerInboxScreen> createState() => _PrayerInboxScreenState();
}

class _PrayerInboxScreenState extends State<PrayerInboxScreen> {
  _InboxFilter _filter = _InboxFilter.all;
  bool _loading = true;
  String? _error;
  List<PrayerRequestItem> _items = const [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      bool? followedUp;
      if (_filter == _InboxFilter.needsFollowUp) followedUp = false;
      if (_filter == _InboxFilter.done) followedUp = true;
      final items = await widget.apiService.listPrayerRequests(followedUp: followedUp);
      if (!mounted) return;
      setState(() {
        _items = items;
        _loading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = 'Could not load prayer requests. Make sure you are signed in as staff.';
      });
    }
  }

  Future<void> _openDetail(PrayerRequestItem item) async {
    final updated = await Navigator.of(context).push<PrayerRequestItem>(
      MaterialPageRoute(
        builder: (_) => PrayerRequestDetailScreen(
          apiService: widget.apiService,
          initial: item,
        ),
      ),
    );
    if (updated != null && mounted) {
      setState(() {
        _items = _items.map((e) => e.id == updated.id ? updated : e).toList();
      });
      if (_filter == _InboxFilter.needsFollowUp && updated.followedUp) {
        _items = _items.where((e) => !e.followedUp).toList();
      }
      if (_filter == _InboxFilter.done && !updated.followedUp) {
        _items = _items.where((e) => e.followedUp).toList();
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
        title: Text('Prayer inbox', style: GoogleFonts.figtree(fontWeight: FontWeight.bold)),
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
                _filterChip('All', _InboxFilter.all),
                _filterChip('Needs follow-up', _InboxFilter.needsFollowUp),
                _filterChip('Followed up', _InboxFilter.done),
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
                          child: Text(_error!, textAlign: TextAlign.center, style: GoogleFonts.figtree(color: _navy)),
                        ),
                      )
                    : _items.isEmpty
                        ? Center(
                            child: Text(
                              'No prayer requests in this view.',
                              style: GoogleFonts.figtree(color: Colors.black54),
                            ),
                          )
                        : ListView.separated(
                            padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
                            itemCount: _items.length,
                            separatorBuilder: (context, index) => const SizedBox(height: 10),
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
                                                item.displayName,
                                                style: GoogleFonts.figtree(
                                                  fontWeight: FontWeight.bold,
                                                  fontSize: 16,
                                                  color: _navy,
                                                ),
                                              ),
                                            ),
                                            if (item.followedUp)
                                              Container(
                                                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                                                decoration: BoxDecoration(
                                                  color: Colors.green.shade50,
                                                  borderRadius: BorderRadius.circular(8),
                                                ),
                                                child: Text(
                                                  'Followed up',
                                                  style: GoogleFonts.figtree(
                                                    fontSize: 11,
                                                    fontWeight: FontWeight.w600,
                                                    color: Colors.green.shade800,
                                                  ),
                                                ),
                                              )
                                            else
                                              Container(
                                                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                                                decoration: BoxDecoration(
                                                  color: _gold.withValues(alpha: 0.2),
                                                  borderRadius: BorderRadius.circular(8),
                                                ),
                                                child: Text(
                                                  'Open',
                                                  style: GoogleFonts.figtree(
                                                    fontSize: 11,
                                                    fontWeight: FontWeight.w600,
                                                    color: _navy,
                                                  ),
                                                ),
                                              ),
                                          ],
                                        ),
                                        const SizedBox(height: 6),
                                        Text(
                                          dateFmt.format(item.createdAt.toLocal()),
                                          style: GoogleFonts.figtree(fontSize: 12, color: Colors.black45),
                                        ),
                                        const SizedBox(height: 10),
                                        Text(
                                          item.preview,
                                          style: GoogleFonts.figtree(fontSize: 14, color: Colors.black87, height: 1.4),
                                        ),
                                        if (item.bestEmail != null || item.phone.trim().isNotEmpty) ...[
                                          const SizedBox(height: 10),
                                          Text(
                                            [
                                              if (item.bestEmail != null) item.bestEmail,
                                              if (item.phone.trim().isNotEmpty) item.phone.trim(),
                                            ].join(' • '),
                                            style: GoogleFonts.figtree(fontSize: 12, color: _pink),
                                          ),
                                        ],
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

  Widget _filterChip(String label, _InboxFilter value) {
    final selected = _filter == value;
    return FilterChip(
      label: Text(label, style: GoogleFonts.figtree(fontWeight: FontWeight.w600)),
      selected: selected,
      onSelected: (_) {
        setState(() => _filter = value);
        _load();
      },
      selectedColor: _gold.withValues(alpha: 0.35),
      checkmarkColor: _navy,
    );
  }
}

class PrayerRequestDetailScreen extends StatefulWidget {
  const PrayerRequestDetailScreen({
    super.key,
    required this.apiService,
    required this.initial,
  });

  final ApiService apiService;
  final PrayerRequestItem initial;

  @override
  State<PrayerRequestDetailScreen> createState() => _PrayerRequestDetailScreenState();
}

class _PrayerRequestDetailScreenState extends State<PrayerRequestDetailScreen> {
  late bool _followedUp;
  late TextEditingController _notesController;
  bool _saving = false;
  String? _error;
  PrayerRequestItem? _item;
  PrayerEmailClient _preferredEmailClient = PrayerEmailClient.gmail;

  @override
  void initState() {
    super.initState();
    _item = widget.initial;
    _followedUp = widget.initial.followedUp;
    _notesController = TextEditingController(text: widget.initial.pastorNotes);
    _loadEmailPreference();
  }

  Future<void> _loadEmailPreference() async {
    final prefs = await SharedPreferences.getInstance();
    final stored = prefs.getString(_kPrayerEmailClientPref);
    if (!mounted) return;
    setState(() {
      _preferredEmailClient = prayerEmailClientFromStorage(stored);
    });
  }

  Future<void> _setEmailPreference(PrayerEmailClient client) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_kPrayerEmailClientPref, prayerEmailClientStorageKey(client));
    if (!mounted) return;
    setState(() => _preferredEmailClient = client);
  }

  @override
  void dispose() {
    _notesController.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (_saving || _item == null) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final updated = await widget.apiService.updatePrayerRequest(
        _item!.id,
        followedUp: _followedUp,
        pastorNotes: _notesController.text.trim(),
        contactedAt: _followedUp && _item!.contactedAt == null ? DateTime.now().toUtc() : _item!.contactedAt,
      );
      if (!mounted) return;
      setState(() {
        _item = updated;
        _followedUp = updated.followedUp;
        _notesController.text = updated.pastorNotes;
        _saving = false;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Follow-up saved')),
      );
      Navigator.of(context).pop(updated);
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _error = 'Could not save changes.';
      });
    }
  }

  Future<void> _launch(Uri uri) async {
    final mode = uri.scheme == 'http' || uri.scheme == 'https'
        ? LaunchMode.externalApplication
        : LaunchMode.platformDefault;
    if (!await launchUrl(uri, mode: mode)) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not open ${uri.scheme} link')),
        );
      }
    }
  }

  Future<void> _openEmail(String to, PrayerEmailClient client) async {
    await _setEmailPreference(client);
    await _launch(prayerEmailComposeUri(to, client));
  }

  Widget _emailClientChip(PrayerEmailClient client, String to, {required bool selected}) {
    return FilterChip(
      label: Text(prayerEmailClientLabel(client), style: GoogleFonts.figtree(fontWeight: FontWeight.w600)),
      selected: selected,
      onSelected: (_) => _openEmail(to, client),
      selectedColor: _gold.withValues(alpha: 0.35),
      checkmarkColor: _navy,
    );
  }

  @override
  Widget build(BuildContext context) {
    final item = _item!;
    final dateFmt = DateFormat('EEEE, MMM d, y • h:mm a');
    final email = item.bestEmail;

    return Scaffold(
      backgroundColor: _surface,
      appBar: AppBar(
        backgroundColor: _navy,
        foregroundColor: Colors.white,
        title: Text(item.displayName, style: GoogleFonts.figtree(fontWeight: FontWeight.bold)),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              dateFmt.format(item.createdAt.toLocal()),
              style: GoogleFonts.figtree(color: Colors.black54, fontSize: 13),
            ),
            if (item.isAnonymous)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(
                  'Submitted anonymously',
                  style: GoogleFonts.figtree(color: _pink, fontWeight: FontWeight.w600),
                ),
              ),
            if (item.submitterUserEmail != null && item.isAnonymous)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  'Signed-in account: ${item.submitterUserName ?? item.submitterUserEmail}',
                  style: GoogleFonts.figtree(fontSize: 12, color: Colors.black54),
                ),
              ),
            const SizedBox(height: 16),
            if (email != null) ...[
              Wrap(
                spacing: 10,
                runSpacing: 10,
                children: [
                  FilledButton.icon(
                    onPressed: () => _openEmail(email, _preferredEmailClient),
                    icon: const Icon(Icons.email_outlined, size: 18),
                    label: Text(
                      'Email in ${prayerEmailClientLabel(_preferredEmailClient)}',
                      style: GoogleFonts.figtree(fontWeight: FontWeight.bold),
                    ),
                    style: FilledButton.styleFrom(
                      backgroundColor: _navy,
                      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                    ),
                  ),
                  if (item.phone.trim().isNotEmpty)
                    OutlinedButton.icon(
                      onPressed: () => _launch(Uri(scheme: 'tel', path: item.phone.trim())),
                      icon: const Icon(Icons.phone_outlined, size: 18),
                      label: const Text('Call'),
                    ),
                ],
              ),
              const SizedBox(height: 10),
              Text(
                'Or open compose in:',
                style: GoogleFonts.figtree(fontSize: 12, color: Colors.black54),
              ),
              const SizedBox(height: 6),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  _emailClientChip(PrayerEmailClient.gmail, email, selected: _preferredEmailClient == PrayerEmailClient.gmail),
                  _emailClientChip(PrayerEmailClient.outlook, email, selected: _preferredEmailClient == PrayerEmailClient.outlook),
                  _emailClientChip(
                    PrayerEmailClient.systemMailto,
                    email,
                    selected: _preferredEmailClient == PrayerEmailClient.systemMailto,
                  ),
                ],
              ),
            ] else if (item.phone.trim().isNotEmpty)
              Wrap(
                spacing: 10,
                runSpacing: 10,
                children: [
                  OutlinedButton.icon(
                    onPressed: () => _launch(Uri(scheme: 'tel', path: item.phone.trim())),
                    icon: const Icon(Icons.phone_outlined, size: 18),
                    label: const Text('Call'),
                  ),
                ],
              ),
            const SizedBox(height: 20),
            Text('Prayer request', style: GoogleFonts.figtree(fontWeight: FontWeight.bold, color: _navy)),
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: Colors.black12),
              ),
              child: Text(
                item.prayerText,
                style: GoogleFonts.figtree(fontSize: 15, height: 1.5, color: Colors.black87),
              ),
            ),
            const SizedBox(height: 24),
            Text('Follow-up', style: GoogleFonts.figtree(fontWeight: FontWeight.bold, color: _navy)),
            const SizedBox(height: 8),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: Text('Mark as followed up', style: GoogleFonts.figtree()),
              value: _followedUp,
              activeThumbColor: _gold,
              onChanged: _saving ? null : (v) => setState(() => _followedUp = v),
            ),
            TextField(
              controller: _notesController,
              maxLines: 5,
              decoration: InputDecoration(
                labelText: 'Pastor notes',
                hintText: 'How you connected, prayer points, next steps…',
                filled: true,
                fillColor: Colors.white,
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
              ),
            ),
            if (item.contactedAt != null) ...[
              const SizedBox(height: 8),
              Text(
                'Last marked contacted: ${DateFormat.yMMMd().add_jm().format(item.contactedAt!.toLocal())}',
                style: GoogleFonts.figtree(fontSize: 12, color: Colors.black45),
              ),
            ],
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(_error!, style: GoogleFonts.figtree(color: Colors.red.shade700)),
            ],
            const SizedBox(height: 20),
            FilledButton(
              onPressed: _saving ? null : _save,
              style: FilledButton.styleFrom(
                backgroundColor: _navy,
                padding: const EdgeInsets.symmetric(vertical: 16),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              ),
              child: _saving
                  ? const SizedBox(
                      height: 22,
                      width: 22,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                    )
                  : Text('Save follow-up', style: GoogleFonts.figtree(fontWeight: FontWeight.bold)),
            ),
          ],
        ),
      ),
    );
  }
}
