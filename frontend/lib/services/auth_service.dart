import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:http/http.dart' as http;

const kUseMockAuth = bool.fromEnvironment('USE_MOCK_AUTH', defaultValue: false);
const _baseUrl = String.fromEnvironment('API_BASE_URL', defaultValue: '');

class AuthUser {
  const AuthUser({
    required this.id,
    required this.email,
    required this.name,
    this.avatarUrl,
    this.isStaff = false,
    this.isPremium = false,
    this.emailVerified = true,
    this.hasUsablePassword = true,
    this.subscriptionStatus = 'free',
    this.billingPeriod = '',
    this.pendingBillingPeriod = '',
    this.cancelAtPeriodEnd = false,
    this.currentPeriodEnd,
  });

  final String id;
  final String email;
  final String name;
  final String? avatarUrl;
  final bool isStaff;
  final bool isPremium;
  final bool emailVerified;
  /// False for Google-only accounts that never set a password.
  final bool hasUsablePassword;
  final String subscriptionStatus;
  final String billingPeriod;
  final String pendingBillingPeriod;
  final bool cancelAtPeriodEnd;
  final DateTime? currentPeriodEnd;

  bool get isPaidPremium => subscriptionStatus == 'active';

  /// Active and past-due members can replace the card Stripe bills.
  bool get canManagePaymentMethod =>
      subscriptionStatus == 'active' || subscriptionStatus == 'past_due';

  /// Email/password accounts must enter the 6-digit code before checkout.
  /// Staff and Google-verified accounts skip this.
  bool get needsEmailVerification => !isStaff && !emailVerified;

  factory AuthUser.fromJson(Map<String, dynamic> json) => AuthUser(
        id: '${json['id']}',
        email: json['email'] as String? ?? '',
        name: json['name'] as String? ?? '',
        avatarUrl: json['avatar_url'] as String?,
        isStaff: json['is_staff'] as bool? ?? false,
        isPremium: json['is_premium'] as bool? ?? false,
        emailVerified: json['email_verified'] as bool? ?? true,
        hasUsablePassword: json['has_usable_password'] as bool? ?? true,
        subscriptionStatus: json['subscription_status'] as String? ?? 'free',
        billingPeriod: json['billing_period'] as String? ?? '',
        pendingBillingPeriod: json['pending_billing_period'] as String? ?? '',
        cancelAtPeriodEnd: json['cancel_at_period_end'] as bool? ?? false,
        currentPeriodEnd: _parseDate(json['current_period_end']),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'email': email,
        'name': name,
        if (avatarUrl != null) 'avatar_url': avatarUrl,
        'is_staff': isStaff,
        'is_premium': isPremium,
        'email_verified': emailVerified,
        'has_usable_password': hasUsablePassword,
        'subscription_status': subscriptionStatus,
        'billing_period': billingPeriod,
        'pending_billing_period': pendingBillingPeriod,
        'cancel_at_period_end': cancelAtPeriodEnd,
        if (currentPeriodEnd != null) 'current_period_end': currentPeriodEnd!.toIso8601String(),
      };

  AuthUser copyWith({
    String? id,
    String? email,
    String? name,
    String? avatarUrl,
    bool? isStaff,
    bool? isPremium,
    bool? emailVerified,
    bool? hasUsablePassword,
    String? subscriptionStatus,
    String? billingPeriod,
    String? pendingBillingPeriod,
    bool? cancelAtPeriodEnd,
    DateTime? currentPeriodEnd,
  }) {
    return AuthUser(
      id: id ?? this.id,
      email: email ?? this.email,
      name: name ?? this.name,
      avatarUrl: avatarUrl ?? this.avatarUrl,
      isStaff: isStaff ?? this.isStaff,
      isPremium: isPremium ?? this.isPremium,
      emailVerified: emailVerified ?? this.emailVerified,
      hasUsablePassword: hasUsablePassword ?? this.hasUsablePassword,
      subscriptionStatus: subscriptionStatus ?? this.subscriptionStatus,
      billingPeriod: billingPeriod ?? this.billingPeriod,
      pendingBillingPeriod: pendingBillingPeriod ?? this.pendingBillingPeriod,
      cancelAtPeriodEnd: cancelAtPeriodEnd ?? this.cancelAtPeriodEnd,
      currentPeriodEnd: currentPeriodEnd ?? this.currentPeriodEnd,
    );
  }

  static DateTime? _parseDate(dynamic value) {
    if (value is String && value.isNotEmpty) return DateTime.tryParse(value);
    return null;
  }
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

  static const String _compileTimeGoogleClientId =
      String.fromEnvironment('GOOGLE_CLIENT_ID');

  static String? _resolvedGoogleClientId;
  static bool _googleInitialized = false;
  static Future<void>? _googleInitFuture;

