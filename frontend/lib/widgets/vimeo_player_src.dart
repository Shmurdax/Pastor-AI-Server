/// Same player URL the admin sermon-sources page uses (`vimeo_embed_url` + `dnt=1`).
///
/// Optional [startSeconds] appends Vimeo's `#t=` media fragment so playback
/// begins near a cited sermon timestamp (e.g. `#t=530s` for 08:50).
String vimeoPlayerSrc(
  String vimeoId, {
  String? privacyHash,
  int? startSeconds,
}) {
  final id = vimeoId.trim();
  final hash = (privacyHash ?? '').trim();
  final base = Uri(
    scheme: 'https',
    host: 'player.vimeo.com',
    path: '/video/$id',
    queryParameters: <String, String>{
      if (hash.isNotEmpty) 'h': hash,
      'dnt': '1',
    },
  );
  final seek = startSeconds;
  if (seek == null || seek < 0) {
    return base.toString();
  }
  return base.replace(fragment: 't=${seek}s').toString();
}
