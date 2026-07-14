import 'dart:convert';
import 'dart:typed_data';
import 'package:http/http.dart' as http;

/// When false, POSTs to Django `POST /api/prayer-requests/` with body:
/// `{ name, email, phone, prayer_text, is_anonymous }` -> `{ success, id, message }`
const kUseMockPrayer = bool.fromEnvironment('USE_MOCK_PRAYER', defaultValue: true);

class ApiClient {
  ApiClient({http.Client? client}) : _client = client ?? http.Client();
  final http.Client _client;

  static const String _baseUrl = String.fromEnvironment('API_BASE_URL', defaultValue: '');
  static const String _apiKey = String.fromEnvironment('PUBLIC_API_KEY');

  String? _accessToken;

  void setAccessToken(String? token) => _accessToken = token;

  String _resolveUrl(String path) {
    final normalizedPath = path.startsWith('/') ? path : '/$path';
    if (_baseUrl.isEmpty) return normalizedPath;
    final base = _baseUrl.endsWith('/') ? _baseUrl : '$_baseUrl/';
    return '$base${normalizedPath.substring(1)}';
  }

  Map<String, String> _headers({bool json = false}) => {
        if (json) 'Content-Type': 'application/json',
        'Accept': 'application/json',
        if (_apiKey.isNotEmpty) 'X-API-Key': _apiKey,
        if (_accessToken != null && _accessToken!.isNotEmpty)
          'Authorization': 'Bearer $_accessToken',
      };

  Future<Map<String, dynamic>> chat({
    required String query,
    required String sessionId,
    bool regenerate = false,
  }) async {
    final res = await _client.post(
      Uri.parse(_resolveUrl('/api/chat/')),
      headers: _headers(json: true),
      body: jsonEncode({
        'query': query,
        'session_id': sessionId,
        'regenerate': regenerate,
      }),
    );
    _ensureOk(res);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> getIngestedDocuments({
    int limit = 1000,
    String? match,
  }) async {
    final qp = <String, String>{'limit': '$limit'};
    if (match != null && match.trim().isNotEmpty) qp['match'] = match.trim();
    final uri = Uri.parse(_resolveUrl('/api/ingested-documents/'))
        .replace(queryParameters: qp);
    final res = await _client.get(uri, headers: _headers());
    _ensureOk(res);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  Future<Uint8List> getDocumentFile(int id) async {
    final res = await _client.get(
      Uri.parse(_resolveUrl('/api/ingested-documents/$id/file/')),
      headers: _headers(),
    );
    _ensureOk(res);
    return res.bodyBytes;
  }

  Future<Uint8List> getSermonPdfByName(String sermonName) async {
    final safe = Uri.encodeComponent(sermonName);
    final res = await _client.get(
      Uri.parse(_resolveUrl('/sermons/$safe.pdf')),
      headers: _headers(),
    );
    _ensureOk(res);
    return res.bodyBytes;
  }

  Future<Map<String, dynamic>> submitPrayerRequest({
    required String prayerText,
    String? name,
    String? email,
    String? phone,
    bool isAnonymous = false,
  }) async {
    if (kUseMockPrayer) {
      await Future<void>.delayed(const Duration(milliseconds: 500));
      return {
        'success': true,
        'id': 'mock-${DateTime.now().millisecondsSinceEpoch}',
        'message': 'Prayer request received.',
      };
    }

    final res = await _client.post(
      Uri.parse(_resolveUrl('/api/prayer-requests/')),
      headers: _headers(json: true),
      body: jsonEncode({
        'name': name ?? '',
        'email': email ?? '',
        'phone': phone ?? '',
        'prayer_text': prayerText,
        'is_anonymous': isAnonymous,
      }),
    );
    _ensureOk(res);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  void _ensureOk(http.Response res) {
    if (res.statusCode >= 200 && res.statusCode < 300) return;
    throw Exception('HTTP ${res.statusCode}: ${res.body}');
  }
}