  static String? get resolvedGoogleClientId {
    if (_resolvedGoogleClientId != null && _resolvedGoogleClientId!.isNotEmpty) {
      return _resolvedGoogleClientId;
    }
    if (_compileTimeGoogleClientId.isNotEmpty) {
      return _compileTimeGoogleClientId;
    }
    return null;
  }

  static bool get isGoogleConfigured =>
      kUseMockAuth || (resolvedGoogleClientId?.isNotEmpty ?? false);

  /// Loads GOOGLE_CLIENT_ID from compile-time defines or GET /api/auth/config/.
  static Future<void> ensureGoogleSignInReady() {
    return _googleInitFuture ??= _initializeGoogleSignIn();
  }

  /// User-facing text for a Google sign-in failure. Cancelled attempts return
  /// null so the form can stay quiet.
  static String? googleErrorMessage(Object error) {
    if (error is GoogleSignInException) {
      if (error.code == GoogleSignInExceptionCode.canceled) return null;
      final description = error.description?.trim();
      if (description != null && description.isNotEmpty) return description;
    }
    final text = error.toString().replaceFirst(RegExp(r'^Exception:\s*'), '').trim();
    if (text.isEmpty) return 'Google sign-in failed. Please try again.';
    return text;
  }

  static Future<void> _initializeGoogleSignIn() async {
    if (kUseMockAuth) return;

    var clientId = _compileTimeGoogleClientId;
    if (clientId.isEmpty) {
      try {
        final client = http.Client();
        try {
          final base = _baseUrlForConfig();
          final uri = base.isEmpty
              ? Uri.parse('/api/auth/config/')
              : Uri.parse('${base.endsWith('/') ? base : '$base/'}api/auth/config/');
          final res = await client.get(
            uri,
            headers: const {'Accept': 'application/json'},
          );
          if (res.statusCode >= 200 && res.statusCode < 300) {
            final body = jsonDecode(res.body) as Map<String, dynamic>;
            clientId = (body['google_client_id'] as String?) ?? '';
          }
        } finally {
          client.close();
        }
      } catch (_) {
        // Fall through — button stays disabled if config cannot load.
      }
    }

    if (clientId.isEmpty) return;

    _resolvedGoogleClientId = clientId;
    // Sign-in only needs an ID token. Do not pass email/profile/openid as
    // OAuth scopes: that opens Google's authorization client, and new Web
    // clients are rejected with an OAuth 2.0 error. The ID token already
    // includes email and profile.
    //
    // Web uses clientId. Android has no google-services.json, so the same Web
    // client is serverClientId (the ID token audience Django checks). Passing
    // serverClientId on web throws.
    try {
      await GoogleSignIn.instance.initialize(
        clientId: kIsWeb ||
                defaultTargetPlatform == TargetPlatform.iOS ||
                defaultTargetPlatform == TargetPlatform.macOS
            ? clientId
            : null,
        serverClientId: kIsWeb ? null : clientId,
      );
      _googleInitialized = true;
    } catch (e) {
      _resolvedGoogleClientId = null;
      _googleInitialized = false;
      _googleInitFuture = null;
      rethrow;
    }
  }

  static String _baseUrlForConfig() =>
      const String.fromEnvironment('API_BASE_URL', defaultValue: '');

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

  /// Mobile / desktop: interactive `authenticate()`.
  /// Web: use the Google Identity Services button, then
  /// [signInWithGoogleAccount]. `authenticate()` is not supported on web.
  Future<AuthResult> signInWithGoogle() async {
    await ensureGoogleSignInReady();
    if (!isGoogleConfigured) {
      throw AuthException('Google Sign-In is not configured. Set GOOGLE_CLIENT_ID.');
    }

    if (kUseMockAuth) {
      await Future<void>.delayed(const Duration(milliseconds: 600));
      return _mockResult(email: 'google.user@example.com', name: 'Google User');
    }

    if (!GoogleSignIn.instance.supportsAuthenticate()) {
      throw AuthException(
        'On web, use the Google button to sign in '
        '(it provides a verified ID token).',
      );
    }

    try {
      final account = await GoogleSignIn.instance.authenticate();
      return await signInWithGoogleAccount(account);
    } on GoogleSignInException catch (e) {
      final message = googleErrorMessage(e);
      throw AuthException(message ?? 'Google sign-in was cancelled.');
    }
  }

  /// Exchange a Google account (from the web button or mobile authenticate)
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

    final idToken = account.authentication.idToken;
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

