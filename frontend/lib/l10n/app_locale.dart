import 'package:flutter/foundation.dart';
import 'package:flutter_application_1/l10n/app_strings.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Supported UI + chat reply languages for the display page.
class AppLanguage {
  const AppLanguage({
    required this.code,
    required this.nativeName,
    required this.englishName,
    required this.speechLocaleId,
  });

  final String code;
  final String nativeName;
  final String englishName;
  /// BCP-47-ish id for [speech_to_text] (e.g. `es_ES`).
  final String speechLocaleId;

  String get label => nativeName == englishName ? nativeName : '$nativeName ($englishName)';
}

const kSupportedAppLanguages = <AppLanguage>[
  AppLanguage(
    code: 'en',
    nativeName: 'English',
    englishName: 'English',
    speechLocaleId: 'en_US',
  ),
  AppLanguage(
    code: 'es',
    nativeName: 'Español',
    englishName: 'Spanish',
    speechLocaleId: 'es_ES',
  ),
  AppLanguage(
    code: 'fr',
    nativeName: 'Français',
    englishName: 'French',
    speechLocaleId: 'fr_FR',
  ),
  AppLanguage(
    code: 'pt',
    nativeName: 'Português',
    englishName: 'Portuguese',
    speechLocaleId: 'pt_BR',
  ),
  AppLanguage(
    code: 'de',
    nativeName: 'Deutsch',
    englishName: 'German',
    speechLocaleId: 'de_DE',
  ),
  AppLanguage(
    code: 'ko',
    nativeName: '한국어',
    englishName: 'Korean',
    speechLocaleId: 'ko_KR',
  ),
  AppLanguage(
    code: 'zh',
    nativeName: '中文',
    englishName: 'Chinese',
    speechLocaleId: 'zh_CN',
  ),
];

AppLanguage appLanguageByCode(String? code) {
  final normalized = (code ?? 'en').trim().toLowerCase();
  for (final lang in kSupportedAppLanguages) {
    if (lang.code == normalized) return lang;
  }
  // Accept BCP-47 prefixes like `es-MX` / `zh-Hans`.
  final short = normalized.split(RegExp(r'[-_]')).first;
  for (final lang in kSupportedAppLanguages) {
    if (lang.code == short) return lang;
  }
  return kSupportedAppLanguages.first;
}

class LocaleController extends ChangeNotifier {
  LocaleController({String initialCode = 'en'})
      : _language = appLanguageByCode(initialCode);

  static const _prefsKey = 'app_display_language';

  AppLanguage _language;
  bool _loaded = false;

  AppLanguage get language => _language;
  String get languageCode => _language.code;
  AppStrings get strings => AppStrings(_language.code);
  bool get isLoaded => _loaded;

  Future<void> load() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final saved = prefs.getString(_prefsKey);
      if (saved != null && saved.isNotEmpty) {
        _language = appLanguageByCode(saved);
      }
    } catch (e) {
      debugPrint('LocaleController.load failed: $e');
    } finally {
      _loaded = true;
      notifyListeners();
    }
  }

  Future<void> setLanguageCode(String code) async {
    final next = appLanguageByCode(code);
    if (next.code == _language.code) return;
    _language = next;
    notifyListeners();
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_prefsKey, next.code);
    } catch (e) {
      debugPrint('LocaleController.setLanguageCode persist failed: $e');
    }
  }
}
