/// Stripe sends subscribers back with `?billing=success&session_id=...`.
/// Those params must not stay in the address bar, or a refresh replays the
/// post-checkout return flow.
Uri uriWithoutBillingReturn(Uri uri) {
  if (!uri.queryParameters.containsKey('billing') &&
      !uri.queryParameters.containsKey('session_id')) {
    return uri;
  }
  final params = Map<String, String>.from(uri.queryParameters)
    ..remove('billing')
    ..remove('session_id');
  // An empty queryParameters map still stringifies as "?", so omit the query
  // entirely when nothing else remains.
  return Uri(
    scheme: uri.scheme,
    userInfo: uri.userInfo,
    host: uri.host,
    port: uri.hasPort ? uri.port : null,
    path: uri.path,
    queryParameters: params.isEmpty ? null : params,
    fragment: uri.hasFragment ? uri.fragment : null,
  );
}
