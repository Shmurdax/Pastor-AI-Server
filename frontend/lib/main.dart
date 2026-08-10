import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_application_1/screens/media_library_screen.dart';
import 'package:flutter_application_1/screens/prayer_inbox_screen.dart';
import 'package:flutter_application_1/screens/subscriptions_screen.dart';
import 'package:flutter_application_1/widgets/church_events_nav_overlay.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:flutter_application_1/widgets/chat_nav_actions.dart';
import 'package:flutter_application_1/widgets/google_auth_button.dart';
import 'package:flutter_application_1/widgets/nordins_ai_nav_menu.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;
import 'package:url_launcher/url_launcher.dart';
import 'package:uuid/uuid.dart';

// ─── Constants ───────────────────────────────────────────────────────────────
const _navy = Color(0xFF1B264F);
const _gold = Color(0xFFD4AF37);
const _pink = Color(0xFFa1375a);
const _surface = Color(0xFFF4F4F9);
/// Matches [_buildInputArea] bottom padding and desktop sermon sidebar `margin.bottom`.
const _layoutBottomInsetDesktop = 30.0;
const _layoutBottomInsetMobile = 15.0;
/// Min height from [_buildInputArea] top padding through the send row (excludes bottom inset).
const _chatInputBarBlockHeight = 74.0;
const _prayerFabClearanceBelowWide = 1900.0;

/// Prevents Material 3 stretch / glow from painting grey at the viewport edge on web.
class _NoOverscrollScrollBehavior extends MaterialScrollBehavior {
  const _NoOverscrollScrollBehavior();

  @override
  Widget buildOverscrollIndicator(
    BuildContext context,
    Widget child,
    ScrollableDetails details,
  ) {
    return child;
  }
}

// ─── Token Storage ───────────────────────────────────────────────────────────
class TokenStorage {
  static const _tokenKey = 'auth_token';
  static const _userKey = 'auth_user';
  static const _sessionPrefix = 'chat_session_';
  static const _historyPrefix = 'chat_history_';

  const TokenStorage();

  Future<void> saveSession({required String token, required AuthUser user}) async {
    final userJson = jsonEncode(user.toJson());
    if (kIsWeb) {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_tokenKey, token);
      await prefs.setString(_userKey, userJson);
      return;
    }
    const storage = FlutterSecureStorage();
    await storage.write(key: _tokenKey, value: token);
    await storage.write(key: _userKey, value: userJson);
  }

  Future<({String? token, AuthUser? user})> loadSession() async {
    if (kIsWeb) {
      final prefs = await SharedPreferences.getInstance();
      final token = prefs.getString(_tokenKey);
      final userJson = prefs.getString(_userKey);
      if (token == null || userJson == null) return (token: null, user: null);
      return (token: token, user: AuthUser.fromJson(jsonDecode(userJson) as Map<String, dynamic>));
    }
    const storage = FlutterSecureStorage();
    final token = await storage.read(key: _tokenKey);
    final userJson = await storage.read(key: _userKey);
    if (token == null || userJson == null) return (token: null, user: null);
    return (token: token, user: AuthUser.fromJson(jsonDecode(userJson) as Map<String, dynamic>));
  }

  Future<void> clearSession() async {
    if (kIsWeb) {
      final prefs = await SharedPreferences.getInstance();
      await prefs.remove(_tokenKey);
      await prefs.remove(_userKey);
      return;
    }
    const storage = FlutterSecureStorage();
    await storage.delete(key: _tokenKey);
    await storage.delete(key: _userKey);
  }

  Future<String?> loadChatSessionId(String userId) async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString('$_sessionPrefix$userId');
  }

  Future<void> saveChatSessionId(String userId, String sessionId) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('$_sessionPrefix$userId', sessionId);
  }

  Future<List<Map<String, dynamic>>> loadChatHistory(String userId) async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString('$_historyPrefix$userId');
    if (raw == null || raw.isEmpty) return [];
    final decoded = jsonDecode(raw);
    if (decoded is! List) return [];
    return decoded
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
  }

  Future<void> saveChatHistory(String userId, List<Map<String, dynamic>> entries) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('$_historyPrefix$userId', jsonEncode(entries));
  }
}

enum _SidebarPanel { sermonLibrary, previousChats }

// ─── Auth Controller ───────────────────────────────────────────────────────────
class AuthController extends ChangeNotifier {
  AuthController({AuthService? authService, TokenStorage? tokenStorage})
      : _authService = authService ?? AuthService(),
        _tokenStorage = tokenStorage ?? const TokenStorage() {
    _restoreSession();
  }

  final AuthService _authService;
  final TokenStorage _tokenStorage;

  AuthUser? user;
  String? token;
  bool isLoading = false;
  String? error;

  bool get isAuthenticated => token != null && user != null;

  Future<void> _restoreSession() async {
    final saved = await _tokenStorage.loadSession();
    if (saved.token == null || saved.user == null) return;

    if (kUseMockAuth) {
      token = saved.token;
      user = saved.user;
      notifyListeners();
      return;
    }

    try {
      final me = await _authService.getMe(saved.token!);
      token = saved.token;
      user = me;
      notifyListeners();
    } catch (_) {
      await _tokenStorage.clearSession();
    }
  }

  Future<bool> login({required String email, required String password}) =>
      _authenticate(() => _authService.login(email: email, password: password));

  Future<bool> register({
    required String name,
    required String email,
    required String password,
  }) =>
      _authenticate(() => _authService.register(name: name, email: email, password: password));

  Future<bool> signInWithGoogle() =>
      _authenticate(_authService.signInWithGoogle);

  Future<bool> signInWithGoogleAccount(GoogleSignInAccount account) =>
      _authenticate(() => _authService.signInWithGoogleAccount(account));

  Future<bool> _authenticate(Future<AuthResult> Function() action) async {
    isLoading = true;
    error = null;
    notifyListeners();
    try {
      final result = await action();
      token = result.token;
      user = result.user;
      await _tokenStorage.saveSession(token: result.token, user: result.user);
      isLoading = false;
      notifyListeners();
      return true;
    } on AuthException catch (e) {
      error = e.message;
    } catch (e) {
      // Surface the real error — the old generic message hid web GIS failures.
      final msg = e.toString().replaceFirst(RegExp(r'^Exception:\s*'), '');
      error = msg.isEmpty ? 'Something went wrong. Please try again.' : msg;
    }
    isLoading = false;
    notifyListeners();
    return false;
  }

  Future<void> logout() async {
    final currentToken = token;
    token = null;
    user = null;
    error = null;
    await _tokenStorage.clearSession();
    if (currentToken != null) await _authService.logout(currentToken);
    notifyListeners();
  }

  void clearError() {
    if (error == null) return;
    error = null;
    notifyListeners();
  }
}

// ─── App Root ─────────────────────────────────────────────────────────────────
void main() => runApp(
      ChangeNotifierProvider(
        create: (_) => AuthController(),
        child: const SermonBrainApp(),
      ),
    );

class SermonBrainApp extends StatelessWidget {
  const SermonBrainApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      scrollBehavior: const _NoOverscrollScrollBehavior(),
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(
          seedColor: _navy,
          primary: _navy,
          secondary: _gold,
          surface: Colors.white,
        ),
        scaffoldBackgroundColor: Colors.white,
        textTheme: GoogleFonts.figtreeTextTheme(),
      ),
      home: const ChatScreen(),
    );
  }
}

