import 'dart:convert';
import 'package:http/http.dart' as http;

class ApiService {
  // Use a relative path for your Nginx web deployment
  final String baseUrl = "/api/chat/";

  Future<Map<String, dynamic>> sendMessage(String query, String sessionId) async {
    final response = await http.post(
      Uri.parse(baseUrl),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode({"query": query, "session_id": sessionId}),
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    } else {
      throw Exception("Failed to reach Pastor-AI server");
    }
  }
}