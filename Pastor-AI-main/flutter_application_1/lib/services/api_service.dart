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
}
