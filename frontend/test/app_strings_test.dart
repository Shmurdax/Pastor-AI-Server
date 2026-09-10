import 'package:flutter_application_1/l10n/app_locale.dart';
import 'package:flutter_application_1/l10n/app_strings.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('Spanish strings translate key chrome', () {
    final s = AppStrings('es');
    expect(s.home, 'Inicio');
    expect(s.sermonLibrary, 'Biblioteca de sermones');
    expect(s.howCanIHelp, '¿En qué puedo ayudarte?');
    expect(s.newChat, 'Nuevo chat');
  });

  test('Unknown language falls back to English', () {
    final s = AppStrings('xx');
    expect(s.home, 'Home');
    expect(s.sermonLibrary, 'Sermon Library');
  });

  test('sermonSourcesCount interpolates the source count', () {
    expect(AppStrings('en').sermonSourcesCount(3), 'Sermon sources (3)');
    expect(AppStrings('es').sermonSourcesCount(2), 'Fuentes del sermón (2)');
  });

  test('appLanguageByCode accepts locale prefixes', () {
    expect(appLanguageByCode('es-MX').code, 'es');
    expect(appLanguageByCode('zh_CN').code, 'zh');
    expect(appLanguageByCode('unknown').code, 'en');
  });

  test('all supported languages have full English key coverage', () {
    final enKeys = AppStrings('en');
    for (final lang in kSupportedAppLanguages) {
      final s = AppStrings(lang.code);
      expect(s.home.isNotEmpty, isTrue, reason: lang.code);
      expect(s.sermonLibrary.isNotEmpty, isTrue, reason: lang.code);
      expect(s.welcomeTitle.isNotEmpty, isTrue, reason: lang.code);
      expect(s.deleteChatBody('X').contains('X'), isTrue, reason: lang.code);
      // smoke: not accidentally returning the key name
      expect(s.home, isNot('home'));
      expect(enKeys.home, 'Home');
    }
  });
}
