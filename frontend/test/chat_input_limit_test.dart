import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_application_1/chat_input_limits.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/l10n/app_locale.dart';
import 'package:flutter_application_1/main.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUpAll(() {
    GoogleFonts.config.allowRuntimeFetching = false;
  });

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  test('clampChatInput keeps text at or under 1000 graphemes', () {
    expect(clampChatInput(''), '');
    expect(clampChatInput('hello'), 'hello');
    expect(clampChatInput('a' * kChatInputMaxLength).length, kChatInputMaxLength);

    final overLimit = 'a' * (kChatInputMaxLength + 50);
    final clamped = clampChatInput(overLimit);
    expect(chatInputLength(clamped), kChatInputMaxLength);
    expect(clamped, 'a' * kChatInputMaxLength);
  });

  test('clampChatInput counts emoji as one grapheme', () {
    final emojiOver = '🙂' * (kChatInputMaxLength + 3);
    final clamped = clampChatInput(emojiOver);
    expect(chatInputLength(clamped), kChatInputMaxLength);
    expect(clamped, '🙂' * kChatInputMaxLength);
  });

  testWidgets('chat composer enforces a 1000 character max and shows the count',
      (tester) async {
    tester.view.physicalSize = const Size(1280, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    await tester.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider(create: (_) => AuthController()),
          ChangeNotifierProvider(create: (_) => LocaleController()),
        ],
        child: const SermonBrainApp(),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    final fieldFinder = find.byKey(const ValueKey('chatInputField'));
    expect(fieldFinder, findsOneWidget);

    final field = tester.widget<TextField>(fieldFinder);
    expect(field.maxLength, kChatInputMaxLength);
    expect(
      field.inputFormatters,
      contains(isA<LengthLimitingTextInputFormatter>()),
    );

    await tester.enterText(fieldFinder, 'a' * (kChatInputMaxLength + 80));
    await tester.pump();

    expect(field.controller!.text, 'a' * kChatInputMaxLength);
    expect(
      find.byKey(const ValueKey('chatInputCharCount')),
      findsOneWidget,
    );
    expect(find.text('$kChatInputMaxLength / $kChatInputMaxLength'), findsOneWidget);
  });
}