// ─── Login Screen ─────────────────────────────────────────────────────────────
class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  final _formKey = GlobalKey<FormState>();
  bool _obscurePassword = true;
  StreamSubscription<GoogleSignInAccount?>? _googleSub;
  bool _handlingGoogle = false;

  @override
  void initState() {
    super.initState();
    // Web GIS renderButton authenticates via onCurrentUserChanged (real idToken).
    if (kIsWeb && AuthService.isGoogleConfigured) {
      _googleSub = AuthService.googleSignIn.onCurrentUserChanged.listen(_onGoogleUser);
    }
  }

  @override
  void dispose() {
    _googleSub?.cancel();
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _onGoogleUser(GoogleSignInAccount? account) async {
    if (account == null || _handlingGoogle || !mounted) return;
    _handlingGoogle = true;
    final auth = context.read<AuthController>();
    auth.clearError();
    final ok = await auth.signInWithGoogleAccount(account);
    _handlingGoogle = false;
    if (!mounted) return;
    if (ok) Navigator.of(context).pop(true);
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    final auth = context.read<AuthController>();
    auth.clearError();
    final ok = await auth.login(
      email: _emailController.text.trim(),
      password: _passwordController.text,
    );
    if (!mounted) return;
    if (ok) Navigator.of(context).pop(true);
  }

  Future<void> _googleSignIn() async {
    // Mobile / non-web only. Web uses GoogleAuthButton → GIS renderButton.
    final auth = context.read<AuthController>();
    auth.clearError();
    final ok = await auth.signInWithGoogle();
    if (!mounted) return;
    if (ok) Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthController>();
    final isMobile = MediaQuery.of(context).size.width < 600;

    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        backgroundColor: Colors.white,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, color: _navy),
          onPressed: () => Navigator.of(context).pop(),
        ),
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: EdgeInsets.all(isMobile ? 24 : 40),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 440),
            child: Form(
              key: _formKey,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Center(
                    child: Image.asset(
                      'assets/images/nordins_main_logo.png',
                      height: isMobile ? 80 : 95,
                      fit: BoxFit.contain,
                    ),
                  ),
                  const SizedBox(height: 24),
                  Text('Please login to continue',
                      textAlign: TextAlign.center,
                      style: GoogleFonts.figtree(fontSize: 28, fontWeight: FontWeight.bold, color: _navy)),
                  const SizedBox(height: 8),
                  Text('Sign in to save your chat history across devices.',
                      textAlign: TextAlign.center,
                      style: GoogleFonts.figtree(fontSize: 14, color: Colors.black54)),
                  const SizedBox(height: 32),
                  if (auth.error != null) ...[
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: Colors.red.shade50,
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: Colors.red.shade200),
                      ),
                      child: Text(auth.error!, style: GoogleFonts.figtree(color: Colors.red.shade800, fontSize: 14)),
                    ),
                    const SizedBox(height: 16),
                  ],
                  TextFormField(
                    controller: _emailController,
                    keyboardType: TextInputType.emailAddress,
                    decoration: _authInputDecoration('Email'),
                    validator: (v) {
                      if (v == null || v.trim().isEmpty) return 'Enter your email';
                      if (!v.contains('@')) return 'Enter a valid email';
                      return null;
                    },
                  ),
                  const SizedBox(height: 16),
                  TextFormField(
                    controller: _passwordController,
                    obscureText: _obscurePassword,
                    decoration: _authInputDecoration('Password').copyWith(
                      suffixIcon: IconButton(
                        icon: Icon(_obscurePassword ? Icons.visibility_off : Icons.visibility, color: _navy),
                        onPressed: () => setState(() => _obscurePassword = !_obscurePassword),
                      ),
                    ),
                    validator: (v) => (v == null || v.isEmpty) ? 'Enter your password' : null,
                  ),
                  const SizedBox(height: 24),
                  FilledButton(
                    onPressed: auth.isLoading ? null : _submit,
                    style: FilledButton.styleFrom(
                      backgroundColor: _navy,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 16),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    ),
                    child: auth.isLoading
                        ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                        : Text('Sign in', style: GoogleFonts.figtree(fontWeight: FontWeight.bold, fontSize: 16)),
                  ),
                  const SizedBox(height: 12),
                  GoogleAuthButton(
                    enabled: !auth.isLoading && AuthService.isGoogleConfigured,
                    onPressed: auth.isLoading ? null : _googleSignIn,
                    label: 'Sign in with Google',
                  ),
                  if (!AuthService.isGoogleConfigured) ...[
                    const SizedBox(height: 8),
                    Text(
                      'Google Sign-In is not configured (missing GOOGLE_CLIENT_ID).',
                      textAlign: TextAlign.center,
                      style: GoogleFonts.figtree(fontSize: 12, color: Colors.black45),
                    ),
                  ],
                  const SizedBox(height: 16),
                  TextButton(
                    onPressed: auth.isLoading ? null : () => Navigator.of(context).pop(),
                    child: Text('Continue as guest', style: GoogleFonts.figtree(color: Colors.black54)),
                  ),
                  const SizedBox(height: 8),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Text("Don't have an account? ", style: GoogleFonts.figtree(color: Colors.black54)),
                      TextButton(
                        onPressed: auth.isLoading
                            ? null
                            : () => Navigator.of(context).pushReplacement(
                                  MaterialPageRoute(builder: (_) => const RegisterScreen()),
                                ),
                        child: Text('Create one', style: GoogleFonts.figtree(color: _pink, fontWeight: FontWeight.bold)),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

// ─── Register Screen ──────────────────────────────────────────────────────────
class RegisterScreen extends StatefulWidget {
  const RegisterScreen({super.key});

  @override
  State<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends State<RegisterScreen> {
  final _nameController = TextEditingController();
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  final _confirmController = TextEditingController();
  final _formKey = GlobalKey<FormState>();
  bool _obscurePassword = true;
  bool _obscureConfirm = true;
  StreamSubscription<GoogleSignInAccount?>? _googleSub;
  bool _handlingGoogle = false;

  @override
  void initState() {
    super.initState();
    if (kIsWeb && AuthService.isGoogleConfigured) {
      _googleSub = AuthService.googleSignIn.onCurrentUserChanged.listen(_onGoogleUser);
    }
  }

  @override
  void dispose() {
    _googleSub?.cancel();
    _nameController.dispose();
    _emailController.dispose();
    _passwordController.dispose();
    _confirmController.dispose();
    super.dispose();
  }

  Future<void> _onGoogleUser(GoogleSignInAccount? account) async {
    if (account == null || _handlingGoogle || !mounted) return;
    _handlingGoogle = true;
    final auth = context.read<AuthController>();
    auth.clearError();
    final ok = await auth.signInWithGoogleAccount(account);
    _handlingGoogle = false;
    if (!mounted) return;
    if (ok) Navigator.of(context).pop(true);
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    final auth = context.read<AuthController>();
    auth.clearError();
    final ok = await auth.register(
      name: _nameController.text.trim(),
      email: _emailController.text.trim(),
      password: _passwordController.text,
    );
    if (!mounted) return;
    if (ok) Navigator.of(context).pop(true);
  }

  Future<void> _googleSignIn() async {
    final auth = context.read<AuthController>();
    auth.clearError();
    final ok = await auth.signInWithGoogle();
    if (!mounted) return;
    if (ok) Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthController>();
    final isMobile = MediaQuery.of(context).size.width < 600;

    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        backgroundColor: Colors.white,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, color: _navy),
          onPressed: () => Navigator.of(context).pushReplacement(
            MaterialPageRoute(builder: (_) => const LoginScreen()),
          ),
        ),
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: EdgeInsets.all(isMobile ? 24 : 40),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 440),
            child: Form(
              key: _formKey,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Center(
                    child: Image.asset(
                      'assets/images/nordins_main_logo.png',
                      height: isMobile ? 80 : 95,
                      fit: BoxFit.contain,
                    ),
                  ),
                  const SizedBox(height: 24),
                  Text('Create your account',
                      textAlign: TextAlign.center,
                      style: GoogleFonts.figtree(fontSize: 28, fontWeight: FontWeight.bold, color: _navy)),
                  const SizedBox(height: 8),
                  Text('Join to save conversations and pick up where you left off.',
                      textAlign: TextAlign.center,
                      style: GoogleFonts.figtree(fontSize: 14, color: Colors.black54)),
                  const SizedBox(height: 32),
                  if (auth.error != null) ...[
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: Colors.red.shade50,
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: Colors.red.shade200),
                      ),
                      child: Text(auth.error!, style: GoogleFonts.figtree(color: Colors.red.shade800, fontSize: 14)),
                    ),
                    const SizedBox(height: 16),
                  ],
                  TextFormField(
                    controller: _nameController,
                    textCapitalization: TextCapitalization.words,
                    decoration: _authInputDecoration('Full name'),
                    validator: (v) => (v == null || v.trim().isEmpty) ? 'Enter your name' : null,
                  ),
                  const SizedBox(height: 16),
                  TextFormField(
                    controller: _emailController,
                    keyboardType: TextInputType.emailAddress,
                    decoration: _authInputDecoration('Email'),
                    validator: (v) {
                      if (v == null || v.trim().isEmpty) return 'Enter your email';
                      if (!v.contains('@')) return 'Enter a valid email';
                      return null;
                    },
                  ),
                  const SizedBox(height: 16),
                  TextFormField(
                    controller: _passwordController,
                    obscureText: _obscurePassword,
                    decoration: _authInputDecoration('Password').copyWith(
                      suffixIcon: IconButton(
                        icon: Icon(_obscurePassword ? Icons.visibility_off : Icons.visibility, color: _navy),
                        onPressed: () => setState(() => _obscurePassword = !_obscurePassword),
                      ),
                    ),
                    validator: (v) => (v == null || v.length < 8) ? 'Password must be at least 8 characters' : null,
                  ),
                  const SizedBox(height: 16),
                  TextFormField(
                    controller: _confirmController,
                    obscureText: _obscureConfirm,
                    decoration: _authInputDecoration('Confirm password').copyWith(
                      suffixIcon: IconButton(
                        icon: Icon(_obscureConfirm ? Icons.visibility_off : Icons.visibility, color: _navy),
                        onPressed: () => setState(() => _obscureConfirm = !_obscureConfirm),
                      ),
                    ),
                    validator: (v) {
                      if (v != _passwordController.text) return 'Passwords do not match';
                      return null;
                    },
                  ),
                  const SizedBox(height: 24),
                  FilledButton(
                    onPressed: auth.isLoading ? null : _submit,
                    style: FilledButton.styleFrom(
                      backgroundColor: _navy,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 16),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    ),
                    child: auth.isLoading
                        ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                        : Text('Create account', style: GoogleFonts.figtree(fontWeight: FontWeight.bold, fontSize: 16)),
                  ),
                  const SizedBox(height: 12),
                  GoogleAuthButton(
                    enabled: !auth.isLoading && AuthService.isGoogleConfigured,
                    onPressed: auth.isLoading ? null : _googleSignIn,
                    label: 'Sign up with Google',
                  ),
                  const SizedBox(height: 16),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Text('Already have an account? ', style: GoogleFonts.figtree(color: Colors.black54)),
                      TextButton(
                        onPressed: auth.isLoading
                            ? null
                            : () => Navigator.of(context).pushReplacement(
                                  MaterialPageRoute(builder: (_) => const LoginScreen()),
                                ),
                        child: Text('Sign in', style: GoogleFonts.figtree(color: _pink, fontWeight: FontWeight.bold)),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

InputDecoration _authInputDecoration(String label) => InputDecoration(
      labelText: label,
      labelStyle: GoogleFonts.figtree(color: _navy),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide(color: Colors.grey.shade300),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: _gold, width: 2),
      ),
    );

