/// Drop leaked CJK from a visible chat reply when the UI is not Chinese.
String sanitizeVisibleChatText(String text, {required String language}) {
  final raw = text;
  if (raw.isEmpty) return raw;
  final lang = language.trim().toLowerCase();
  if (lang == 'zh' || lang.startsWith('zh-')) return raw;

  var cleaned = raw.replaceAll(RegExp(r'[\u3400-\u9fff\uf900-\ufaff]+'), '');
  cleaned = cleaned.replaceAll(RegExp(r'[\u3000-\u303f\uff00-\uffef]+'), '');
  if (lang != 'ko' && !lang.startsWith('ko-')) {
    cleaned = cleaned.replaceAll(RegExp(r'[\uac00-\ud7af]+'), '');
  }
  cleaned = cleaned.replaceAll(RegExp(r'[\u3040-\u30ff]+'), '');
  cleaned = cleaned.replaceAll(RegExp(r'[ \t]+\n'), '\n');
  cleaned = cleaned.replaceAll(RegExp(r'\n{3,}'), '\n\n');
  return cleaned.trimRight();
}

bool hasUnexpectedCjk(String text, {required String language}) {
  final lang = language.trim().toLowerCase();
  if (lang == 'zh' || lang.startsWith('zh-')) return false;
  if (RegExp(r'[\u3400-\u9fff\uf900-\ufaff]').hasMatch(text)) return true;
  if (lang != 'ko' && !lang.startsWith('ko-')) {
    if (RegExp(r'[\uac00-\ud7af]').hasMatch(text)) return true;
  }
  return RegExp(r'[\u3040-\u30ff]').hasMatch(text);
}
