import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:uuid/uuid.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:flutter/services.dart';
import 'dart:convert';
import 'package:flutter/foundation.dart';

// ─── Constants ───────────────────────────────────────────────────────────────
const _navy = Color(0xFF1B264F);
const _gold = Color(0xFFD4AF37);
const _pink = Color(0xFFa1375a);
const _surface = Color(0xFFF4F4F9);

// ─── App Root ─────────────────────────────────────────────────────────────────
void main() => runApp(const SermonBrainApp());

class SermonBrainApp extends StatelessWidget {
  const SermonBrainApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(seedColor: _navy, primary: _navy, secondary: _gold),
        scaffoldBackgroundColor: Colors.white,
        textTheme: GoogleFonts.figtreeTextTheme(),
      ),
      home: const ChatScreen(),
    );
  }
}

// ─── Chat Screen ──────────────────────────────────────────────────────────────
class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> with TickerProviderStateMixin {
  // Services & controllers
  final _apiService = ApiService();
  final _controller = TextEditingController();
  final _scrollController = ScrollController();
  final _chatFocusNode = FocusNode();
  String sessionId = const Uuid().v4();

  // State
  final List<Map<String, dynamic>> _messages = [];
  List<String> _librarySermons = [];
  List<String> _previousSermons = [];
  bool _isLoading = false;
  bool _isFirstMessage = true;
  bool _isButtonTapped = false;
  bool _showBackToBottomButton = false;
  http.Client? _activeClient;

  // Animations
  late final AnimationController _pulseController = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 900),
  )..repeat(reverse: true);

  late final Animation<double> _wobbleAnimation =
      Tween<double>(begin: 0.7, end: 1.2).animate(
    CurvedAnimation(parent: _pulseController, curve: Curves.easeInOut),
  );

  late final Animation<double> _fadeAnimation =
      Tween<double>(begin: 0.2, end: 1.0).animate(
    CurvedAnimation(parent: _pulseController, curve: Curves.easeInOut),
  );

  // ─── Lifecycle ──────────────────────────────────────────────────────────────
  @override
  void initState() {
    super.initState();
    _scrollController.addListener(() {
      final isFarFromBottom =
          _scrollController.offset < _scrollController.position.maxScrollExtent - 500;
      if (isFarFromBottom != _showBackToBottomButton) {
        setState(() => _showBackToBottomButton = isFarFromBottom);
      }
    });
  }

  @override
  void dispose() {
    _pulseController.dispose();
    _scrollController.dispose();
    _controller.dispose();
    super.dispose();
  }

  // ─── Helpers ────────────────────────────────────────────────────────────────
  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  Future<void> _launchUrl(String urlString) async {
    final url = Uri.parse(urlString);
    if (await canLaunchUrl(url)) {
      await launchUrl(url, mode: LaunchMode.externalApplication);
    } else {
      debugPrint('Could not launch $urlString');
    }
  }

