/// Same player URL the admin sermon-sources page uses (`vimeo_embed_url` + `dnt=1`).
String vimeoPlayerSrc(String vimeoId, {String? privacyHash}) {
  final id = vimeoId.trim();
  final hash = (privacyHash ?? '').trim();
  return Uri(
    scheme: 'https',
    host: 'player.vimeo.com',
    path: '/video/$id',
    queryParameters: <String, String>{
      if (hash.isNotEmpty) 'h': hash,
      'dnt': '1',
    },
  ).toString();
}
