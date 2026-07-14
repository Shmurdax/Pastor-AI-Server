import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:http/http.dart' as http;

const kUseMockAuth = bool.fromEnvironment('USE_MOCK_AUTH', defaultValue: true);
const _googleClientId = String.fromEnvironment('GOOGLE_CLIENT_ID');
const _baseUrl = String.fromEnvironment('API_BASE_URL', defaultValue: '');

class AuthUser {
  const AuthUser({
    required this.id,
    required this.email,
    required this.name,
    this.avatarUrl,
  });

  final String id;
  final String email;
  final String name;
  final String? avatarUrl;

  factory AuthUser.fromJson(Map<String, dynamic> json) => AuthUser(
        id: '${json['id']}',
        email: json['email'] as String? ?? '',
        name: json['name'] as String? ?? '',
        avatarUrl: json['avatar_url'] as String?,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'email': email,
        'name': name,
        if (avatarUrl != null) 'avatar_url': avatarUrl,
      };
}

class AuthResult {
  const AuthResult({required this.token, required this.user});

  final String token;
  final AuthUser user;
}

class AuthException implements Exception {
  AuthException(this.message);
  final String message;

  @override
  String toString() => message;
}

class AuthService {
  AuthService({http.Client? client}) : _client = client ?? http.Client();
  final http.Client _client;

  String _resolveUrl(String path) {
    final normalizedPath = path.startsWith('/') ? path : '/$path';
    if (_baseUrl.isEmpty) return normalizedPath;
    final base = _baseUrl.endsWith('/') ? _baseUrl : '$_baseUrl/';
    return '$base${normalizedPath.substring(1)}';
  }

  Future<AuthResult> login({required String email, required String password}) async {
    if (kUseMockAuth) {
      await Future<void>.delayed(const Duration(milliseconds: 600));
      return _mockResult(email: email, name: email.split('@').first);
    }

    final res = await _client.post(
      Uri.parse(_resolveUrl('/api/auth/login/')),
      headers: const {'Content-Type': 'application/json', 'Accept': 'application/json'},
      body: jsonEncode({'email': email, 'password': password}),
    );
    return _parseAuthResponse(res);
  }

  Future<AuthResult> register({
    required String name,
    required String email,
    required String password,
  }) async {
    if (kUseMockAuth) {
      await Future<void>.delayed(const Duration(milliseconds: 600));
      return _mockResult(email: email, name: name);
    }

    final res = await _client.post(
      Uri.parse(_resolveUrl('/api/auth/register/')),
      headers: const {'Content-Type': 'application/json', 'Accept': 'application/json'},
      body: jsonEncode({'name': name, 'email': email, 'password': password}),
    );
    return _parseAuthResponse(res);
  }

  Future<AuthResult> signInWithGoogle() async {
    if (_googleClientId.isEmpty && !kUseMockAuth) {
      throw AuthException('Google Sign-In is not configured. Set GOOGLE_CLIENT_ID.');
    }

    final googleSignIn = GoogleSignIn(
      clientId: kIsWeb && _googleClientId.isNotEmpty ? _googleClientId : null,
      scopes: const ['email', 'profile'],
    );

    final account = await googleSignIn.signIn();
    if (account == null) throw AuthException('Google sign-in was cancelled.');

    final auth = await account.authentication;
    final idToken = auth.idToken;
    if (idToken == null || idToken.isEmpty) {
      throw AuthException('Could not obtain a Google ID token.');
    }

    if (kUseMockAuth) {
      await Future<void>.delayed(const Duration(milliseconds: 600));
      return _mockResult(
        email: account.email,
        name: account.displayName ?? account.email.split('@').first,
        avatarUrl: account.photoUrl,
      );
    }

    final res = await _client.post(
      Uri.parse(_resolveUrl('/api/auth/google/')),
      headers: const {'Content-Type': 'application/json', 'Accept': 'application/json'},
      body: jsonEncode({'id_token': idToken}),
    );
    return _parseAuthResponse(res);
  }

  Future<AuthUser> getMe(String token) async {
    if (kUseMockAuth) {
      await Future<void>.delayed(const Duration(milliseconds: 200));
      throw AuthException('Mock session expired.');
    }

    final res = await _client.get(
      Uri.parse(_resolveUrl('/api/auth/me/')),
      headers: {
        'Accept': 'application/json',
        'Authorization': 'Bearer $token',
      },
    );
    if (res.statusCode == 401) throw AuthException('Session expired. Please sign in again.');
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw AuthException('Could not verify session (${res.statusCode}).');
    }
    final body = jsonDecode(res.body) as Map<String, dynamic>;
    return AuthUser.fromJson(body['user'] as Map<String, dynamic>? ?? body);
  }

  Future<void> logout(String token) async {
    if (kUseMockAuth) return;

    try {
      await _client.post(
        Uri.parse(_resolveUrl('/api/auth/logout/')),
        headers: {
          'Accept': 'application/json',
          'Authorization': 'Bearer $token',
        },
      );
    } catch (_) {
      // Best-effort logout; local session is cleared regardless.
    }
  }

  AuthResult _mockResult({required String email, required String name, String? avatarUrl}) {
    final safeEmail = email.trim().toLowerCase();
    return AuthResult(
      token: 'mock-token-${safeEmail.hashCode}',
      user: AuthUser(
        id: 'mock-${safeEmail.hashCode}',
        email: safeEmail,
        name: name.trim().isEmpty ? 'Guest User' : name.trim(),
        avatarUrl: avatarUrl,
      ),
    );
  }

  AuthResult _parseAuthResponse(http.Response res) {
    if (res.statusCode == 401 || res.statusCode == 400) {
      final body = _tryDecode(res.body);
      throw AuthException(body?['detail'] as String? ?? 'Invalid email or password.');
    }
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw AuthException('Authentication failed (${res.statusCode}).');
    }
    final body = jsonDecode(res.body) as Map<String, dynamic>;
    final token = body['token'] as String?;
    final userJson = body['user'] as Map<String, dynamic>?;
    if (token == null || userJson == null) {
      throw AuthException('Unexpected response from authentication server.');
    }
    return AuthResult(token: token, user: AuthUser.fromJson(userJson));
  }

  Map<String, dynamic>? _tryDecode(String body) {
    try {
      return jsonDecode(body) as Map<String, dynamic>;
    } catch (_) {
      return null;
    }
  }
}
