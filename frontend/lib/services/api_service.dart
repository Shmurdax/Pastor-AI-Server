import 'package:flutter_application_1/models/church_event.dart';
import 'package:flutter_application_1/models/prayer_request.dart';

import 'api_client.dart';

class ApiService {
  ApiService({ApiClient? apiClient}) : _apiClient = apiClient ?? ApiClient();
  final ApiClient _apiClient;

  void setAccessToken(String? token) => _apiClient.setAccessToken(token);

  Future<Map<String, dynamic>> sendMessage(
    String query,
    String sessionId, {
    bool regenerate = false,
  }) async {
    return _apiClient.chat(
      query: query,
      sessionId: sessionId,
      regenerate: regenerate,
    );
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

  /// TEMPORARY — gifts Premium without charging. Remove when Stripe is live.
  Future<Map<String, dynamic>> mockActivatePremium({required String billingPeriod}) =>
      _apiClient.mockActivatePremium(billingPeriod: billingPeriod);
}
