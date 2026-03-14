import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:uuid/uuid.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:flutter_application_1/services/api_service.dart';

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
  final List<Map<String, dynamic>> _messages = [];
  bool _isLoading = false;
  bool _isFirstMessage = true;

  final String sessionId = const Uuid().v4();

  Future<void> _sendMessage() async {
    if (_controller.text.trim().isEmpty) return;

    String userText = _controller.text;
    setState(() {
      _messages.add({"role": "user", "text": userText});
      _isLoading = true;
      _isFirstMessage = false;
    });
    _controller.clear();

    try {
      final data = await _apiService.sendMessage(userText, sessionId);
      setState(() {
        _messages.add({
          "role": "ai",
          "text": data['answer'],
          "sources": List<String>.from(data['sources'] ?? []),
        });
      });
    } catch (e) {
      setState(() {
        _messages.add({"role": "ai", "text": "Error: Could not connect to the server."});
      });
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
      // No floating margins in Drawer mode (Mobile)
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
              style: GoogleFonts.figtree(color: Colors.white, fontSize: 20, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            Container(height: 2, width: 40, color: const Color(0xFFD4AF37)),
            const Expanded(child: SizedBox()),
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
                    padding: EdgeInsets.symmetric(horizontal: isMobile ? 15 : 20, vertical: 20),
                    itemCount: _messages.length,
                    itemBuilder: (context, index) {
                      final msg = _messages[index];
                      return _buildChatBubble(msg, msg["role"] == "user", isMobile);
                    },
                  ),
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
                          "Welcome to the Nordins AI Assistant",
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
            borderRadius: BorderRadius.circular(32),
            border: Border.all(color: Colors.grey.shade300),
          ),
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
          child: Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _controller,
                  decoration: const InputDecoration(
                    hintText: "How can I help you?",
                    border: InputBorder.none,
                    contentPadding: EdgeInsets.symmetric(horizontal: 16),
                  ),
                  onSubmitted: (_) => _sendMessage(),
                ),
              ),
              Padding(
                padding: const EdgeInsets.all(4.0),
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
}