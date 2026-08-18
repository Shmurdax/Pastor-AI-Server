import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:shared_preferences/shared_preferences.dart';

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

  bool get isPremium => user?.isPremium ?? false;

  /// Paid Premium members and staff (staff inherit Premium entitlements).
  bool get hasPremiumAccess =>
      (user?.isStaff ?? false) || isPremium || (user?.isPaidPremium ?? false);

  Future<void> applyUser(AuthUser next) async {
    user = next;
    if (token != null) {
      await _tokenStorage.saveSession(token: token!, user: next);
    }
    notifyListeners();
  }

  Future<bool> refreshMe() async {
    if (token == null) return false;
    try {
      final me = await _authService.getMe(token!);
      await applyUser(me);
      return true;
    } catch (_) {
      return false;
    }
  }

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