// ─── Chat Screen ──────────────────────────────────────────────────────────────
class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> with TickerProviderStateMixin {
  final _scaffoldKey = GlobalKey<ScaffoldState>();
  // Services & controllers
  final _apiService = ApiService();
  final _tokenStorage = const TokenStorage();
  final _controller = TextEditingController();
  final _scrollController = ScrollController();
  final _chatFocusNode = FocusNode();
  final _inputAreaKey = GlobalKey();
  final stt.SpeechToText _speechToText = stt.SpeechToText();
  String sessionId = const Uuid().v4();
  bool _authInitialized = false;
  _SidebarPanel _sidebarPanel = _SidebarPanel.sermonLibrary;
  bool _eventsNavPanelOpen = false;
  List<Map<String, dynamic>> _chatHistoryEntries = [];

  // State
  final List<Map<String, dynamic>> _messages = [];
  List<String> _librarySermons = [];
  List<String> _previousSermons = [];
  bool _isLoading = false;
  bool _isFirstMessage = true;
  bool _isButtonTapped = false;
  bool _showBackToBottomButton = false;
  bool _speechAvailable = false;
  bool _isListening = false;
  String _textBeforeSpeech = '';
  /// Full [_buildInputArea] height including bottom inset; grows with multiline input.
  double _inputAreaHeight = _layoutBottomInsetDesktop + _chatInputBarBlockHeight;
  http.Client? _activeClient;

  // Prayer request panel
  bool _prayerPanelExpanded = false;
  bool _prayerSubmitting = false;
  bool _prayerSubmitted = false;
  String? _prayerError;
  bool _submitAnonymously = false;
  final _prayerFormKey = GlobalKey<FormState>();
  final _prayerNameController = TextEditingController();
  final _prayerEmailController = TextEditingController();
  final _prayerPhoneController = TextEditingController();
  final _prayerTextController = TextEditingController();
  bool _prayerPrefilled = false;

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
  
  String _boldBibleReferences(String text) {
  // Matches: BookName Chapter:Verse or Chapter:Verse-Verse
  // Handles multi-word books (e.g., "1 Kings", "Song of Solomon")
  // Handles ranges (e.g., 3:1-14) and optional translation tags (e.g., (NKJV))
final bibleRefRegex = RegExp(
    r'((?:1|2|3)\s)?'                // optional numeric prefix like "1 ", "2 "
    r'[A-Z][a-z]+'                   // book name first word (capitalized)
    r'(?:\s[A-Z][a-z]+)*'            // optional additional capitalized words
    r'\s\d+'                         // chapter number
    r'(?:-\d+)?'                     // optional chapter range (e.g., 2-4)
    r'(?::\d+(?:-(?:\d+:\d+|\d+))?)?' // optional :verse, :verse-endverse, or :verse-chapter:verse
    r'(?:\s\([A-Z]+\))?',            // optional translation (e.g., (NKJV))
    caseSensitive: true,
  );

  return text.replaceAllMapped(bibleRefRegex, (match) {
    final ref = match.group(0)!;
    if (text.substring(
      match.start > 2 ? match.start - 2 : 0,
      match.start
    ).endsWith('**')) return ref;
    return '**$ref**';
  });
}

  // ─── Lifecycle ──────────────────────────────────────────────────────────────
  @override
  void initState() {
    super.initState();
    ChatNavActions.openEvents = _openChurchEvents;
    _scrollController.addListener(() {
      final isFarFromBottom =
          _scrollController.offset < _scrollController.position.maxScrollExtent - 500;
      if (isFarFromBottom != _showBackToBottomButton) {
        setState(() => _showBackToBottomButton = isFarFromBottom);
      }
    });
    WidgetsBinding.instance.addPostFrameCallback((_) => _syncAuthState());
    _initSpeech();
  }

