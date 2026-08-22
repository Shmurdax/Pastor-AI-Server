import 'package:flutter/material.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:google_fonts/google_fonts.dart';

const _navy = Color(0xFF1B264F);
const _gold = Color(0xFFD4AF37);
const _pink = Color(0xFFa1375a);
const _surface = Color(0xFFF4F4F9);

/// Staff tool: compose and send an email to every account email.
class EmailNotificationScreen extends StatefulWidget {
  const EmailNotificationScreen({super.key, required this.apiService});

  final ApiService apiService;

  @override
  State<EmailNotificationScreen> createState() => _EmailNotificationScreenState();
}

class _EmailNotificationScreenState extends State<EmailNotificationScreen> {
  final _formKey = GlobalKey<FormState>();
  final _subjectController = TextEditingController();
  final _bodyController = TextEditingController();

  bool _loadingMeta = true;
  bool _sending = false;
  String? _error;
  String? _statusMessage;
  int _recipientCount = 0;
  String _fromEmail = '';
  bool _emailConfigured = false;

  @override
  void initState() {
    super.initState();
    _loadMeta();
  }

  @override
  void dispose() {
    _subjectController.dispose();
    _bodyController.dispose();
    super.dispose();
  }

  Future<void> _loadMeta() async {
    setState(() {
      _loadingMeta = true;
      _error = null;
    });
    try {
      final meta = await widget.apiService.getEmailNotificationMeta();
      if (!mounted) return;
      setState(() {
        _recipientCount = (meta['recipient_count'] as num?)?.toInt() ?? 0;
        _fromEmail = meta['from_email'] as String? ?? '';
        _emailConfigured = meta['email_configured'] as bool? ?? false;
        _loadingMeta = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _loadingMeta = false;
        _error = 'Could not load recipient info. Make sure you are signed in as staff.';
      });
    }
  }

