import 'package:characters/characters.dart';

/// Maximum Unicode grapheme clusters allowed in the chat composer.
const kChatInputMaxLength = 1000;

/// Show the live count once the composer is this close to the cap.
const kChatInputCounterThreshold = 800;

int chatInputLength(String text) => text.characters.length;

/// Truncates [text] to [kChatInputMaxLength] grapheme clusters.
String clampChatInput(String text) {
  final graphemes = text.characters;
  if (graphemes.length <= kChatInputMaxLength) return text;
  return graphemes.take(kChatInputMaxLength).toString();
}
