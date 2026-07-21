import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:http/http.dart' as http;

const kUseMockAuth = bool.fromEnvironment('USE_MOCK_AUTH', defaultValue: false);
const _googleClientId = String.fromEnvironment('GOOGLE_CLIENT_ID');
const _baseUrl = String.fromEnvironment('API_BASE_URL', defaultValue: '');

class AuthUser {
  const AuthUser({
    required this.id,
    required this.email,
    required this.name,
    this.avatarUrl,
    this.isStaff = false,
  });

  final String id;
  final String email;
  final String name;
  final String? avatarUrl;
  final bool isStaff;

  factory AuthUser.fromJson(Map<String, dynamic> json) => AuthUser(
        id: '${json['id']}',
        email: json['email'] as String? ?? '',
        name: json['name'] as String? ?? '',
        avatarUrl: json['avatar_url'] as String?,
        isStaff: json['is_staff'] as bool? ?? false,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'email': email,
        'name': name,
        if (avatarUrl != null) 'avatar_url': avatarUrl,
        'is_staff': isStaff,
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

  /// Shared plugin instance so the web GIS `renderButton` and token exchange
  /// use the same client configuration.
  static final GoogleSignIn googleSignIn = GoogleSignIn(
    clientId: _googleClientId.isNotEmpty ? _googleClientId : null,
    scopes: const <String>['email', 'profile', 'openid'],
  );

  static bool get isGoogleConfigured =>
      kUseMockAuth || _googleClientId.isNotEmpty;

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

  /// Mobile / desktop: interactive `signIn()`.
  /// Web: prefer [signInWithGoogleAccount] after GIS `renderButton` / One Tap.
  Future<AuthResult> signInWithGoogle() async {
    if (!isGoogleConfigured) {
      throw AuthException('Google Sign-In is not configured. Set GOOGLE_CLIENT_ID.');
    }

    if (kIsWeb) {
      final current = googleSignIn.currentUser;
      if (current != null) {
        return signInWithGoogleAccount(current);
      }
      throw AuthException(
        'On web, use the Google button to sign in '
        '(it provides a verified ID token).',
      );
    }

    final account = await googleSignIn.signIn();
    if (account == null) throw AuthException('Google sign-in was cancelled.');
    return signInWithGoogleAccount(account);
  }

  /// Exchange a Google account (from `renderButton` / One Tap / mobile signIn)
  /// for a Django DRF Token.
  Future<AuthResult> signInWithGoogleAccount(GoogleSignInAccount account) async {
    if (kUseMockAuth) {
      await Future<void>.delayed(const Duration(milliseconds: 600));
      return _mockResult(
        email: account.email,
        name: account.displayName ?? account.email.split('@').first,
        avatarUrl: account.photoUrl,
      );
    }

    final googleAuth = await account.authentication;
    final idToken = googleAuth.idToken;
    if (idToken == null || idToken.isEmpty) {
      throw AuthException(
        'Could not obtain a Google ID token. '
        'On web, use the official Google Sign-In button (not a custom button).',
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
        // DRF TokenAuthentication expects "Token <key>", not Bearer.
        'Authorization': 'Token $token',
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
          // DRF TokenAuthentication expects "Token <key>", not Bearer.
          'Authorization': 'Token $token',
        },
      );
    } catch (_) {
      // Best-effort logout; local session is cleared regardless.
    }

    try {
      await googleSignIn.signOut();
    } catch (_) {
      // Ignore Google sign-out failures.
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
    if (res.statusCode == 401 || res.statusCode == 400 || res.statusCode == 503) {
      final body = _tryDecode(res.body);
      throw AuthException(
        body?['detail'] as String? ??
            (res.statusCode == 503
                ? 'Google Sign-In is not configured on the server.'
                : 'Invalid email or password.'),
      );
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
