import 'package:fetch_client/fetch_client.dart';
import 'package:http/http.dart' as http;

/// Flutter web's default [http.Client] uses XHR, which buffers the entire
/// response. Fetch + ReadableStream delivers SSE tokens as they arrive.
http.Client createHttpClient() {
  return FetchClient(
    mode: RequestMode.cors,
    credentials: RequestCredentials.sameOrigin,
    cache: RequestCache.noStore,
  );
}
