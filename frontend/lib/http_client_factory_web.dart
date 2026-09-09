import 'package:fetch_client/fetch_client.dart';
import 'package:http/http.dart' as http;

/// Flutter web's default [http.Client] uses XHR, which buffers the entire
/// response and often ignores [http.Client.close] until the body finishes.
/// Fetch + ReadableStream delivers SSE tokens as they arrive and aborts on close.
http.Client createHttpClient() {
  return FetchClient(
    mode: RequestMode.cors,
    credentials: RequestCredentials.sameOrigin,
    cache: RequestCache.noStore,
  );
}