  Future<void> _initSpeech() async {
    final available = await _speechToText.initialize(
      onStatus: (status) {
        if (!mounted) return;
        final listening = status == stt.SpeechToText.listeningStatus;
        if (_isListening != listening) {
          setState(() => _isListening = listening);
        }
      },
      onError: (error) {
        if (!mounted) return;
        setState(() => _isListening = false);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              'Voice input error: ${error.errorMsg}',
              style: GoogleFonts.figtree(),
            ),
            duration: const Duration(seconds: 3),
          ),
        );
      },
    );
    if (!mounted) return;
    setState(() => _speechAvailable = available);
  }

  Future<void> _toggleVoiceInput() async {
    if (_isLoading) return;

    if (_isListening) {
      await _speechToText.stop();
      if (mounted) setState(() => _isListening = false);
      return;
    }

    if (!_speechAvailable) {
      final available = await _speechToText.initialize();
      if (!mounted) return;
      setState(() => _speechAvailable = available);
      if (!available) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              'Voice input is not available in this browser. Try Chrome or Edge.',
              style: GoogleFonts.figtree(),
            ),
            duration: const Duration(seconds: 4),
          ),
        );
        return;
      }
    }

    _textBeforeSpeech = _controller.text.trimRight();
    if (_textBeforeSpeech.isNotEmpty) {
      _textBeforeSpeech = '$_textBeforeSpeech ';
    }

    setState(() => _isListening = true);
    await _speechToText.listen(
      onResult: (result) {
        if (!mounted) return;
        final spoken = result.recognizedWords.trim();
        final next = '$_textBeforeSpeech$spoken';
        _controller.value = TextEditingValue(
          text: next,
          selection: TextSelection.collapsed(offset: next.length),
        );
        setState(() {});
      },
      listenOptions: stt.SpeechListenOptions(
        partialResults: true,
        cancelOnError: true,
        listenMode: stt.ListenMode.dictation,
        // Stop after ~3s of silence (timer resets while speech is detected).
        pauseFor: const Duration(seconds: 3),
      ),
    );
  }

  Future<void> _syncAuthState() async {
    final auth = context.read<AuthController>();
    _apiService.setAccessToken(auth.token);

    if (auth.isAuthenticated && auth.user != null) {
      final savedSession = await _tokenStorage.loadChatSessionId(auth.user!.id);
      final history = await _tokenStorage.loadChatHistory(auth.user!.id);
      if (mounted) {
        setState(() {
          _chatHistoryEntries = history;
          if (savedSession != null) sessionId = savedSession;
        });
        await _restoreMessagesForCurrentSession(auth.user!.id);
      }
    } else if (mounted) {
      setState(() => _chatHistoryEntries = []);
    }

    if (mounted) setState(() => _authInitialized = true);
  }

  Future<void> _restoreMessagesForCurrentSession(String userId) async {
    for (final entry in _chatHistoryEntries) {
      if (entry['sessionId'] == sessionId) {
        final rawMessages = entry['messages'];
        if (rawMessages is! List || rawMessages.isEmpty) return;
        if (!mounted) return;
        setState(() {
          _messages
            ..clear()
            ..addAll(
              rawMessages
                  .whereType<Map>()
                  .map((m) => Map<String, dynamic>.from(m)),
            );
          _librarySermons = List<String>.from(entry['librarySermons'] ?? const []);
          _previousSermons = List<String>.from(entry['previousSermons'] ?? const []);
          _isFirstMessage = _messages.isEmpty;
        });
        return;
      }
    }
  }

  Future<void> _persistSessionId() async {
    final auth = context.read<AuthController>();
    if (!auth.isAuthenticated || auth.user == null) return;
    await _tokenStorage.saveChatSessionId(auth.user!.id, sessionId);
  }

  String _chatHistoryTitle() {
    for (final msg in _messages) {
      if (msg['role'] == 'user') {
        final text = (msg['text'] as String? ?? '').trim();
        if (text.isNotEmpty) {
          return text.length > 48 ? '${text.substring(0, 48)}…' : text;
        }
      }
    }
    return 'New conversation';
  }

  Map<String, dynamic> _currentChatSnapshot() => {
        'sessionId': sessionId,
        'title': _chatHistoryTitle(),
        'updatedAt': DateTime.now().millisecondsSinceEpoch,
        'messages': _messages.map((m) => Map<String, dynamic>.from(m)).toList(),
        'librarySermons': List<String>.from(_librarySermons),
        'previousSermons': List<String>.from(_previousSermons),
      };

  Future<void> _persistChatHistory() async {
    final auth = context.read<AuthController>();
    if (!auth.isAuthenticated || auth.user == null || _messages.isEmpty) return;

    final snapshot = _currentChatSnapshot();
    final sid = sessionId;
    final updated = <Map<String, dynamic>>[
      snapshot,
      ..._chatHistoryEntries.where((e) => e['sessionId'] != sid),
    ]..sort((a, b) => (b['updatedAt'] as int? ?? 0).compareTo(a['updatedAt'] as int? ?? 0));

    const maxEntries = 40;
    final trimmed = updated.take(maxEntries).toList();
    await _tokenStorage.saveChatHistory(auth.user!.id, trimmed);
    if (mounted) setState(() => _chatHistoryEntries = trimmed);
  }

  Future<void> _reloadChatHistory() async {
    final auth = context.read<AuthController>();
    if (!auth.isAuthenticated || auth.user == null) return;
    final history = await _tokenStorage.loadChatHistory(auth.user!.id);
    if (mounted) setState(() => _chatHistoryEntries = history);
  }

  Future<void> _saveChatHistoryEntries(List<Map<String, dynamic>> entries) async {
    final auth = context.read<AuthController>();
    if (!auth.isAuthenticated || auth.user == null) return;
    await _tokenStorage.saveChatHistory(auth.user!.id, entries);
    if (mounted) setState(() => _chatHistoryEntries = entries);
  }

  Future<void> _confirmDeleteChatHistoryEntry(Map<String, dynamic> entry) async {
    final sid = entry['sessionId'] as String?;
    if (sid == null) return;

    final title = (entry['title'] as String? ?? 'this conversation').trim();
    final delete = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Delete chat?', style: GoogleFonts.figtree(fontWeight: FontWeight.bold, color: _navy)),
        content: Text(
          'Remove “${title.length > 60 ? '${title.substring(0, 60)}…' : title}” from your history? This cannot be undone.',
          style: GoogleFonts.figtree(color: Colors.black87),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            style: FilledButton.styleFrom(backgroundColor: _pink),
            child: Text('Delete', style: GoogleFonts.figtree(fontWeight: FontWeight.bold)),
          ),
        ],
      ),
    );
    if (delete != true || !mounted) return;

    final updated = _chatHistoryEntries.where((e) => e['sessionId'] != sid).toList();
    await _saveChatHistoryEntries(updated);

    if (sid == sessionId && mounted) {
      setState(() {
        sessionId = const Uuid().v4();
        _messages.clear();
        _librarySermons.clear();
        _previousSermons.clear();
        _isFirstMessage = true;
        _showBackToBottomButton = false;
      });
      await _persistSessionId();
    }

    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Chat deleted'), duration: Duration(seconds: 2)),
      );
    }
  }

  @override
  void dispose() {
    if (ChatNavActions.openEvents == _openChurchEvents) {
      ChatNavActions.openEvents = null;
    }
    if (_speechToText.isListening) {
      _speechToText.stop();
    }
    _pulseController.dispose();
    _scrollController.dispose();
    _controller.dispose();
    _chatFocusNode.dispose();
    _prayerNameController.dispose();
    _prayerEmailController.dispose();
    _prayerPhoneController.dispose();
    _prayerTextController.dispose();
    super.dispose();
  }

  void _prefillPrayerFormFromAuth() {
    if (_prayerPrefilled) return;
    final auth = context.read<AuthController>();
    if (!auth.isAuthenticated || auth.user == null) return;
    _prayerNameController.text = auth.user!.name;
    _prayerEmailController.text = auth.user!.email;
    _prayerPrefilled = true;
  }

  void _togglePrayerPanel({bool? expanded}) {
    setState(() {
      _prayerPanelExpanded = expanded ?? !_prayerPanelExpanded;
      if (_prayerPanelExpanded) {
        _prayerSubmitted = false;
        _prayerError = null;
        _prefillPrayerFormFromAuth();
      }
    });
  }

  Future<void> _submitPrayerRequest() async {
    if (_prayerSubmitting) return;
    if (!_prayerFormKey.currentState!.validate()) return;

    setState(() {
      _prayerSubmitting = true;
      _prayerError = null;
    });

    try {
      await _apiService.submitPrayerRequest(
        prayerText: _prayerTextController.text.trim(),
        name: _submitAnonymously ? null : _prayerNameController.text.trim(),
        email: _submitAnonymously ? null : _prayerEmailController.text.trim(),
        phone: _prayerPhoneController.text.trim().isEmpty ? null : _prayerPhoneController.text.trim(),
        isAnonymous: _submitAnonymously,
      );
      if (!mounted) return;
      setState(() {
        _prayerSubmitting = false;
        _prayerSubmitted = true;
        _prayerTextController.clear();
        _prayerPhoneController.clear();
        if (!_submitAnonymously) {
          _prayerNameController.clear();
          _prayerEmailController.clear();
          _prayerPrefilled = false;
        }
      });
      Future.delayed(const Duration(seconds: 2), () {
        if (!mounted || !_prayerSubmitted) return;
        setState(() {
          _prayerPanelExpanded = false;
          _prayerSubmitted = false;
          _submitAnonymously = false;
        });
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _prayerSubmitting = false;
        _prayerError = 'Could not submit your prayer request. Please try again.';
      });
    }
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
  var stem = sermonName.trim();
  final lower = stem.toLowerCase();
  for (final ext in const ['.pdf', '.md', '.docx']) {
    if (lower.endsWith(ext)) {
      stem = stem.substring(0, stem.length - ext.length).trim();
      break;
    }
  }
  if (stem.isEmpty) return;

  // Same-origin PDF route: uploaded file when present, else rebuilt from Qdrant notes.
  final Uri fileUri = Uri(
    scheme: Uri.base.scheme.isEmpty ? 'https' : Uri.base.scheme,
    host: Uri.base.host,
    port: Uri.base.hasPort ? Uri.base.port : null,
    pathSegments: <String>['sermons', '$stem.pdf'],
  );

  try {
    final launched = await launchUrl(
      fileUri,
      mode: LaunchMode.externalApplication,
      webOnlyWindowName: '_blank',
    );
    if (!launched && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Could not open sermon PDF for "$stem".')),
      );
    }
  } catch (e, st) {
    debugPrint('Error opening sermon link: $e\n$st');
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Could not open sermon PDF for "$stem".')),
      );
    }
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
  Future<void> _clearChat() async {
    await _persistChatHistory();
    if (!mounted) return;
    setState(() {
      sessionId = const Uuid().v4();
      _messages.clear();
      _librarySermons.clear();
      _previousSermons.clear();
      _isFirstMessage = true;
      _showBackToBottomButton = false;
    });
    _persistSessionId();
  }

  Future<void> _openLogin() async {
    final signedIn = await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
    );
    if (signedIn == true && mounted) {
      await _syncAuthState();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Signed in as ${context.read<AuthController>().user?.name ?? 'user'}')),
        );
      }
    }
  }

  void _openPrayerInbox() {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => PrayerInboxScreen(apiService: _apiService),
      ),
    );
  }

  void _openSubscriptions() {
    if (_scaffoldKey.currentState?.isDrawerOpen ?? false) {
      Navigator.of(context).pop();
    }
    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => const SubscriptionsScreen()),
    );
  }

  void _openMedia() {
    // TODO: gate on Premium subscription.
    if (_scaffoldKey.currentState?.isDrawerOpen ?? false) {
      Navigator.of(context).pop();
    }
    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => const MediaLibraryScreen()),
    );
  }

  void _openChurchEvents() {
    if (_scaffoldKey.currentState?.isDrawerOpen ?? false) {
      Navigator.of(context).pop();
    }
    setState(() => _eventsNavPanelOpen = true);
  }

  void _closeChurchEventsPanel() {
    setState(() => _eventsNavPanelOpen = false);
  }

  void _focusChatNav() {
    setState(() => _eventsNavPanelOpen = false);
  }

  Widget _buildEventsNavPanel(AuthController auth) {
    return ChurchEventsNavOverlay(
      apiService: _apiService,
      isStaff: auth.isAuthenticated && (auth.user?.isStaff ?? false),
      onClose: _closeChurchEventsPanel,
      panelKey: ValueKey('events-nav-${auth.user?.id ?? 'guest'}-${auth.user?.isStaff ?? false}'),
    );
  }

  void _showLoginRequiredForChatHistory() {
    showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Login required', style: GoogleFonts.figtree(fontWeight: FontWeight.bold, color: _navy)),
        content: Text(
          'Login required to access chat history.',
          style: GoogleFonts.figtree(color: Colors.black87),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(), child: const Text('OK')),
          FilledButton(
            onPressed: () {
              Navigator.of(ctx).pop();
              _openLogin();
            },
            style: FilledButton.styleFrom(backgroundColor: _navy),
            child: Text('Log in', style: GoogleFonts.figtree(fontWeight: FontWeight.bold)),
          ),
        ],
      ),
    );
  }

  void _selectSidebarPanel(_SidebarPanel panel) {
    if (panel == _SidebarPanel.previousChats) {
      final auth = context.read<AuthController>();
      if (!auth.isAuthenticated) {
        _showLoginRequiredForChatHistory();
        return;
      }
      _reloadChatHistory();
    }
    setState(() => _sidebarPanel = panel);
  }

  void _loadChatFromHistory(Map<String, dynamic> entry) {
    setState(() {
      sessionId = entry['sessionId'] as String? ?? sessionId;
      _messages
        ..clear()
        ..addAll(
          (entry['messages'] as List<dynamic>? ?? const [])
              .whereType<Map>()
              .map((m) => Map<String, dynamic>.from(m)),
        );
      _librarySermons = List<String>.from(entry['librarySermons'] ?? const []);
      _previousSermons = List<String>.from(entry['previousSermons'] ?? const []);
      _isFirstMessage = _messages.isEmpty;
      _showBackToBottomButton = false;
    });
    _persistSessionId();
    WidgetsBinding.instance.addPostFrameCallback((_) => _scrollToBottom());
  }

  void _showProfileSheet() {
    final auth = context.read<AuthController>();
    final user = auth.user;
    if (user == null) return;

    showModalBottomSheet<void>(
      context: context,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
      ),
      builder: (ctx) => Padding(
        padding: const EdgeInsets.fromLTRB(24, 24, 24, 32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Your account', style: GoogleFonts.figtree(fontSize: 20, fontWeight: FontWeight.bold, color: _navy)),
            const SizedBox(height: 20),
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: CircleAvatar(
                backgroundColor: _gold.withOpacity(0.2),
                child: Text(
                  user.name.isNotEmpty ? user.name[0].toUpperCase() : '?',
                  style: GoogleFonts.figtree(fontWeight: FontWeight.bold, color: _navy),
                ),
              ),
              title: Text(user.name, style: GoogleFonts.figtree(fontWeight: FontWeight.w600)),
              subtitle: Text(user.email, style: GoogleFonts.figtree(color: Colors.black54)),
            ),
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: () {
                  Navigator.of(ctx).pop();
                  _openSubscriptions();
                },
                icon: const Icon(Icons.workspace_premium_outlined, color: _navy),
                label: Text('View plans', style: GoogleFonts.figtree(color: _navy, fontWeight: FontWeight.bold)),
                style: OutlinedButton.styleFrom(
                  side: const BorderSide(color: _gold, width: 1.5),
                  padding: const EdgeInsets.symmetric(vertical: 14),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                ),
              ),
            ),
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: () {
                  Navigator.of(ctx).pop();
                  _openMedia();
                },
                icon: const Icon(Icons.video_library_outlined, color: _navy),
                label: Text('Media library', style: GoogleFonts.figtree(color: _navy, fontWeight: FontWeight.bold)),
                style: OutlinedButton.styleFrom(
                  side: const BorderSide(color: _navy, width: 1.5),
                  padding: const EdgeInsets.symmetric(vertical: 14),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                ),
              ),
            ),
            const SizedBox(height: 12),
            if (user.isStaff) ...[
              SizedBox(
                width: double.infinity,
                child: FilledButton.icon(
                  onPressed: () {
                    Navigator.of(ctx).pop();
                    _openPrayerInbox();
                  },
                  icon: const Icon(Icons.volunteer_activism_outlined),
                  label: Text('Prayer inbox', style: GoogleFonts.figtree(fontWeight: FontWeight.bold)),
                  style: FilledButton.styleFrom(
                    backgroundColor: _navy,
                    padding: const EdgeInsets.symmetric(vertical: 14),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                  ),
                ),
              ),
              const SizedBox(height: 12),
            ],
            if (kUseMockAuth)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Text(
                  'Demo mode: auth is mocked until Django endpoints are ready.',
                  style: GoogleFonts.figtree(fontSize: 12, color: Colors.black45),
                ),
              ),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: () async {
                  Navigator.of(ctx).pop();
                  await auth.logout();
                  _apiService.setAccessToken(null);
                  if (mounted) {
                    setState(() {
                      sessionId = const Uuid().v4();
                      _chatHistoryEntries = [];
                      _sidebarPanel = _SidebarPanel.sermonLibrary;
                    });
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('Signed out')),
                    );
                  }
                },
                icon: const Icon(Icons.logout, color: _pink),
                label: Text('Sign out', style: GoogleFonts.figtree(color: _pink, fontWeight: FontWeight.bold)),
                style: OutlinedButton.styleFrom(
                  side: const BorderSide(color: _pink),
                  padding: const EdgeInsets.symmetric(vertical: 14),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

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

  if (_isListening || _speechToText.isListening) {
    await _speechToText.stop();
    if (mounted) setState(() => _isListening = false);
  }

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
    await _persistSessionId();

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
         "text": _boldBibleReferences(data['answer'] as String),
         "sources": List<String>.from(data['sources'] ?? []),
    });
      
      // 3. Only update the library if the response actually used sermon sources
      final newSources = _parseSources(data['sources']);
      if (newSources.isNotEmpty) {
        _librarySermons = newSources;
        // 4. Clean up: If a sermon is in 'Current', remove it from 'Previous'
        _previousSermons.removeWhere((s) => _librarySermons.contains(s));
      }
    });
    _scrollToBottom();
    await _persistChatHistory();
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
  void _measureInputAreaHeight() {
    final context = _inputAreaKey.currentContext;
    if (context == null) return;
    final height = context.size?.height;
    if (height == null) return;
    if ((height - _inputAreaHeight).abs() < 0.5) return;
    if (!mounted) return;
    setState(() => _inputAreaHeight = height);
  }

  void _scheduleInputAreaMeasure() {
    WidgetsBinding.instance.addPostFrameCallback((_) => _measureInputAreaHeight());
  }

  double _prayerFabBottom(double screenWidth, bool isMobile, double viewInsetBottom) {
    final layoutBottomInset = isMobile ? _layoutBottomInsetMobile : _layoutBottomInsetDesktop;
    const gap = 8.0;
    if (screenWidth < _prayerFabClearanceBelowWide) {
      // Measured height already includes the bottom layout inset.
      return _inputAreaHeight + gap + viewInsetBottom;
    }
    // Wide screens sit in the corner by default; lift by any multiline growth.
    final singleLineHeight = layoutBottomInset + _chatInputBarBlockHeight;
    final growth = (_inputAreaHeight - singleLineHeight).clamp(0.0, double.infinity);
    return layoutBottomInset + growth + gap + viewInsetBottom;
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthController>();
    if (!_authInitialized && auth.isAuthenticated) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _syncAuthState());
    }
    _apiService.setAccessToken(auth.token);

    final screenWidth = MediaQuery.of(context).size.width;
    final isMobileOrTablet = screenWidth < 1024;
    final isMobile = screenWidth < 600;
    final viewInsetBottom = MediaQuery.of(context).viewInsets.bottom;
    final prayerFabBottom = _prayerFabBottom(screenWidth, isMobile, viewInsetBottom);
    final prayerFabRight = isMobile ? 10.0 : 20.0;
    _scheduleInputAreaMeasure();

    return Scaffold(
      key: _scaffoldKey,
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
          if (auth.isAuthenticated && auth.user!.isStaff)
            Padding(
              padding: EdgeInsets.only(top: isMobile ? 20 : 45, right: 4),
              child: IconButton(
                tooltip: 'Prayer inbox',
                onPressed: _openPrayerInbox,
                icon: const Icon(Icons.volunteer_activism_outlined, color: _navy),
              ),
            ),
          if (auth.isAuthenticated)
            Padding(
              padding: EdgeInsets.only(top: isMobile ? 20 : 45, right: isMobile ? 8 : 24),
              child: ActionChip(
                avatar: CircleAvatar(
                  backgroundColor: _gold.withOpacity(0.25),
                  child: Text(
                    auth.user!.name.isNotEmpty ? auth.user!.name[0].toUpperCase() : '?',
                    style: GoogleFonts.figtree(fontSize: 12, fontWeight: FontWeight.bold, color: _navy),
                  ),
                ),
                label: Text(
                  auth.user!.name.split(' ').first,
                  style: GoogleFonts.figtree(fontWeight: FontWeight.w600, color: _navy),
                ),
                onPressed: _showProfileSheet,
              ),
            ),
          if (!isMobile)
            Padding(
              padding: const EdgeInsets.only(top: 45.0),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  _buildNavButton("Home", () => _launchUrl("https://thenordins.org/")),
                  _buildNavButton("Store", () => _launchUrl("https://thenordins.org/store")),
                  _buildNavButton("Events", _openChurchEvents),
                  NordinsAiNavMenu(
                    onAiHome: _focusChatNav,
                    onMedia: _openMedia,
                    onSubscribe: _openSubscriptions,
                  ),
                  const SizedBox(width: 40),
                ],
              ),
            ),
        ],
      ),
      body: Stack(
        children: [
          Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Expanded(
                child: Row(
                  children: [
                    if (!isMobileOrTablet) _buildSidebar(isMobile: false),
                    Expanded(child: _buildChatInterface(isMobile)),
                  ],
                ),
              ),
            ],
          ),
          if (_eventsNavPanelOpen)
            Positioned(
              top: 0,
              right: 0,
              child: NotificationListener<ScrollNotification>(
                onNotification: (_) => true,
                child: NotificationListener<OverscrollIndicatorNotification>(
                  onNotification: (notification) {
                    notification.disallowIndicator();
                    return true;
                  },
                  child: _buildEventsNavPanel(auth),
                ),
              ),
            ),
          if (_prayerPanelExpanded)
            Positioned.fill(
              child: GestureDetector(
                onTap: () => _togglePrayerPanel(expanded: false),
                child: Container(color: Colors.black12),
              ),
            ),
          AnimatedPositioned(
            duration: const Duration(milliseconds: 180),
            curve: Curves.easeOutCubic,
            bottom: prayerFabBottom,
            right: prayerFabRight,
            child: _buildPrayerRequestPanel(
              isCompactViewport: isMobileOrTablet,
              iconOnlyCollapsed: isMobile,
            ),
          ),
        ],
      ),
    );
  }

  // ─── Sidebar ─────────────────────────────────────────────────────────────────
  Widget _buildSidebarTabSwitcher() {
    Widget tab(String label, _SidebarPanel panel, IconData icon) {
      final selected = _sidebarPanel == panel;
      return Expanded(
        child: Material(
          color: Colors.transparent,
          child: InkWell(
            onTap: () => _selectSidebarPanel(panel),
            borderRadius: BorderRadius.circular(12),
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 8),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(12),
                color: selected ? Colors.white.withValues(alpha: 0.14) : Colors.transparent,
                border: Border.all(
                  color: selected ? _gold : Colors.white24,
                  width: selected ? 1.5 : 1,
                ),
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(icon, color: selected ? _gold : Colors.white70, size: 18),
                  const SizedBox(height: 4),
                  Text(
                    label,
                    textAlign: TextAlign.center,
                    style: GoogleFonts.figtree(
                      color: selected ? Colors.white : Colors.white70,
                      fontSize: 11,
                      fontWeight: selected ? FontWeight.bold : FontWeight.w600,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
    }

    return Row(
      children: [
        tab('Sermons', _SidebarPanel.sermonLibrary, Icons.menu_book_outlined),
        const SizedBox(width: 8),
        tab('Chats', _SidebarPanel.previousChats, Icons.history),
      ],
    );
  }

  Widget _buildPreviousChatsPanel(AuthController auth) {
    if (!auth.isAuthenticated) {
      return Text(
        'Sign in to view and reopen your past conversations.',
        style: GoogleFonts.figtree(color: Colors.white70, fontSize: 14),
      );
    }

    if (_chatHistoryEntries.isEmpty) {
      return Text(
        'Your saved chats will appear here. Start a conversation while signed in.',
        style: GoogleFonts.figtree(color: Colors.white70, fontSize: 14),
      );
    }

    return ListView(
      physics: _eventsNavPanelOpen
          ? const NeverScrollableScrollPhysics()
          : const ClampingScrollPhysics(),
      children: _chatHistoryEntries.map(_buildChatHistoryLink).toList(),
    );
  }

  Widget _buildChatHistoryLink(Map<String, dynamic> entry) {
    final title = (entry['title'] as String? ?? 'Conversation').trim();
    final updatedAt = entry['updatedAt'] as int?;
    final isActive = entry['sessionId'] == sessionId;
    String subtitle = '';
    if (updatedAt != null) {
      final dt = DateTime.fromMillisecondsSinceEpoch(updatedAt);
      subtitle =
          '${dt.month}/${dt.day}/${dt.year} · ${dt.hour == 0 ? 12 : (dt.hour > 12 ? dt.hour - 12 : dt.hour)}:${dt.minute.toString().padLeft(2, '0')} ${dt.hour >= 12 ? 'PM' : 'AM'}';
    }

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
            color: isActive
                ? Colors.white.withValues(alpha: 0.12)
                : (isHovered ? Colors.white.withValues(alpha: 0.07) : Colors.transparent),
            border: isActive ? Border.all(color: _gold.withValues(alpha: 0.6)) : null,
            boxShadow: isHovered
                ? [
                    BoxShadow(
                      color: Colors.black.withValues(alpha: 0.2),
                      blurRadius: 15,
                      offset: const Offset(0, 6),
                      spreadRadius: -4,
                    )
                  ]
                : [],
          ),
          child: InkWell(
            borderRadius: BorderRadius.circular(20),
            onTap: () => _loadChatFromHistory(entry),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 8.0, horizontal: 12.0),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(
                    isActive ? Icons.chat_bubble : Icons.chat_bubble_outline,
                    color: _gold,
                    size: 18,
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Padding(
                      padding: const EdgeInsets.only(top: 2),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            title,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: GoogleFonts.figtree(
                              color: Colors.white,
                              fontSize: 14,
                              fontWeight: isActive ? FontWeight.w600 : FontWeight.w400,
                            ),
                          ),
                          if (subtitle.isNotEmpty) ...[
                            const SizedBox(height: 4),
                            Text(
                              subtitle,
                              style: GoogleFonts.figtree(color: Colors.white54, fontSize: 11),
                            ),
                          ],
                        ],
                      ),
                    ),
                  ),
                  IconButton(
                    onPressed: () => _confirmDeleteChatHistoryEntry(entry),
                    icon: const Icon(Icons.delete_outline, size: 18),
                    color: Colors.white54,
                    visualDensity: VisualDensity.compact,
                    padding: EdgeInsets.zero,
                    constraints: const BoxConstraints(minWidth: 32, minHeight: 32),
                    tooltip: 'Delete chat',
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildSidebar({required bool isMobile}) {
    final auth = context.watch<AuthController>();

    return Container(
      width: isMobile ? double.infinity : 320,
      margin: isMobile ? EdgeInsets.zero : const EdgeInsets.only(left: 20, bottom: _layoutBottomInsetDesktop, top: 20),
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
              Wrap(spacing: 4, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
                _buildNavButton("Home", () => _launchUrl("https://thenordins.org/"), textColor: Colors.white),
                _buildNavButton("Store", () => _launchUrl("https://thenordins.org/store"), textColor: Colors.white),
                _buildNavButton("Events", _openChurchEvents, textColor: Colors.white),
                NordinsAiNavMenu(
                  onAiHome: () {
                    if (_scaffoldKey.currentState?.isDrawerOpen ?? false) {
                      Navigator.of(context).pop();
                    }
                    _focusChatNav();
                  },
                  onMedia: _openMedia,
                  onSubscribe: _openSubscriptions,
                  textColor: Colors.white,
                ),
              ]),
              const SizedBox(height: 16),
              Container(height: 1, color: Colors.white24),
              const SizedBox(height: 20),
            ],
            _buildSidebarTabSwitcher(),
            const SizedBox(height: 20),
            if (_sidebarPanel == _SidebarPanel.sermonLibrary) ...[
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
                        physics: _eventsNavPanelOpen
                            ? const NeverScrollableScrollPhysics()
                            : const ClampingScrollPhysics(),
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
            ] else ...[
              Text("Previous Chats",
                  style: GoogleFonts.figtree(color: Colors.white, fontSize: 20, fontWeight: FontWeight.bold)),
              const SizedBox(height: 8),
              Container(height: 2, width: 40, color: _gold),
              const SizedBox(height: 20),
              Expanded(child: _buildPreviousChatsPanel(auth)),
            ],
            const SizedBox(height: 20),
            _buildAuthFooter(auth),
            const SizedBox(height: 12),
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

  Widget _buildPrayerRequestPanel({
    required bool isCompactViewport,
    required bool iconOnlyCollapsed,
  }) {
    final maxHeight = MediaQuery.of(context).size.height * 0.65;
    final panelWidth =
        isCompactViewport ? MediaQuery.of(context).size.width - 32 : 420.0;

    if (!_prayerPanelExpanded) {
      final fab = Material(
        elevation: 4,
        borderRadius: BorderRadius.circular(28),
        child: InkWell(
          onTap: () => _togglePrayerPanel(expanded: true),
          borderRadius: BorderRadius.circular(28),
          child: Container(
            padding: iconOnlyCollapsed
                ? const EdgeInsets.all(14)
                : const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(28),
              gradient: const LinearGradient(colors: [_pink, _navy]),
            ),
            child: iconOnlyCollapsed
                ? const Icon(Icons.volunteer_activism, color: _gold, size: 24)
                : Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.volunteer_activism, color: _gold, size: 22),
                      const SizedBox(width: 8),
                      Text(
                        'Prayer Request Form',
                        style: GoogleFonts.figtree(
                          color: Colors.white,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ],
                  ),
          ),
        ),
      );
      return iconOnlyCollapsed
          ? Tooltip(message: 'Prayer Request Form', child: fab)
          : fab;
    }

    return Material(
      elevation: 12,
      borderRadius: BorderRadius.circular(20),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 250),
        curve: Curves.easeOutCubic,
        width: panelWidth,
        constraints: BoxConstraints(maxHeight: maxHeight),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: _gold, width: 1.5),
          boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.12), blurRadius: 24, offset: const Offset(0, 8))],
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
              decoration: const BoxDecoration(
                borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
                gradient: LinearGradient(colors: [_pink, _navy]),
              ),
              child: Row(
                children: [
                  const Icon(Icons.volunteer_activism, color: _gold, size: 22),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      'Prayer Request',
                      style: GoogleFonts.figtree(color: Colors.white, fontSize: 18, fontWeight: FontWeight.bold),
                    ),
                  ),
                  IconButton(
                    onPressed: () => _togglePrayerPanel(expanded: false),
                    icon: const Icon(Icons.close, color: Colors.white70, size: 22),
                    padding: EdgeInsets.zero,
                    constraints: const BoxConstraints(minWidth: 32, minHeight: 32),
                  ),
                ],
              ),
            ),
            Flexible(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(20),
                child: _prayerSubmitted
                    ? Column(
                        children: [
                          const Icon(Icons.check_circle_outline, color: Colors.green, size: 48),
                          const SizedBox(height: 12),
                          Text(
                            'Your prayer request has been received.',
                            textAlign: TextAlign.center,
                            style: GoogleFonts.figtree(fontSize: 16, fontWeight: FontWeight.w600, color: _navy),
                          ),
                          const SizedBox(height: 8),
                          Text(
                            'Our prayer team will be lifting you up.',
                            textAlign: TextAlign.center,
                            style: GoogleFonts.figtree(fontSize: 14, color: Colors.black54),
                          ),
                        ],
                      )
                    : Form(
                        key: _prayerFormKey,
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            Text(
                              'Share your prayer need with us.',
                              style: GoogleFonts.figtree(fontSize: 14, color: Colors.black54),
                            ),
                            const SizedBox(height: 16),
                            if (_prayerError != null) ...[
                              Container(
                                padding: const EdgeInsets.all(10),
                                decoration: BoxDecoration(
                                  color: Colors.red.shade50,
                                  borderRadius: BorderRadius.circular(10),
                                  border: Border.all(color: Colors.red.shade200),
                                ),
                                child: Text(_prayerError!, style: GoogleFonts.figtree(color: Colors.red.shade800, fontSize: 13)),
                              ),
                              const SizedBox(height: 12),
                            ],
                            CheckboxListTile(
                              value: _submitAnonymously,
                              onChanged: _prayerSubmitting
                                  ? null
                                  : (v) => setState(() => _submitAnonymously = v ?? false),
                              contentPadding: EdgeInsets.zero,
                              controlAffinity: ListTileControlAffinity.leading,
                              title: Text('Submit anonymously', style: GoogleFonts.figtree(fontSize: 14, color: _navy)),
                              activeColor: _navy,
                            ),
                            if (!_submitAnonymously) ...[
                              TextFormField(
                                controller: _prayerNameController,
                                decoration: _authInputDecoration('Name'),
                                validator: (v) {
                                  if (_submitAnonymously) return null;
                                  if (v == null || v.trim().isEmpty) return 'Enter your name';
                                  return null;
                                },
                              ),
                              const SizedBox(height: 12),
                              TextFormField(
                                controller: _prayerEmailController,
                                keyboardType: TextInputType.emailAddress,
                                decoration: _authInputDecoration('Email'),
                                validator: (v) {
                                  if (_submitAnonymously) return null;
                                  if (v == null || v.trim().isEmpty) return 'Enter your email';
                                  if (!v.contains('@')) return 'Enter a valid email';
                                  return null;
                                },
                              ),
                              const SizedBox(height: 12),
                            ],
                            TextFormField(
                              controller: _prayerPhoneController,
                              keyboardType: TextInputType.phone,
                              decoration: _authInputDecoration('Phone (optional)'),
                            ),
                            const SizedBox(height: 12),
                            TextFormField(
                              controller: _prayerTextController,
                              minLines: 4,
                              maxLines: 6,
                              decoration: _authInputDecoration('Your prayer request'),
                              validator: (v) {
                                if (v == null || v.trim().length < 10) {
                                  return 'Please share at least a few words (10+ characters)';
                                }
                                return null;
                              },
                            ),
                            const SizedBox(height: 16),
                            FilledButton(
                              onPressed: _prayerSubmitting ? null : _submitPrayerRequest,
                              style: FilledButton.styleFrom(
                                backgroundColor: _navy,
                                foregroundColor: Colors.white,
                                padding: const EdgeInsets.symmetric(vertical: 14),
                                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                              ),
                              child: _prayerSubmitting
                                  ? const SizedBox(
                                      height: 20,
                                      width: 20,
                                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                                    )
                                  : Text('Submit Prayer Request', style: GoogleFonts.figtree(fontWeight: FontWeight.bold)),
                            ),
                          ],
                        ),
                      ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildAuthFooter(AuthController auth) {
    if (auth.isAuthenticated && auth.user != null) {
      final user = auth.user!;
      return InkWell(
        onTap: _showProfileSheet,
        borderRadius: BorderRadius.circular(16),
        child: Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: Colors.white.withOpacity(0.08),
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: Colors.white24),
          ),
          child: Row(
            children: [
              CircleAvatar(
                radius: 18,
                backgroundColor: _gold.withOpacity(0.25),
                backgroundImage: user.avatarUrl != null ? NetworkImage(user.avatarUrl!) : null,
                child: user.avatarUrl == null
                    ? Text(
                        user.name.isNotEmpty ? user.name[0].toUpperCase() : '?',
                        style: GoogleFonts.figtree(fontWeight: FontWeight.bold, color: Colors.white),
                      )
                    : null,
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(user.name,
                        style: GoogleFonts.figtree(color: Colors.white, fontWeight: FontWeight.w600, fontSize: 14)),
                    Text(user.email,
                        style: GoogleFonts.figtree(color: Colors.white70, fontSize: 12),
                        overflow: TextOverflow.ellipsis),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right, color: Colors.white54, size: 20),
            ],
          ),
        ),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          'Sign in to save chat history across devices.',
          textAlign: TextAlign.center,
          style: GoogleFonts.figtree(color: Colors.white70, fontSize: 12),
        ),
        const SizedBox(height: 10),
        FilledButton(
          onPressed: _openLogin,
          style: FilledButton.styleFrom(
            backgroundColor: _gold,
            foregroundColor: _navy,
            padding: const EdgeInsets.symmetric(vertical: 14),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          ),
          child: Text('Sign in', style: GoogleFonts.figtree(fontWeight: FontWeight.bold)),
        ),
      ],
    );
  }

  // ─── Chat Interface ───────────────────────────────────────────────────────────
  Widget _buildChatInterface(bool isMobile) {
    final mq = MediaQuery.of(context);
    final screenWidth = mq.size.width;
    final narrowViewport = screenWidth < _prayerFabClearanceBelowWide;

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
                    child: Stack(
                      children: [
                        ListView.builder(
                          controller: _scrollController,
                          physics: const AlwaysScrollableScrollPhysics(),
                          padding: EdgeInsets.symmetric(horizontal: isMobile ? 15 : 20, vertical: 20),
                          itemCount: _messages.length,
                          itemBuilder: (context, index) {
                            final msg = _messages[index];
                            return _buildChatBubble(msg, msg["role"] == "user", isMobile, index);
                          },
                        ),
                        if (_showBackToBottomButton && !_isLoading)
                          Positioned(
                            left: narrowViewport ? (isMobile ? 8 : 12) : null,
                            right: narrowViewport ? null : (isMobile ? 8 : 12),
                            bottom: 12,
                            child: AnimatedSwitcher(
                              duration: const Duration(milliseconds: 200),
                              child: TextButton.icon(
                                key: const ValueKey('scrollBtn'),
                                onPressed: _scrollToBottom,
                                icon: const Icon(Icons.arrow_downward, size: 16),
                                label: Text(
                                  'Back to bottom',
                                  style: GoogleFonts.figtree(fontWeight: FontWeight.w600),
                                ),
                                style: TextButton.styleFrom(
                                  foregroundColor: _navy,
                                  backgroundColor: Colors.white.withValues(alpha: 0.92),
                                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                                  shape: RoundedRectangleBorder(
                                    borderRadius: BorderRadius.circular(20),
                                    side: BorderSide(color: _gold.withValues(alpha: 0.55)),
                                  ),
                                ),
                              ),
                            ),
                          ),
                      ],
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
                            "This tool is trained on Pastor Don's sermon notes and resources. The AI may occasionally produce inaccurate information. Please verify insights with your Bible.",
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
      key: _inputAreaKey,
      padding: EdgeInsets.only(
        bottom: isMobile ? _layoutBottomInsetMobile : _layoutBottomInsetDesktop,
        left: isMobile ? 10 : 20,
        right: isMobile ? 10 : 20,
        top: 10,
      ),
      child: Center(
        child: Container(
          constraints: const BoxConstraints(maxWidth: 1100),
          decoration: BoxDecoration(
            color: _surface,
            borderRadius: BorderRadius.circular(24),
            border: Border.all(
              color: _isListening ? _gold : Colors.grey.shade300,
              width: _isListening ? 1.5 : 1,
            ),
          ),
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Expanded(
                child: TextField(
                  controller: _controller,
                  focusNode: _chatFocusNode,
                  onChanged: (_) {
                    setState(() {});
                    _scheduleInputAreaMeasure();
                  },
                  minLines: 1,
                  maxLines: 5,
                  textInputAction: TextInputAction.send,
                  onSubmitted: (_) {
                    if (_isListening) {
                      _speechToText.stop();
                    }
                    if (_controller.text.trim().isEmpty) {
                      _chatFocusNode.requestFocus();
                    } else if (!_isLoading) {
                      _sendMessage();
                    }
                  },
                  decoration: InputDecoration(
                    hintText: _isListening ? 'Listening… speak your question' : 'How can I help you?',
                    border: InputBorder.none,
                    contentPadding: const EdgeInsets.only(left: 16, right: 8, top: 14, bottom: 14),
                  ),
                ),
              ),
              Padding(
                padding: const EdgeInsets.only(bottom: 6.0, right: 2.0),
                child: MouseRegion(
                  cursor: SystemMouseCursors.click,
                  child: Tooltip(
                    message: _isListening ? 'Stop voice input' : 'Ask with voice',
                    child: GestureDetector(
                      onTap: _toggleVoiceInput,
                      child: AnimatedBuilder(
                        animation: _pulseController,
                        builder: (context, child) {
                          final scale = _isListening ? (0.92 + (_wobbleAnimation.value - 0.7) * 0.2) : 1.0;
                          return Transform.scale(scale: scale, child: child);
                        },
                        child: Container(
                          width: 40,
                          height: 40,
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            color: _isListening ? _pink : Colors.white,
                            border: Border.all(
                              color: _isListening ? _pink : _navy.withValues(alpha: 0.35),
                              width: 1.5,
                            ),
                          ),
                          child: Icon(
                            _isListening ? Icons.mic : Icons.mic_none,
                            color: _isListening ? Colors.white : _navy,
                            size: 22,
                          ),
                        ),
                      ),
                    ),
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