  Future<void> _send() async {
    if (_sending) return;
    final form = _formKey.currentState;
    if (form == null || !form.validate()) return;

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogCtx) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        title: Text(
          'Send to all accounts?',
          style: GoogleFonts.figtree(color: _navy, fontWeight: FontWeight.bold),
        ),
        content: Text(
          'This emails $_recipientCount account${_recipientCount == 1 ? '' : 's'} '
          'with the subject “${_subjectController.text.trim()}”.',
          style: GoogleFonts.figtree(height: 1.45),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogCtx).pop(false),
            child: Text('Cancel', style: GoogleFonts.figtree(color: _navy, fontWeight: FontWeight.w600)),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogCtx).pop(true),
            style: FilledButton.styleFrom(backgroundColor: _navy),
            child: Text('Send', style: GoogleFonts.figtree(fontWeight: FontWeight.bold)),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    setState(() {
      _sending = true;
      _error = null;
      _statusMessage = null;
    });
    try {
      final result = await widget.apiService.sendEmailNotification(
        subject: _subjectController.text.trim(),
        body: _bodyController.text.trim(),
      );
      if (!mounted) return;
      setState(() {
        _sending = false;
        _statusMessage = result['message'] as String? ??
            'Sent to ${result['sent'] ?? 0} account${(result['sent'] == 1) ? '' : 's'}.';
        _recipientCount = (result['recipient_count'] as num?)?.toInt() ?? _recipientCount;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(_statusMessage!)),
      );
    } catch (e) {
      if (!mounted) return;
      final detail = e.toString().replaceFirst(RegExp(r'^Exception:\s*'), '');
      setState(() {
        _sending = false;
        _error = detail.isEmpty ? 'Could not send the notification.' : detail;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _surface,
      appBar: AppBar(
        backgroundColor: _navy,
        foregroundColor: Colors.white,
        title: Text('Email members', style: GoogleFonts.figtree(fontWeight: FontWeight.bold)),
        actions: [
          IconButton(
            onPressed: (_loadingMeta || _sending) ? null : _loadMeta,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: _loadingMeta
          ? const Center(child: CircularProgressIndicator(color: _navy))
          : SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(20, 20, 20, 40),
              child: Form(
                key: _formKey,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Container(
                      padding: const EdgeInsets.all(16),
                      decoration: BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(16),
                        border: Border.all(color: _gold.withValues(alpha: 0.45)),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '$_recipientCount account email${_recipientCount == 1 ? '' : 's'}',
                            style: GoogleFonts.figtree(
                              fontSize: 18,
                              fontWeight: FontWeight.bold,
                              color: _navy,
                            ),
                          ),
                          const SizedBox(height: 6),
                          Text(
                            _fromEmail.isEmpty
                                ? 'Sends individually so addresses stay private.'
                                : 'From $_fromEmail · sends individually so addresses stay private.',
                            style: GoogleFonts.figtree(fontSize: 13, color: Colors.black54, height: 1.35),
                          ),
                          if (!_emailConfigured) ...[
                            const SizedBox(height: 10),
                            Text(
                              'SMTP is not configured yet. Messages may only print on the server '
                              'console until EMAIL_HOST is set.',
                              style: GoogleFonts.figtree(fontSize: 13, color: _pink, height: 1.35),
                            ),
                          ],
                        ],
                      ),
                    ),
                    if (_error != null) ...[
                      const SizedBox(height: 16),
                      Text(_error!, style: GoogleFonts.figtree(color: _pink, height: 1.35)),
                    ],
                    if (_statusMessage != null) ...[
                      const SizedBox(height: 16),
                      Text(_statusMessage!, style: GoogleFonts.figtree(color: _navy, height: 1.35)),
                    ],
                    const SizedBox(height: 20),
                    Text('Subject', style: GoogleFonts.figtree(fontWeight: FontWeight.w600, color: _navy)),
                    const SizedBox(height: 8),
                    TextFormField(
                      controller: _subjectController,
                      textInputAction: TextInputAction.next,
                      decoration: InputDecoration(
                        filled: true,
                        fillColor: Colors.white,
                        hintText: 'Sunday update',
                        hintStyle: GoogleFonts.figtree(color: Colors.black38),
                        border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
                        enabledBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(12),
                          borderSide: BorderSide(color: _navy.withValues(alpha: 0.2)),
                        ),
                      ),
                      style: GoogleFonts.figtree(),
                      validator: (v) {
                        if (v == null || v.trim().isEmpty) return 'Enter a subject';
                        return null;
                      },
                    ),
                    const SizedBox(height: 16),
                    Text('Message', style: GoogleFonts.figtree(fontWeight: FontWeight.w600, color: _navy)),
                    const SizedBox(height: 8),
                    TextFormField(
                      controller: _bodyController,
                      minLines: 8,
                      maxLines: 16,
                      decoration: InputDecoration(
                        filled: true,
                        fillColor: Colors.white,
                        hintText: 'Write the note you want every member to receive…',
                        hintStyle: GoogleFonts.figtree(color: Colors.black38),
                        alignLabelWithHint: true,
                        border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
                        enabledBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(12),
                          borderSide: BorderSide(color: _navy.withValues(alpha: 0.2)),
                        ),
                      ),
                      style: GoogleFonts.figtree(height: 1.4),
                      validator: (v) {
                        if (v == null || v.trim().isEmpty) return 'Enter a message';
                        return null;
                      },
                    ),
                    const SizedBox(height: 24),
                    FilledButton.icon(
                      onPressed: (_sending || _recipientCount == 0) ? null : _send,
                      icon: _sending
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                            )
                          : const Icon(Icons.send_outlined),
                      label: Text(
                        _sending ? 'Sending…' : 'Send to all accounts',
                        style: GoogleFonts.figtree(fontWeight: FontWeight.bold),
                      ),
                      style: FilledButton.styleFrom(
                        backgroundColor: _navy,
                        disabledBackgroundColor: _navy.withValues(alpha: 0.4),
                        padding: const EdgeInsets.symmetric(vertical: 16),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                      ),
                    ),
                  ],
                ),
              ),
            ),
    );
  }
}
