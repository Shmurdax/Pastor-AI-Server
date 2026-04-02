import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:uuid/uuid.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:url_launcher/url_launcher.dart';

void main() {
  runApp(const SermonBrainApp());
}

class SermonBrainApp extends StatelessWidget {
  const SermonBrainApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF1B264F),
          primary: const Color(0xFF1B264F),
          secondary: const Color(0xFFD4AF37),
        ),
        scaffoldBackgroundColor: Colors.white,
        textTheme: GoogleFonts.figtreeTextTheme(),
      ),
      home: const ChatScreen(),
    );
  }
}

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}
class _ChatScreenState extends State<ChatScreen> {
  final ApiService _apiService = ApiService();
  final TextEditingController _controller = TextEditingController();
  
  // NEW: Added this controller
  final ScrollController _scrollController = ScrollController();

  final List<Map<String, dynamic>> _messages = [];
  List<String> _librarySermons = []; 
  List<String> _previousSermons = [];
  bool _isLoading = false;
  bool _isFirstMessage = true;
  
  // NEW: Added this toggle
  bool _showBackToBottomButton = false;

  final String sessionId = const Uuid().v4();

Future<void> _launchSermonDoc(String sermonName) async {
  // 1. Your GitHub permalink base URL (Notice 'tree' is changed to 'blob')
  final String baseUrl = "https://github.com/Shmurdax/Pastor-AI-Server/blob/ab5913f6d76dc38d97a8e947193230ef956b0737/Pastor-AI-main/Pastor-Data/";
  
  // 2. Combine the base URL, the sermon name, and the file extension.
  // IMPORTANT: Ensure '.docx' matches the actual file types in your GitHub folder. 
  // If they are markdown files, change this to '.md'.
  final String fullUrl = '$baseUrl$sermonName.docx';
  
  final Uri url = Uri.parse(fullUrl);

  try {
    if (await canLaunchUrl(url)) {
      // This will open a new browser tab directly to the file on GitHub
      await launchUrl(
        url,
        mode: LaunchMode.externalApplication, 
      );
    } else {
      debugPrint("Could not launch $fullUrl");
    }
  } catch (e) {
    debugPrint("Error opening GitHub link: $e");
  }
}

@override
  void initState() {
    super.initState();
    _scrollController.addListener(() {
      // Check if the user is more than 300 pixels away from the bottom
      // maxScrollExtent is the total length of the list
      bool isFarFromBottom = _scrollController.offset < 
                             (_scrollController.position.maxScrollExtent - 300);

      // We only call setState if the status actually changes to avoid lag
      if (isFarFromBottom && !_showBackToBottomButton) {
        setState(() => _showBackToBottomButton = true);
      } else if (!isFarFromBottom && _showBackToBottomButton) {
        setState(() => _showBackToBottomButton = false);
      }
    });
  }

  @override
  void dispose() {
    _scrollController.dispose();
    _controller.dispose();
    super.dispose();
  }

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

  // <--- SECTION 1 STOPS HERE. The next line in your code should be:
  // Future<void> _sendMessage() async { ...
 Future<void> _sendMessage() async {
    if (_controller.text.trim().isEmpty) return;

    String userText = _controller.text;
    setState(() {
      _messages.add({"role": "user", "text": userText});
      _isLoading = true;
      _isFirstMessage = false;
    });
    _controller.clear();

    // 1. Scroll immediately after the user's message is added to the list
    _scrollToBottom();

    try {
      final data = await _apiService.sendMessage(userText, sessionId);
      setState(() {
        _messages.add({
          "role": "ai",
          "text": data['answer'],
          "sources": List<String>.from(data['sources'] ?? []),
        });

        // Move the OLD current sermons to the PREVIOUS list
        // We use .toSet() to ensure we don't have duplicates in the history
        _previousSermons = [..._librarySermons, ..._previousSermons].toSet().toList();

        // Set the NEW sermons as the current list
        _librarySermons = List<String>.from(data['sources'] ?? [])
            .map((s) => s.replaceAll('.md', '').replaceAll('.docx', '').trim().replaceAll('.pdf', ''))
            .toSet()
            .take(5)
            .toList();
      });

      // 2. Scroll again after the AI response is rendered
      _scrollToBottom();
      
    } catch (e) {
      setState(() {
        _messages.add({"role": "ai", "text": "Error: Could not connect to the server."});
      });

      // 3. Scroll if an error message appears so the user sees it
      _scrollToBottom();

    } finally {
      setState(() { _isLoading = false; });
    }
  }

