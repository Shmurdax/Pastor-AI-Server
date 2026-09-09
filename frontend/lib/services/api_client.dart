import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter_application_1/chat_stream.dart';
import 'package:flutter_application_1/models/church_event.dart';
import 'package:flutter_application_1/models/prayer_request.dart';
import 'package:flutter_application_1/models/response_report.dart';
import 'package:http/http.dart' as http;

/// When false, POSTs to Django `POST /api/prayer-requests/` with body:
/// `{ name, email, phone, prayer_text, is_anonymous }` -> `{ success, id, message }`
const kUseMockPrayer = bool.fromEnvironment('USE_MOCK_PRAYER', defaultValue: false);

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

  Map<String, String> _headers({bool json = false, String? accept}) => {
        if (json) 'Content-Type': 'application/json',
        'Accept': accept ?? 'application/json',
        if (_apiKey.isNotEmpty) 'X-API-Key': _apiKey,
        // DRF TokenAuthentication expects "Token <key>", not Bearer.
        if (_accessToken != null && _accessToken!.isNotEmpty)
          'Authorization': 'Token $_accessToken',
      };

  Future<Map<String, dynamic>> chat({
    required String query,
    required String sessionId,
    bool regenerate = false,
    String language = 'en',
  }) async {
    final res = await _client.post(
      Uri.parse(_resolveUrl('/api/chat/')),
      headers: _headers(json: true),
      body: jsonEncode({
        'query': query,
        'session_id': sessionId,
        'regenerate': regenerate,
        'language': language,
      }),
    );
    _ensureOk(res);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  /// Streams model tokens as they are generated. [onDelta] receives each text chunk.
  /// Returns the final payload (`answer`, `sources`, `message_id`).
  Future<Map<String, dynamic>> chatStream({
    required String query,
    required String sessionId,
    bool regenerate = false,
    String language = 'en',
    http.Client? client,
    required void Function(String delta) onDelta,
    bool Function()? isCancelled,
  }) async {
    bool cancelled() => isCancelled?.call() ?? false;
    final httpClient = client ?? _client;
    final request = http.Request('POST', Uri.parse(_resolveUrl('/api/chat/')));
    request.headers.addAll(
      _headers(json: true, accept: 'text/event-stream, application/json'),
    );
    request.body = jsonEncode({
      'query': query,
      'session_id': sessionId,
      'regenerate': regenerate,
      'language': language,
      'stream': true,
    });

    if (cancelled()) {
      return {'answer': '', 'sources': <String>[], 'cancelled': true};
    }

    final streamed = await httpClient.send(request);
    if (cancelled()) {
      return {'answer': '', 'sources': <String>[], 'cancelled': true};
    }
    if (streamed.statusCode < 200 || streamed.statusCode >= 300) {
      final body = await streamed.stream.bytesToString();
      throw Exception('HTTP ${streamed.statusCode}: $body');
    }

    final contentType = streamed.headers['content-type'] ?? '';
    if (!contentType.contains('event-stream')) {
      final body = await streamed.stream.bytesToString();
      if (cancelled()) {
        return {'answer': '', 'sources': <String>[], 'cancelled': true};
      }
      final decoded = jsonDecode(body);
      if (decoded is! Map<String, dynamic>) {
        throw Exception('Unexpected chat response');
      }
      final answer = decoded['answer']?.toString() ?? '';
      if (answer.isNotEmpty) onDelta(answer);
      return decoded;
    }

    final carry = StringBuffer();
    Map<String, dynamic>? done;
    String assembled = '';
    await for (final chunk in streamed.stream.transform(utf8.decoder)) {
      if (cancelled()) {
        return {
          'answer': assembled,
          'sources': <String>[],
          'cancelled': true,
        };
      }
      for (final event in consumeSseChunk(carry, chunk)) {
        if (cancelled()) {
          return {
            'answer': assembled,
            'sources': <String>[],
            'cancelled': true,
          };
        }
        if (event.isDelta && event.text.isNotEmpty) {
          assembled += event.text;
          onDelta(event.text);
        } else if (event.isDone) {
          done = {
            'answer': event.answer.isNotEmpty ? event.answer : assembled,
            'sources': event.sources,
            if (event.messageId != null) 'message_id': event.messageId,
          };
        } else if (event.isError) {
          throw Exception(event.error.isNotEmpty ? event.error : 'Chat stream failed');
        }
      }
    }
    if (cancelled()) {
      return {
        'answer': assembled,
        'sources': <String>[],
        'cancelled': true,
      };
    }
    if (done != null) return done;
    if (assembled.isNotEmpty) {
      return {'answer': assembled, 'sources': <String>[]};
    }
    throw Exception('Chat stream ended without a response');
  }

  /// Kick the serverless GPU while the user is still browsing. Failures are
  /// ignored: a short timeout still queues the worker on RunPod.
  Future<void> warmupChat() async {
    try {
      await _client.post(
        Uri.parse(_resolveUrl('/api/chat/warmup/')),
        headers: _headers(json: true),
        body: '{}',
      );
    } catch (_) {
      // Fire-and-forget.
    }
  }

  Future<List<String>> translateTexts({
    required List<String> texts,
    required String language,
  }) async {
    final res = await _client.post(
      Uri.parse(_resolveUrl('/api/translate/')),
      headers: _headers(json: true),
      body: jsonEncode({
        'texts': texts,
        'language': language,
      }),
    );
    _ensureOk(res);
    final body = jsonDecode(res.body) as Map<String, dynamic>;
    final out = body['texts'];
    if (out is! List) return texts;
    return out.map((e) => e?.toString() ?? '').toList();
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

  Future<List<PrayerRequestItem>> listPrayerRequests({bool? followedUp}) async {
    final qp = <String, String>{};
    if (followedUp != null) qp['followed_up'] = followedUp ? 'true' : 'false';
    final uri = Uri.parse(_resolveUrl('/api/prayer-requests/')).replace(queryParameters: qp.isEmpty ? null : qp);
    final res = await _client.get(uri, headers: _headers());
    _ensureOk(res);
    final body = jsonDecode(res.body) as Map<String, dynamic>;
    final results = body['results'] as List<dynamic>? ?? [];
    return results
        .map((e) => PrayerRequestItem.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<PrayerRequestItem> updatePrayerRequest(
    int id, {
    bool? followedUp,
    String? pastorNotes,
    DateTime? contactedAt,
  }) async {
    final payload = <String, dynamic>{};
    if (followedUp != null) payload['followed_up'] = followedUp;
    if (pastorNotes != null) payload['pastor_notes'] = pastorNotes;
    if (contactedAt != null) payload['contacted_at'] = contactedAt.toUtc().toIso8601String();

    final res = await _client.patch(
      Uri.parse(_resolveUrl('/api/prayer-requests/$id/')),
      headers: _headers(json: true),
      body: jsonEncode(payload),
    );
    _ensureOk(res);
    return PrayerRequestItem.fromJson(jsonDecode(res.body) as Map<String, dynamic>);
  }

  Future<List<ChurchEventItem>> listChurchEvents() async {
    final res = await _client.get(
      Uri.parse(_resolveUrl('/api/church-events/')),
      headers: _headers(),
    );
    _ensureOk(res);
    final body = jsonDecode(res.body) as Map<String, dynamic>;
    final results = body['results'] as List<dynamic>? ?? [];
    return results
        .map((e) => ChurchEventItem.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<ChurchEventItem> createChurchEvent(Map<String, dynamic> payload) async {
    final res = await _client.post(
      Uri.parse(_resolveUrl('/api/church-events/')),
      headers: _headers(json: true),
      body: jsonEncode(payload),
    );
    _ensureOk(res);
    return ChurchEventItem.fromJson(jsonDecode(res.body) as Map<String, dynamic>);
  }

  Future<ChurchEventItem> updateChurchEvent(int id, Map<String, dynamic> payload) async {
    final res = await _client.patch(
      Uri.parse(_resolveUrl('/api/church-events/$id/')),
      headers: _headers(json: true),
      body: jsonEncode(payload),
    );
    _ensureOk(res);
    return ChurchEventItem.fromJson(jsonDecode(res.body) as Map<String, dynamic>);
  }

  Future<void> deleteChurchEvent(int id) async {
    final res = await _client.delete(
      Uri.parse(_resolveUrl('/api/church-events/$id/')),
      headers: _headers(),
    );
    _ensureOk(res);
  }

  Future<Map<String, dynamic>> getBillingConfig() async {
    final res = await _client.get(
      Uri.parse(_resolveUrl('/api/billing/config/')),
      headers: _headers(),
    );
    _ensureOk(res);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> createCheckoutSession({
    required String billingPeriod,
  }) async {
    final res = await _client.post(
      Uri.parse(_resolveUrl('/api/billing/create-checkout-session/')),
      headers: _headers(json: true),
      body: jsonEncode({'billing_period': billingPeriod}),
    );
    _ensureOk(res);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> getCheckoutSessionStatus(String sessionId) async {
    final uri = Uri.parse(_resolveUrl('/api/billing/session-status/')).replace(
      queryParameters: {'session_id': sessionId},
    );
    final res = await _client.get(uri, headers: _headers());
    _ensureOk(res);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  /// TEMPORARY mock activate — never send card fields. Remove with mock checkout.
  Future<Map<String, dynamic>> mockActivatePremium({
    required String billingPeriod,
  }) async {
    final res = await _client.post(
      Uri.parse(_resolveUrl('/api/billing/mock-activate/')),
      headers: _headers(json: true),
      body: jsonEncode({'billing_period': billingPeriod}),
    );
    _ensureOk(res);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> cancelSubscription() async {
    final res = await _client.post(
      Uri.parse(_resolveUrl('/api/billing/cancel-subscription/')),
      headers: _headers(json: true),
      body: jsonEncode(const {}),
    );
    _ensureOk(res);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> submitResponseReport({
    required int messageId,
    required String reason,
    required String sessionId,
    String details = '',
  }) async {
    final res = await _client.post(
      Uri.parse(_resolveUrl('/api/response-reports/')),
      headers: _headers(json: true),
      body: jsonEncode({
        'message_id': messageId,
        'reason': reason,
        'details': details,
        'session_id': sessionId,
      }),
    );
    _ensureOk(res);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  Future<List<ResponseReportItem>> listResponseReports({String? status}) async {
    final qp = <String, String>{};
    if (status != null && status.trim().isNotEmpty) qp['status'] = status.trim();
    final uri = Uri.parse(_resolveUrl('/api/response-reports/')).replace(
      queryParameters: qp.isEmpty ? null : qp,
    );
    final res = await _client.get(uri, headers: _headers());
    _ensureOk(res);
    final body = jsonDecode(res.body) as Map<String, dynamic>;
    final results = body['results'] as List<dynamic>? ?? [];
    return results
        .map((e) => ResponseReportItem.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<ResponseReportItem> updateResponseReport(
    int id, {
    String? status,
    String? staffNotes,
  }) async {
    final payload = <String, dynamic>{};
    if (status != null) payload['status'] = status;
    if (staffNotes != null) payload['staff_notes'] = staffNotes;

    final res = await _client.patch(
      Uri.parse(_resolveUrl('/api/response-reports/$id/')),
      headers: _headers(json: true),
      body: jsonEncode(payload),
    );
    _ensureOk(res);
    return ResponseReportItem.fromJson(jsonDecode(res.body) as Map<String, dynamic>);
  }

  Future<List<Map<String, dynamic>>> listMediaVideos() async {
    final res = await _client.get(
      Uri.parse(_resolveUrl('/api/media/')),
      headers: _headers(),
    );
    _ensureOk(res);
    final body = jsonDecode(res.body) as Map<String, dynamic>;
    final results = body['results'] as List<dynamic>? ?? [];
    return results.map((e) => Map<String, dynamic>.from(e as Map)).toList();
  }

  void _ensureOk(http.Response res) {
    if (res.statusCode >= 200 && res.statusCode < 300) return;
    throw Exception('HTTP ${res.statusCode}: ${res.body}');
  }
}
