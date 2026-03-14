// import 'dart:convert';
// import 'package:http/http.dart' as http;

// class ApiService {
//   // Use a relative path for your Nginx web deployment
//   final String baseUrl = "http://123.456.78.90:8001/api/chat/";

//   Future<Map<String, dynamic>> sendMessage(String query, String sessionId) async {
//     final response = await http.post(
//       Uri.parse(baseUrl),
//       headers: {"Content-Type": "application/json"},
//       body: jsonEncode({"query": query, "session_id": sessionId}),
//     );

//     if (response.statusCode == 200) {
//       return jsonDecode(response.body);
//     } else {
//       throw Exception("Failed to reach Pastor-AI server");
//     }
//   }
// }

import 'dart:convert';
import 'package:http/http.dart' as http;

class ApiService {
  // Tip: Ensure this matches the IP your server is listening on!
  final String baseUrl = "http://10.60.170.73:8001/api/chat/";

  Future<Map<String, dynamic>> sendMessage(String query, String sessionId) async {
    try {
      final response = await http.post(
        Uri.parse(baseUrl),
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json", // Forces Django to send JSON, not HTML
        },
        body: jsonEncode({
          "query": query, 
          "session_id": sessionId
        }),
      );

      if (response.statusCode == 200) {
        // This now contains {'answer': '...', 'sources': [...]}
        return jsonDecode(response.body);
      } else {
        // Helpful for debugging: prints the actual error status
        print("Server Error: ${response.statusCode}");
        print("Response body: ${response.body}");
        throw Exception("Server returned code ${response.statusCode}");
      }
    } catch (e) {
      print("Connection Error: $e");
      throw Exception("Could not connect to Pastor-AI: $e");
    }
  }
}