  @override
  Widget build(BuildContext context) {
    // Check if the viewport is mobile-sized
    final bool isMobile = MediaQuery.of(context).size.width < 800;

    return Scaffold(
      backgroundColor: Colors.white,
      // On mobile, the sidebar becomes a Drawer
      drawer: isMobile ? Drawer(child: _buildSidebar(isMobile: true)) : null,
      appBar: AppBar(
        centerTitle: false,
        backgroundColor: Colors.white,
        elevation: 0,
        toolbarHeight: isMobile ? 80 : 120,
        // The menu icon (hamburger) automatically appears on mobile because of the 'drawer'
        title: Padding(
          padding: EdgeInsets.only(
            top: 20.0, 
            left: isMobile ? 0 : 40.0, 
          ),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                "THE", 
                style: GoogleFonts.openSans(
                  color: const Color(0xFF1B264F),
                  fontSize: isMobile ? 12 : 16,
                  fontWeight: FontWeight.w300,
                  letterSpacing: 2.0,
                ),
              ),
              Text(
                "NORDINS", 
                style: GoogleFonts.playfairDisplay(
                  color: const Color(0xFF1B264F),
                  fontSize: isMobile ? 28 : 38,
                  fontWeight: FontWeight.w400,
                  fontStyle: FontStyle.italic,
                  letterSpacing: 0.5,
                ),
              ),
            ],
          ),
        ),
      ),
      body: Row(
        children: [
          // Sidebar only shows permanently on Desktop
          if (!isMobile) _buildSidebar(isMobile: false),
          Expanded(
            child: _buildChatInterface(isMobile),
          ),
        ],
      ),
    );
  }

Widget _buildSidebar({required bool isMobile}) {
    return Container(
      width: 260,
      margin: isMobile ? EdgeInsets.zero : const EdgeInsets.only(left: 20, bottom: 30, top: 20), 
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        borderRadius: isMobile ? BorderRadius.zero : BorderRadius.circular(32),
        gradient: const LinearGradient(
          colors: [Color(0xFFa1375a), Color(0xFF1B264F)],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
      ),
      child: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              "Sermon Library",
              style: GoogleFonts.figtree(
                color: Colors.white, 
                fontSize: 20, 
                fontWeight: FontWeight.bold
              ),
            ),
            const SizedBox(height: 8),
            Container(height: 2, width: 40, color: const Color(0xFFD4AF37)),
            const SizedBox(height: 20),
            
            // MODIFIED: This section now dynamically lists the sermons
            Expanded(
              child: _librarySermons.isEmpty && _previousSermons.isEmpty
                  ? Text(
                      "Relevant sermons will appear here after you ask a question.",
                      style: GoogleFonts.figtree(color: Colors.white70, fontSize: 14),
                    )
                  : ListView(
                      children: [
                        // --- SECTION 1: CURRENT SOURCES ---
                        ..._librarySermons.map((sermon) => _buildSermonLink(sermon)),

                        // --- SECTION 2: DIVIDER & HISTORY ---
                        if (_previousSermons.isNotEmpty) ...[
                          const SizedBox(height: 20),
                          Row(
                            children: [
                              const Expanded(child: Divider(color: Colors.white24)),
                              Padding(
                                padding: const EdgeInsets.symmetric(horizontal: 8.0),
                                child: Text(
                                  "Last Question's Sources",
                                  style: GoogleFonts.figtree(
                                    color: const Color(0xFFD4AF37),
                                    fontSize: 12,
                                    fontWeight: FontWeight.bold,
                                  ),
                                ),
                              ),
                              const Expanded(child: Divider(color: Colors.white24)),
                            ],
                          ),
                          const SizedBox(height: 10),
                          // Display previous sermons with slightly more transparency
                          ..._previousSermons.map((sermon) => Opacity(
                                opacity: 0.7,
                                child: _buildSermonLink(sermon),
                              )),
                        ],
                      ],
                    ),
            ),
          
          const SizedBox(height: 20),
          Center(
            child: Text(
              "AI",
              style: GoogleFonts.figtree(
                color: const Color(0xFFD4AF37),
                fontWeight: FontWeight.w900,
                letterSpacing: 2.0,
                fontSize: 24,
              ),
            ),
          ),
        ],
      ),
    ),
  );
}

