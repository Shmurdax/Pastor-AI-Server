import 'package:flutter_application_1/models/church_event.dart';
import 'package:flutter_application_1/models/media_item.dart';
import 'package:flutter_application_1/models/prayer_request.dart';
import 'package:flutter_application_1/models/response_report.dart';

import 'api_client.dart';

class ApiService {
  ApiService({ApiClient? apiClient}) : _apiClient = apiClient ?? ApiClient();
  final ApiClient _apiClient;

  void setAccessToken(String? token) => _apiClient.setAccessToken(token);

  Future<Map<String, dynamic>> sendMessage(
    String query,
    String sessionId, {
    bool regenerate = false,
    String language = 'en',
  }) async {
    return _apiClient.chat(
      query: query,
      sessionId: sessionId,
      regenerate: regenerate,
      language: language,
    );
  }

  Future<List<String>> translateTexts({
    required List<String> texts,
    required String language,
  }) {
    return _apiClient.translateTexts(texts: texts, language: language);
  }

  Future<Map<String, dynamic>> getIngestedDocuments({
    int limit = 1000,
    String? match,
  }) {
    return _apiClient.getIngestedDocuments(limit: limit, match: match);
  }

  Future<Map<String, dynamic>> submitPrayerRequest({
    required String prayerText,
    String? name,
    String? email,
    String? phone,
    bool isAnonymous = false,
  }) {
    return _apiClient.submitPrayerRequest(
      prayerText: prayerText,
      name: name,
      email: email,
      phone: phone,
      isAnonymous: isAnonymous,
    );
  }

  Future<List<PrayerRequestItem>> listPrayerRequests({bool? followedUp}) {
    return _apiClient.listPrayerRequests(followedUp: followedUp);
  }

  Future<PrayerRequestItem> updatePrayerRequest(
    int id, {
    bool? followedUp,
    String? pastorNotes,
    DateTime? contactedAt,
  }) {
    return _apiClient.updatePrayerRequest(
      id,
      followedUp: followedUp,
      pastorNotes: pastorNotes,
      contactedAt: contactedAt,
    );
  }

  Future<List<ChurchEventItem>> listChurchEvents() => _apiClient.listChurchEvents();

  Future<ChurchEventItem> createChurchEvent(Map<String, dynamic> payload) =>
      _apiClient.createChurchEvent(payload);

  Future<ChurchEventItem> updateChurchEvent(int id, Map<String, dynamic> payload) =>
      _apiClient.updateChurchEvent(id, payload);

  Future<void> deleteChurchEvent(int id) => _apiClient.deleteChurchEvent(id);

  Future<Map<String, dynamic>> getBillingConfig() => _apiClient.getBillingConfig();

  Future<Map<String, dynamic>> createCheckoutSession({required String billingPeriod}) =>
      _apiClient.createCheckoutSession(billingPeriod: billingPeriod);

  Future<Map<String, dynamic>> getCheckoutSessionStatus(String sessionId) =>
      _apiClient.getCheckoutSessionStatus(sessionId);

  Future<Map<String, dynamic>> syncSubscription() => _apiClient.syncSubscription();

  /// TEMPORARY — gifts Premium without charging. Remove when Stripe is live.
  Future<Map<String, dynamic>> mockActivatePremium({required String billingPeriod}) =>
      _apiClient.mockActivatePremium(billingPeriod: billingPeriod);

  Future<Map<String, dynamic>> cancelSubscription() => _apiClient.cancelSubscription();

  Future<Map<String, dynamic>> submitResponseReport({
    required int messageId,
    required String reason,
    required String sessionId,
    String details = '',
  }) {
    return _apiClient.submitResponseReport(
      messageId: messageId,
      reason: reason,
      sessionId: sessionId,
      details: details,
    );
  }

  Future<List<ResponseReportItem>> listResponseReports({String? status}) {
    return _apiClient.listResponseReports(status: status);
  }

  Future<ResponseReportItem> updateResponseReport(
    int id, {
    String? status,
    String? staffNotes,
  }) {
    return _apiClient.updateResponseReport(
      id,
      status: status,
      staffNotes: staffNotes,
    );
  }

  Future<List<MediaItem>> listMediaVideos() async {
    final rows = await _apiClient.listMediaVideos();
    return rows.map(MediaItem.fromApiJson).toList();
  }
}