  Future<void> changePassword({
    required String token,
    required String currentPassword,
    required String newPassword,
  }) async {
    if (kUseMockAuth) {
      await Future<void>.delayed(const Duration(milliseconds: 400));
      return;
    }

    final res = await _client.post(
      Uri.parse(_resolveUrl('/api/auth/change-password/')),
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': 'Token $token',
      },
      body: jsonEncode({
        'current_password': currentPassword,
        'new_password': newPassword,
      }),
    );
    if (res.statusCode >= 200 && res.statusCode < 300) return;
    throw AuthException(_authErrorMessage(res, fallback: 'Could not change password'));
  }

  /// Asks the server to email a reset code. The response does not say whether
  /// the address has an account.
  Future<String> requestPasswordReset({required String email}) async {
    const fallback =
        'If an account with that email exists, we sent password reset instructions.';
    if (kUseMockAuth) {
      await Future<void>.delayed(const Duration(milliseconds: 400));
      return fallback;
    }

    final res = await _client.post(
      Uri.parse(_resolveUrl('/api/auth/forgot-password/')),
      headers: const {'Content-Type': 'application/json', 'Accept': 'application/json'},
      body: jsonEncode({'email': email.trim()}),
    );
    if (res.statusCode >= 200 && res.statusCode < 300) {
      final body = _tryDecode(res.body);
      final detail = body?['detail'];
      if (detail is String && detail.isNotEmpty) return detail;
      return fallback;
    }
    throw AuthException(_authErrorMessage(res, fallback: 'Could not send a reset code'));
  }

  Future<String> resetPassword({
    required String email,
    required String code,
    required String newPassword,
  }) async {
    const fallback = 'Password updated. You can sign in with your new password.';
    if (kUseMockAuth) {
      await Future<void>.delayed(const Duration(milliseconds: 400));
      return fallback;
    }

    final res = await _client.post(
      Uri.parse(_resolveUrl('/api/auth/reset-password/')),
      headers: const {'Content-Type': 'application/json', 'Accept': 'application/json'},
      body: jsonEncode({
        'email': email.trim(),
        'code': code.trim(),
        'new_password': newPassword,
      }),
    );
    if (res.statusCode >= 200 && res.statusCode < 300) {
      final body = _tryDecode(res.body);
      final detail = body?['detail'];
      if (detail is String && detail.isNotEmpty) return detail;
      return fallback;
    }
    throw AuthException(_authErrorMessage(res, fallback: 'Could not reset password'));
  }

  Future<AuthUser> changeName({
    required String token,
    required String name,
  }) async {
    if (kUseMockAuth) {
      await Future<void>.delayed(const Duration(milliseconds: 300));
      return AuthUser(
        id: 'mock',
        email: 'mock@example.com',
        name: name.trim(),
      );
    }

    final res = await _client.post(
      Uri.parse(_resolveUrl('/api/auth/change-name/')),
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': 'Token $token',
      },
      body: jsonEncode({'name': name}),
    );
    return _parseUserUpdateResponse(res, fallback: 'Could not update name');
  }

  Future<AuthUser> changeEmail({
    required String token,
    required String email,
    required String currentPassword,
  }) async {
    if (kUseMockAuth) {
      await Future<void>.delayed(const Duration(milliseconds: 300));
      return AuthUser(
        id: 'mock',
        email: email.trim().toLowerCase(),
        name: 'Mock User',
        emailVerified: false,
      );
    }

    final res = await _client.post(
      Uri.parse(_resolveUrl('/api/auth/change-email/')),
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': 'Token $token',
      },
      body: jsonEncode({
        'email': email,
        'current_password': currentPassword,
      }),
    );
    return _parseUserUpdateResponse(res, fallback: 'Could not update email');
  }

  AuthUser _parseUserUpdateResponse(http.Response res, {required String fallback}) {
    if (res.statusCode >= 200 && res.statusCode < 300) {
      final body = jsonDecode(res.body) as Map<String, dynamic>;
      final userJson = body['user'] as Map<String, dynamic>?;
      if (userJson == null) {
        throw AuthException('Unexpected response from server.');
      }
      return AuthUser.fromJson(userJson);
    }
    throw AuthException(_authErrorMessage(res, fallback: fallback));
  }

  String _authErrorMessage(http.Response res, {required String fallback}) {
    final body = _tryDecode(res.body);
    final detail = body?['detail'];
    if (detail is String && detail.isNotEmpty) return detail;
    if (body != null) {
      for (final entry in body.entries) {
        final value = entry.value;
        if (value is List && value.isNotEmpty) return '${value.first}';
        if (value is String && value.isNotEmpty) return value;
      }
    }
    if (res.statusCode == 401) return 'Session expired. Please sign in again.';
    return '$fallback (${res.statusCode}).';
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
      if (_googleInitialized) {
        await GoogleSignIn.instance.signOut();
      }
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
      final body = _tryDecode(res.body);
      final detail = body?['detail'];
      if (detail is String && detail.isNotEmpty) {
        throw AuthException(detail);
      }
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