Widget _buildChatInterface(bool isMobile) {
    return Column(
      children: [
        Expanded(
          child: Stack(
            children: [
              Center(
                child: Container(
                  constraints: const BoxConstraints(maxWidth: 1100),
                  child: ListView.builder(
                    // LINKED: This tells the list to use your scroll logic
                    controller: _scrollController,
                    padding: EdgeInsets.symmetric(horizontal: isMobile ? 15 : 20, vertical: 20),
                    itemCount: _messages.length,
                    itemBuilder: (context, index) {
                      final msg = _messages[index];
                      return _buildChatBubble(msg, msg["role"] == "user", isMobile);
                    },
                  ),
                ),
              ),

              // NEW: The floating "Scroll to Bottom" button logic
              if (_showBackToBottomButton)
                // NEW: Smooth Animated Scroll to Bottom Button
              Positioned(
                bottom: 20,
                right: 20,
                child: AnimatedSwitcher(
                  duration: const Duration(milliseconds: 300),
                  transitionBuilder: (Widget child, Animation<double> animation) {
                    return ScaleTransition(scale: animation, child: child);
                  },
                  child: _showBackToBottomButton
                      ? FloatingActionButton.small(
                          key: const ValueKey('scrollBtn'), // Necessary for AnimatedSwitcher
                          backgroundColor: const Color(0xFF1B264F),
                          foregroundColor: const Color(0xFFD4AF37),
                          onPressed: _scrollToBottom,
                          child: const Icon(Icons.arrow_downward),
                        )
                      : const SizedBox.shrink(),
                ),
              ),

              if (_isFirstMessage)
                Center(
                  child: Container(
                    constraints: const BoxConstraints(maxWidth: 600),
                    margin: const EdgeInsets.all(20),
                    padding: const EdgeInsets.all(24),
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(20),
                      boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.08), blurRadius: 30)],
                      border: Border.all(color: const Color(0xFFD4AF37), width: 1.5),
                    ),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(Icons.auto_awesome, color: Color(0xFFD4AF37), size: 40),
                        const SizedBox(height: 16),
                        Text(
                          "Welcome to the Nordin's AI Assistant",
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            fontSize: isMobile ? 18 : 22, 
                            fontWeight: FontWeight.bold, 
                            color: const Color(0xFF1B264F)
                          ),
                        ),
                        const SizedBox(height: 12),
                        Text(
                          "This tool is trained on sermon notes and resources. Please verify insights with your Bible.",
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
        if (_isLoading)
          const LinearProgressIndicator(color: Color(0xFFD4AF37), backgroundColor: Colors.transparent),
        _buildInputArea(isMobile),
      ],
    );
  }

  Widget _buildChatBubble(Map<String, dynamic> msg, bool isUser, bool isMobile) {
    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        // On mobile, bubbles can take up 85% width; on PC, only 70%
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * (isMobile ? 0.85 : 0.7),
        ),
        margin: const EdgeInsets.symmetric(vertical: 8),
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          gradient: isUser 
            ? const LinearGradient(
                colors: [Color(0xFFa1375a), Color(0xFF1B264F)],
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
              ) 
            : null,
          color: isUser ? null : const Color(0xFFF4F4F9),
          borderRadius: BorderRadius.only(
            topLeft: const Radius.circular(16),
            topRight: const Radius.circular(16),
            bottomLeft: Radius.circular(isUser ? 16 : 0),
            bottomRight: Radius.circular(isUser ? 0 : 16),
          ),
          boxShadow: isUser ? [
            BoxShadow(color: Colors.black.withOpacity(0.1), blurRadius: 8, offset: const Offset(0, 3))
          ] : [],
        ),
        child: MarkdownBody(
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
      ),
    );
  }

Widget _buildInputArea(bool isMobile) {
    return Container(
      padding: EdgeInsets.only(
        bottom: isMobile ? 15 : 30, 
        left: isMobile ? 10 : 20, 
        right: isMobile ? 10 : 20, 
        top: 10
      ),
      child: Center(
        child: Container(
          constraints: const BoxConstraints(maxWidth: 1100),
          decoration: BoxDecoration(
            color: const Color(0xFFF4F4F9),
            borderRadius: BorderRadius.circular(24), 
            border: Border.all(color: Colors.grey.shade300),
          ),
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.end, 
            children: [
              Expanded(
                child: TextField(
                  controller: _controller,
                  minLines: 1, 
                  maxLines: 5, // Allows the box to grow as text wraps naturally
                  textInputAction: TextInputAction.send, // Tells the keyboard "Enter" means send
                  onSubmitted: (_) => _sendMessage(), // Fires the send function when Enter is pressed
                  decoration: const InputDecoration(
                    hintText: "How can I help you?",
                    border: InputBorder.none,
                    contentPadding: EdgeInsets.only(left: 16, right: 16, top: 14, bottom: 14),
                  ),
                ),
              ),
              Padding(
                padding: const EdgeInsets.only(bottom: 6.0, right: 4.0, left: 4.0),
                child: Container(
                  width: 40, height: 40,
                  decoration: const BoxDecoration(
                    shape: BoxShape.circle,
                    gradient: LinearGradient(colors: [Color(0xFFa1375a), Color(0xFF1B264F)]),
                  ),
                  child: IconButton(
                    icon: const Icon(Icons.arrow_upward, color: Colors.white, size: 18),
                    onPressed: _sendMessage,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
  // ... existing _buildInputArea method above ...

  Widget _buildSermonLink(String sermonTitle) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4.0),
      child: InkWell(
        borderRadius: BorderRadius.circular(8),
        onTap: () => _launchSermonDoc(sermonTitle),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 8.0, horizontal: 4.0),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Icon(Icons.description_outlined, color: Color(0xFFD4AF37), size: 18),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  sermonTitle,
                  style: GoogleFonts.figtree(
                    color: Colors.white,
                    fontSize: 14,
                    fontWeight: FontWeight.w500,
                    decoration: TextDecoration.underline,
                    decorationColor: Colors.white38,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
} // This is the very last closing brace of your _ChatScreenState class