Future<void> _launchSermonDoc(String sermonName) async {
  final String origin = Uri.base.origin;

  final String stem = sermonName.toLowerCase().endsWith('.pdf')
      ? sermonName.substring(0, sermonName.length - 4)
      : sermonName;
  final String expectedPdf = '$stem.pdf';

  final Uri listUri = Uri.parse('$origin/api/ingested-documents/');

  try {
    final http.Response res = await http.get(listUri);
    if (res.statusCode != 200) {
      debugPrint('Sermon list failed: ${res.statusCode} ${res.body}');
      return;
    }

    final Map<String, dynamic> body =
        jsonDecode(res.body) as Map<String, dynamic>;
    final List<dynamic> docs =
        body['documents'] as List<dynamic>? ?? <dynamic>[];

    Map<String, dynamic>? match;
    for (final dynamic d in docs) {
      final Map<String, dynamic> map = d as Map<String, dynamic>;
      final String name =
          (map['source_name'] as String? ?? '').toLowerCase();
      if (name == expectedPdf.toLowerCase()) {
        match = map;
        break;
      }
    }

    if (match == null) {
      debugPrint('No ingested document matched source_name=$expectedPdf');
      return;
    }

    final String fileUrl = match['file_url'] as String;
    final Uri fileUri = Uri.parse(origin).resolve(fileUrl);

    await launchUrl(
      fileUri,
      mode: LaunchMode.externalApplication,
    );
  } catch (e, st) {
    debugPrint('Error opening sermon link: $e\n$st');
  }
}

  void _copyToClipboard(String text) async {
    await Clipboard.setData(ClipboardData(text: text));
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Copied to clipboard!'), duration: Duration(seconds: 2)),
      );
    }
  }

  List<String> _parseSources(dynamic raw) =>
      List<String>.from(raw ?? [])
          .map((s) => s.replaceAll('.md', '').replaceAll('.docx', '').replaceAll('.pdf', '').trim())
          .toSet()
          .take(5)
          .toList();

  // ─── Chat Actions ───────────────────────────────────────────────────────────
  void _clearChat() => setState(() {
        sessionId = const Uuid().v4();
        _messages.clear();
        _librarySermons.clear();
        _previousSermons.clear();
        _isFirstMessage = true;
        _showBackToBottomButton = false;
      });

  void _stopResponse() {
    if (_activeClient == null) return;
    _activeClient!.close();
    setState(() {
      _isLoading = false;
      _activeClient = null;
      _messages.add({"role": "ai", "text": "_Response cancelled by user._"});
    });
    _scrollToBottom();
  }

Future<void> _sendMessage() async {
  // Guard clause: prevent sending if already loading
  if (_isLoading) return; 

  final userText = _controller.text.trim();
  if (userText.isEmpty) return;
  _controller.clear();
  await _submitMessage(userText, addUserMessage: true);
}

  void _regenerateResponse(int index) {
    final userMessage = _messages[index - 1];
    if (userMessage["role"] != "user") return;
    final prompt = userMessage["text"] as String;
    setState(() => _messages.removeAt(index));
    _submitMessage(prompt, addUserMessage: false, regenerate: true);
  }

