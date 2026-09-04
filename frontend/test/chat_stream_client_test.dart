import 'dart:convert';

import 'package:flutter_application_1/services/api_client.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

class _ScriptedStreamClient extends http.BaseClient {
  _ScriptedStreamClient(this.body, {this.contentType = 'text/event-stream'});

  final String body;
  final String contentType;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    return http.StreamedResponse(
      Stream<List<int>>.fromIterable([utf8.encode(body)]),
      200,
      headers: {'content-type': contentType},
    );
  }
}

void main() {
  test('chatStream applies deltas as the server generates them', () async {
    const payload =
        'data: {"type":"delta","text":"Faith "}\n\n'
        'data: {"type":"delta","text":"grows"}\n\n'
        'data: {"type":"done","answer":"Faith grows","sources":["Hebrews 11"],"message_id":4}\n\n';
    final api = ApiClient(client: _ScriptedStreamClient(payload));
    final deltas = <String>[];

    final result = await api.chatStream(
      query: 'What is faith?',
      sessionId: 's1',
      onDelta: deltas.add,
    );

    expect(deltas, ['Faith ', 'grows']);
    expect(result['answer'], 'Faith grows');
    expect(result['sources'], ['Hebrews 11']);
    expect(result['message_id'], 4);
  });

  test('chatStream falls back to a full JSON body', () async {
    final api = ApiClient(
      client: _ScriptedStreamClient(
        jsonEncode({'answer': 'Grace first', 'sources': []}),
        contentType: 'application/json',
      ),
    );
    final deltas = <String>[];
    final result = await api.chatStream(
      query: 'q',
      sessionId: 's',
      onDelta: deltas.add,
    );
    expect(deltas, ['Grace first']);
    expect(result['answer'], 'Grace first');
  });
}
