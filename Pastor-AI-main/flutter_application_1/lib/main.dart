import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:uuid/uuid.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:flutter/services.dart';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

// ─── Constants ───────────────────────────────────────────────────────────────
const _navy = Color(0xFF1B264F);
const _gold = Color(0xFFD4AF37);
const _pink = Color(0xFFa1375a);
const _surface = Color(0xFFF4F4F9);

// ─── Token Storage ───────────────────────────────────────────────────────────
class TokenStorage {
  static const _tokenKey = 'auth_token';
  static const _userKey = 'auth_user';
  static const _sessionPrefix = 'chat_session_';

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
}

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
    } catch (_) {
      error = 'Something went wrong. Please try again.';
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

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
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
                  OutlinedButton.icon(
                    onPressed: auth.isLoading ? null : _googleSignIn,
                    icon: const Icon(Icons.g_mobiledata, size: 28, color: _navy),
                    label: Text('Sign in with Google', style: GoogleFonts.figtree(fontWeight: FontWeight.w600, color: _navy)),
                    style: OutlinedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 14),
                      side: const BorderSide(color: _navy),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    ),
                  ),
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

  @override
  void dispose() {
    _nameController.dispose();
    _emailController.dispose();
    _passwordController.dispose();
    _confirmController.dispose();
    super.dispose();
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
                  OutlinedButton.icon(
                    onPressed: auth.isLoading ? null : _googleSignIn,
                    icon: const Icon(Icons.g_mobiledata, size: 28, color: _navy),
                    label: Text('Sign up with Google', style: GoogleFonts.figtree(fontWeight: FontWeight.w600, color: _navy)),
                    style: OutlinedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 14),
                      side: const BorderSide(color: _navy),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    ),
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
  // Services & controllers
  final _apiService = ApiService();
  final _tokenStorage = const TokenStorage();
  final _controller = TextEditingController();
  final _scrollController = ScrollController();
  final _chatFocusNode = FocusNode();
  String sessionId = const Uuid().v4();
  bool _authInitialized = false;

  // State
  final List<Map<String, dynamic>> _messages = [];
  List<String> _librarySermons = [];
  List<String> _previousSermons = [];
  bool _isLoading = false;
  bool _isFirstMessage = true;
  bool _isButtonTapped = false;
  bool _showBackToBottomButton = false;
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
    _scrollController.addListener(() {
      final isFarFromBottom =
          _scrollController.offset < _scrollController.position.maxScrollExtent - 500;
      if (isFarFromBottom != _showBackToBottomButton) {
        setState(() => _showBackToBottomButton = isFarFromBottom);
      }
    });
    WidgetsBinding.instance.addPostFrameCallback((_) => _syncAuthState());
  }

  Future<void> _syncAuthState() async {
    final auth = context.read<AuthController>();
    _apiService.setAccessToken(auth.token);

    if (auth.isAuthenticated && auth.user != null) {
      final savedSession = await _tokenStorage.loadChatSessionId(auth.user!.id);
      if (savedSession != null && mounted) {
        setState(() => sessionId = savedSession);
      }
    }

    if (mounted) setState(() => _authInitialized = true);
  }

  Future<void> _persistSessionId() async {
    final auth = context.read<AuthController>();
    if (!auth.isAuthenticated || auth.user == null) return;
    await _tokenStorage.saveChatSessionId(auth.user!.id, sessionId);
  }

  @override
  void dispose() {
    _pulseController.dispose();
    _scrollController.dispose();
    _controller.dispose();
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
  final String stem = sermonName.toLowerCase().endsWith('.pdf')
      ? sermonName.substring(0, sermonName.length - 4)
      : sermonName;
  final String expectedPdf = '$stem.pdf';

  try {
    final body = await _apiService.getIngestedDocuments(match: expectedPdf);
    final List<dynamic> docs = body['documents'] as List<dynamic>? ?? <dynamic>[];

    Map<String, dynamic>? match;
    for (final dynamic d in docs) {
      final Map<String, dynamic> map = d as Map<String, dynamic>;
      final String name = (map['source_name'] as String? ?? '').toLowerCase();
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
    final Uri fileUri = Uri.parse(Uri.base.origin).resolve(fileUrl);

    await launchUrl(fileUri, mode: LaunchMode.externalApplication);
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
  void _clearChat() {
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
                    setState(() => sessionId = const Uuid().v4());
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
    final auth = context.watch<AuthController>();
    if (!_authInitialized && auth.isAuthenticated) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _syncAuthState());
    }
    _apiService.setAccessToken(auth.token);

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
                  _buildNavButton("Nordin's AI", () => debugPrint("Already on AI Page")),
                  const SizedBox(width: 100),
                ],
              ),
            ),
        ],
      ),
      body: Stack(
        children: [
          Row(
            children: [
              if (!isMobileOrTablet) _buildSidebar(isMobile: false),
              Expanded(child: _buildChatInterface(isMobile)),
            ],
          ),
          if (_prayerPanelExpanded)
            Positioned.fill(
              child: GestureDetector(
                onTap: () => _togglePrayerPanel(expanded: false),
                child: Container(color: Colors.black12),
              ),
            ),
          Positioned(
            bottom: isMobile ? 90 + MediaQuery.of(context).viewInsets.bottom : 24,
            right: 24,
            child: _buildPrayerRequestPanel(isMobile),
          ),
        ],
      ),
    );
  }

  // ─── Sidebar ─────────────────────────────────────────────────────────────────
  Widget _buildSidebar({required bool isMobile}) {
    final auth = context.watch<AuthController>();

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
            if (auth.isAuthenticated) ...[
              const SizedBox(height: 20),
              Text("Your Conversations",
                  style: GoogleFonts.figtree(color: Colors.white70, fontSize: 14, fontWeight: FontWeight.w600)),
              const SizedBox(height: 8),
              Text(
                "Chat history will appear here once the backend sync is connected.",
                style: GoogleFonts.figtree(color: Colors.white54, fontSize: 12),
              ),
              const SizedBox(height: 16),
              Container(height: 1, color: Colors.white24),
            ],
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

  Widget _buildPrayerRequestPanel(bool isMobile) {
    final maxHeight = MediaQuery.of(context).size.height * 0.65;
    final panelWidth = isMobile ? MediaQuery.of(context).size.width - 32 : 420.0;

    if (!_prayerPanelExpanded) {
      return Material(
        elevation: 4,
        borderRadius: BorderRadius.circular(28),
        child: InkWell(
          onTap: () => _togglePrayerPanel(expanded: true),
          borderRadius: BorderRadius.circular(28),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(28),
              gradient: const LinearGradient(colors: [_pink, _navy]),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.volunteer_activism, color: _gold, size: 22),
                const SizedBox(width: 8),
                Text('Prayer Request Form', style: GoogleFonts.figtree(color: Colors.white, fontWeight: FontWeight.bold)),
              ],
            ),
          ),
        ),
      );
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
                    bottom: 88,
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