Future<void> _submitMessage(String userText, {required bool addUserMessage, bool regenerate = false}) async {
  setState(() {
    if (addUserMessage) {
      _messages.add({"role": "user", "text": userText});
      _isFirstMessage = false;
    }
    _isLoading = true;
    _activeClient = http.Client();
    
    // NOTE: We no longer clear or move sermons here. 
    // This keeps the current sources visible while the AI is "typing."
  });
  _scrollToBottom();

  try {
    final data = await _apiService.sendMessage(userText, sessionId, regenerate: regenerate);
    if (!mounted || _activeClient == null) return;

    setState(() {
      // 1. THE SHIFT: Now that the response is complete, 
      // move the "current" sermons to the "previous" list.
      if (_librarySermons.isNotEmpty) {
        _previousSermons = [..._librarySermons, ..._previousSermons]
            .toSet()
            .take(25) // Keeping the expanded limit we discussed
            .toList();
      }

      // 2. Add the new message to the chat
      _messages.add({
        "role": "ai",
        "text": data['answer'],
        "sources": List<String>.from(data['sources'] ?? []),
      });
      
      // 3. Update the current library with the NEW sources
      _librarySermons = _parseSources(data['sources']);
      
      // 4. Clean up: If a sermon is in 'Current', remove it from 'Previous'
      _previousSermons.removeWhere((s) => _librarySermons.contains(s));
    });
    _scrollToBottom();
  } catch (e) {
    if (_activeClient != null) {
      setState(() => _messages.add({"role": "ai", "text": "Error: Could not connect to the server."}));
      _scrollToBottom();
    }
  } finally {
    setState(() {
      _isLoading = false;
      _activeClient = null;
    });
  }
}

  // ─── Build ───────────────────────────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    final screenWidth = MediaQuery.of(context).size.width;
    final isMobileOrTablet = screenWidth < 1024;
    final isMobile = screenWidth < 600;

    return Scaffold(
      backgroundColor: Colors.white,
      drawer: isMobileOrTablet ? Drawer(child: _buildSidebar(isMobile: true)) : null,
      appBar: AppBar(
        centerTitle: false,
        backgroundColor: Colors.white,
        elevation: 0,
        toolbarHeight: isMobileOrTablet ? 100 : 120,
        title: Padding(
          padding: EdgeInsets.only(
            top: isMobileOrTablet ? 10.0 : 20.0,
            left: isMobileOrTablet ? 10.0 : 60.0,
          ),
          child: GestureDetector(
            onTap: () => _launchUrl("https://thenordins.org/"),
            child: MouseRegion(
              cursor: SystemMouseCursors.click,
              child: Image.asset(
                'assets/images/nordins_main_logo.png',
                height: isMobileOrTablet ? 80 : 95,
                fit: BoxFit.contain,
              ),
            ),
          ),
        ),
        actions: [
          if (!isMobile)
            Padding(
              padding: const EdgeInsets.only(top: 45.0),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  _buildNavButton("Home", () => _launchUrl("https://thenordins.org/")),
                  _buildNavButton("Store", () => _launchUrl("https://thenordins.org/store")),
                  _buildNavButton("Nordin's AI", () => debugPrint("Already on AI Page")),
                  const SizedBox(width: 100),
                ],
              ),
            ),
        ],
      ),
      body: Row(
        children: [
          if (!isMobileOrTablet) _buildSidebar(isMobile: false),
          Expanded(child: _buildChatInterface(isMobile)),
        ],
      ),
    );
  }

  // ─── Sidebar ─────────────────────────────────────────────────────────────────
  Widget _buildSidebar({required bool isMobile}) {
    return Container(
      width: isMobile ? double.infinity : 320,
      margin: isMobile ? EdgeInsets.zero : const EdgeInsets.only(left: 20, bottom: 30, top: 20),
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        borderRadius: isMobile ? BorderRadius.zero : BorderRadius.circular(32),
        gradient: const LinearGradient(
          colors: [_pink, _navy],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
      ),
      child: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (isMobile) ...[
              Row(children: [
                _buildNavButton("Home", () => _launchUrl("https://thenordins.org/"), textColor: Colors.white),
                _buildNavButton("Store", () => _launchUrl("https://thenordins.org/store"), textColor: Colors.white),
              ]),
              const SizedBox(height: 16),
              Container(height: 1, color: Colors.white24),
              const SizedBox(height: 20),
            ],
            Text("Sermon Library",
                style: GoogleFonts.figtree(color: Colors.white, fontSize: 20, fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            Container(height: 2, width: 40, color: _gold),
            const SizedBox(height: 20),
            Expanded(
              child: _librarySermons.isEmpty && _previousSermons.isEmpty
                  ? Text("Relevant sermons will appear here after you ask a question.",
                      style: GoogleFonts.figtree(color: Colors.white70, fontSize: 14))
                  : ListView(
                      children: [
                        ..._librarySermons.map(_buildSermonLink),
                        if (_previousSermons.isNotEmpty) ...[
                          const SizedBox(height: 20),
                          Row(children: [
                            const Expanded(child: Divider(color: Colors.white24)),
                            Padding(
                              padding: const EdgeInsets.symmetric(horizontal: 8.0),
                              child: Text("Last Question's Sources",
                                  style: GoogleFonts.figtree(
                                      color: _gold, fontSize: 12, fontWeight: FontWeight.bold)),
                            ),
                            const Expanded(child: Divider(color: Colors.white24)),
                          ]),
                          const SizedBox(height: 10),
                          ..._previousSermons.map(
                              (s) => Opacity(opacity: 0.7, child: _buildSermonLink(s))),
                        ],
                      ],
                    ),
            ),
            const SizedBox(height: 20),
            Center(
              child: Padding(
                padding: const EdgeInsets.only(bottom: 20.0),
                child: OutlinedButton.icon(
                  onPressed: _clearChat,
                  icon: const Icon(Icons.delete_sweep_outlined, color: _gold, size: 20),
                  label: Text("New Chat",
                      style: GoogleFonts.figtree(
                          color: _gold, fontWeight: FontWeight.bold, letterSpacing: 0.5)),
                  style: OutlinedButton.styleFrom(
                    side: const BorderSide(color: _gold, width: 1.5),
                    padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 14),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    foregroundColor: _gold.withOpacity(0.1),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  // ─── Chat Interface ───────────────────────────────────────────────────────────
  Widget _buildChatInterface(bool isMobile) {
    final mq = MediaQuery.of(context);
    final screenWidth = mq.size.width;
    final rightPadding = screenWidth >= 1900 ? (screenWidth - 1100) / 4 : 20.0;

    // Hide the welcome box when the keyboard is open (viewInsets.bottom > 0)
    // or when vertical space is too tight to display it cleanly (< 400px).
    final keyboardOpen = mq.viewInsets.bottom > 0;
    final enoughVerticalSpace = mq.size.height - mq.viewInsets.bottom > 400;
    final showWelcomeBox = _isFirstMessage && !keyboardOpen && enoughVerticalSpace;

    return Column(
      children: [
        Expanded(
          child: SelectionArea(
            child: Stack(
              children: [
                Center(
                  child: Container(
                    constraints: const BoxConstraints(maxWidth: 1100),
                    child: ListView.builder(
                      controller: _scrollController,
                      padding: EdgeInsets.symmetric(horizontal: isMobile ? 15 : 20, vertical: 20),
                      itemCount: _messages.length,
                      itemBuilder: (context, index) {
                        final msg = _messages[index];
                        return _buildChatBubble(msg, msg["role"] == "user", isMobile, index);
                      },
                    ),
                  ),
                ),
                if (_showBackToBottomButton)
                  Positioned(
                    bottom: 20,
                    right: rightPadding,
                    child: AnimatedSwitcher(
                      duration: const Duration(milliseconds: 300),
                      transitionBuilder: (child, animation) =>
                          ScaleTransition(scale: animation, child: child),
                      child: FloatingActionButton.small(
                        key: const ValueKey('scrollBtn'),
                        backgroundColor: _navy,
                        foregroundColor: _gold,
                        onPressed: _scrollToBottom,
                        child: const Icon(Icons.arrow_downward),
                      ),
                    ),
                  ),
                if (_isFirstMessage)
                  Center(
                    child: AnimatedContainer(
                      duration: const Duration(milliseconds: 1),
                      constraints: const BoxConstraints(maxWidth: 600),
                      margin: const EdgeInsets.all(20),
                      padding: const EdgeInsets.all(24),
                      decoration: BoxDecoration(
                        color: showWelcomeBox ? Colors.white : Colors.transparent,
                        borderRadius: BorderRadius.circular(20),
                        boxShadow: showWelcomeBox
                            ? [BoxShadow(color: Colors.black.withOpacity(0.08), blurRadius: 30)]
                            : [],
                        border: Border.all(
                          color: showWelcomeBox ? _gold : Colors.transparent,
                          width: 1.5,
                        ),
                      ),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          const Icon(Icons.auto_awesome, color: _gold, size: 40),
                          const SizedBox(height: 16),
                          Text(
                            "Welcome to the Nordin's AI Assistant",
                            textAlign: TextAlign.center,
                            style: TextStyle(
                              fontSize: isMobile ? 18 : 22,
                              fontWeight: FontWeight.bold,
                              color: _navy,
                            ),
                          ),
                          const SizedBox(height: 12),
                          Text(
                            "This tool is trained on sermon notes and resources. The AI may occasionally produce inaccurate information. Please verify insights with your Bible.",
                            textAlign: TextAlign.center,
                            style: GoogleFonts.figtree(fontSize: 14, color: Colors.black54),
                          ),
                        ],
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
        if (_isLoading)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 16.0),
            child: AnimatedBuilder(
              animation: _pulseController,
              builder: (_, __) => Opacity(
                opacity: _fadeAnimation.value,
                child: Transform.scale(
                  scale: _wobbleAnimation.value,
                  child: Image.asset('assets/images/nordins_transparent_logo.png', height: 48),
                ),
              ),
            ),
          ),
        _buildInputArea(isMobile),
      ],
    );
  }

  // ─── Widgets ──────────────────────────────────────────────────────────────────
Widget _buildChatBubble(Map<String, dynamic> msg, bool isUser, bool isMobile, int index) {
  // Logic to determine if this is the most recent message in the chat
  final isLastMessage = index == _messages.length - 1;

  return Align(
    alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
    child: Container(
      constraints: BoxConstraints(
        maxWidth: MediaQuery.of(context).size.width * (isMobile ? 0.85 : 0.7),
      ),
      margin: const EdgeInsets.symmetric(vertical: 8),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        gradient: isUser ? const LinearGradient(colors: [_pink, _navy]) : null,
        color: isUser ? null : _surface,
        borderRadius: BorderRadius.only(
          topLeft: const Radius.circular(16),
          topRight: const Radius.circular(16),
          bottomLeft: Radius.circular(isUser ? 16 : 0),
          bottomRight: Radius.circular(isUser ? 0 : 16),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          MarkdownBody(
            data: msg["text"],
            styleSheet: MarkdownStyleSheet(
              p: GoogleFonts.figtree(
                fontSize: 15, 
                color: isUser ? Colors.white : Colors.black87,
              ),
              strong: GoogleFonts.figtree(
                fontWeight: FontWeight.bold, 
                color: isUser ? Colors.white : Colors.black,
              ),
            ),
          ),
          if (!isUser) ...[
            const SizedBox(height: 10),
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                // The Copy button remains available for all messages
                _buildActionButton(
                  icon: Icons.copy_rounded,
                  tooltip: "Copy to clipboard",
                  onTap: () => _copyToClipboard(msg["text"]),
                ),
                
                // The Regenerate button only appears if this is the latest AI message
                if (isLastMessage) ...[
                  const SizedBox(width: 4),
                  _buildActionButton(
                    icon: Icons.refresh_rounded,
                    tooltip: "Regenerate response",
                    onTap: _isLoading ? null : () => _regenerateResponse(index),
                  ),
                ],
              ],
            ),
          ],
        ],
      ),
    ),
  );
}

  Widget _buildInputArea(bool isMobile) {
    return Container(
      padding: EdgeInsets.only(bottom: isMobile ? 15 : 30, left: isMobile ? 10 : 20, right: isMobile ? 10 : 20, top: 10),
      child: Center(
        child: Container(
          constraints: const BoxConstraints(maxWidth: 1100),
          decoration: BoxDecoration(
            color: _surface,
            borderRadius: BorderRadius.circular(24),
            border: Border.all(color: Colors.grey.shade300),
          ),
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Expanded(
                // Inside _buildInputArea...
              child: TextField(
                controller: _controller,
                focusNode: _chatFocusNode,
                onChanged: (_) => setState(() {}),
                minLines: 1,
                maxLines: 5,
                textInputAction: TextInputAction.send,
                // UPDATE THIS LINE:
                onSubmitted: (_) {
                  if (_controller.text.trim().isEmpty) {
                    _chatFocusNode.requestFocus();
                  } else if (!_isLoading) {
                    _sendMessage();
                  }
                },
                decoration: const InputDecoration(
                  hintText: "How can I help you?",
                  border: InputBorder.none,
                  contentPadding: EdgeInsets.only(left: 16, right: 16, top: 14, bottom: 14),
                ),
              ),
              ),
              Padding(
                padding: const EdgeInsets.only(bottom: 6.0, right: 4.0, left: 4.0),
                child: MouseRegion(
                  cursor: SystemMouseCursors.click,
                  child: GestureDetector(
                    onTapDown: (_) => setState(() => _isButtonTapped = true),
                    onTapUp: (_) => setState(() => _isButtonTapped = false),
                    onTapCancel: () => setState(() => _isButtonTapped = false),
                    onTap: _isLoading ? _stopResponse : _sendMessage,
                    child: AnimatedScale(
                      scale: _isButtonTapped ? 1.3 : (_controller.text.isNotEmpty || _isLoading ? 1.15 : 1.0),
                      duration: const Duration(milliseconds: 150),
                      curve: Curves.easeOutBack,
                      child: Container(
                        width: 40,
                        height: 40,
                        decoration: const BoxDecoration(
                          shape: BoxShape.circle,
                          gradient: LinearGradient(colors: [_pink, _navy]),
                          boxShadow: [BoxShadow(color: Colors.black26, blurRadius: 4, offset: Offset(0, 2))],
                        ),
                        child: Icon(_isLoading ? Icons.stop : Icons.arrow_upward,
                            color: Colors.white, size: _isLoading ? 22 : 18),
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildNavButton(String label, VoidCallback onTap, {Color textColor = Colors.black}) {
    bool isHovered = false;
    return StatefulBuilder(
      builder: (context, setState) => MouseRegion(
        onEnter: (_) => setState(() => isHovered = true),
        onExit: (_) => setState(() => isHovered = false),
        cursor: SystemMouseCursors.click,
        child: GestureDetector(
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 10.0),
            child: Stack(
              clipBehavior: Clip.none,
              children: [
                Padding(
                  padding: const EdgeInsets.only(bottom: 6.0),
                  child: Text(
                    label.toUpperCase(),
                    style: TextStyle(
                      fontFamily: 'Times New Roman',
                      color: textColor,
                      fontSize: 16,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                ),
                Positioned(
                  bottom: 0, left: 0, right: 0,
                  child: Align(
                    alignment: Alignment.centerLeft,
                    child: AnimatedContainer(
                      duration: const Duration(milliseconds: 300),
                      curve: Curves.easeInOut,
                      height: 2,
                      width: isHovered ? 200 : 0,
                      color: _gold,
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

  Widget _buildSermonLink(String sermonTitle) {
    bool isHovered = false;
    return StatefulBuilder(
      builder: (context, setState) => MouseRegion(
        onEnter: (_) => setState(() => isHovered = true),
        onExit: (_) => setState(() => isHovered = false),
        child: AnimatedContainer(
          duration: isHovered ? const Duration(milliseconds: 250) : Duration.zero,
          curve: isHovered ? Curves.easeOut : Curves.linear,
          margin: const EdgeInsets.symmetric(vertical: 4.0, horizontal: 12.0),
          transform: isHovered ? (Matrix4.identity()..translate(0.0, -3.0)) : Matrix4.identity(),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(20),
            color: isHovered ? Colors.white.withOpacity(0.07) : Colors.transparent,
            boxShadow: isHovered
                ? [BoxShadow(color: Colors.black.withOpacity(0.2), blurRadius: 15, offset: const Offset(0, 6), spreadRadius: -4)]
                : [],
          ),
          child: InkWell(
            borderRadius: BorderRadius.circular(20),
            onTap: () => _launchSermonDoc(sermonTitle),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 12.0, horizontal: 16.0),
              child: Row(
                children: [
                  const Icon(Icons.description_outlined, color: _gold, size: 18),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(sermonTitle,
                        style: GoogleFonts.figtree(
                            color: Colors.white, fontSize: 14, fontWeight: FontWeight.w400)),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildActionButton({required IconData icon, required String tooltip, required VoidCallback? onTap}) {
    return Tooltip(
      message: tooltip,
      waitDuration: const Duration(milliseconds: 500),
      child: StatefulBuilder(
        builder: (context, setState) {
          bool hovered = false;
          return StatefulBuilder(
            builder: (context, setHoverState) {
              return MouseRegion(
                onEnter: (_) => setHoverState(() => hovered = true),
                onExit: (_) => setHoverState(() => hovered = false),
                child: AnimatedContainer(
                  duration: hovered ? const Duration(milliseconds: 150) : Duration.zero,
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(8),
                    boxShadow: hovered
                        ? [BoxShadow(color: Colors.black.withOpacity(0.15), blurRadius: 6, spreadRadius: 1)]
                        : [],
                  ),
                  child: InkWell(
                    onTap: onTap,
                    borderRadius: BorderRadius.circular(8),
                    child: Padding(
                      padding: const EdgeInsets.all(6.0),
                      child: Icon(icon, size: 18, color: Colors.black45),
                    ),
                  ),
                ),
              );
            },
          );
        },
      ),
    );
  }
}