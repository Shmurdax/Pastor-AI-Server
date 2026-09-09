import 'dart:convert';

import 'package:flutter_application_1/services/api_client.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

class _FailingClient extends http.BaseClient {
  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) {
    return Future.error(Exception('offline'));
  }
}

class _CaptureClient extends http.BaseClient {
  static String? lastPath;
  static String? lastMethod;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    lastPath = request.url.path;
    lastMethod = request.method;
    return http.StreamedResponse(
      Stream<List<int>>.fromIterable([utf8.encode('{"ok":true}')]),
      200,
      headers: {'content-type': 'application/json'},
    );
  }
}

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

  test('warmupChat posts to /api/chat/warmup/ and swallows errors', () async {
    final api = ApiClient(client: _CaptureClient());
    await api.warmupChat();
    expect(_CaptureClient.lastPath, '/api/chat/warmup/');
    expect(_CaptureClient.lastMethod, 'POST');

    final failing = ApiClient(client: _FailingClient());
    await failing.warmupChat();
  });

  test('chatStream stops painting tokens after isCancelled', () async {
    const payload =
        'data: {"type":"delta","text":"Faith "}\n\n'
        'data: {"type":"delta","text":"grows"}\n\n'
        'data: {"type":"done","answer":"Faith grows","sources":[]}\n\n';
    final api = ApiClient(client: _ScriptedStreamClient(payload));
    final deltas = <String>[];
    var cancelled = false;

    final result = await api.chatStream(
      query: 'What is faith?',
      sessionId: 's1',
      onDelta: (text) {
        deltas.add(text);
        cancelled = true;
      },
      isCancelled: () => cancelled,
    );

    expect(deltas, ['Faith ']);
    expect(result['cancelled'], isTrue);
    expect(result['answer'], 'Faith ');
  });
}
