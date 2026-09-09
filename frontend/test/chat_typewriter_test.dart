import 'package:flutter_application_1/chat_typewriter.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('nextRevealChunk prefers a nearby word boundary', () {
    expect(nextRevealChunk('Faith grows daily', 5), 'Faith ');
    expect(nextRevealChunk('Hi', 12), 'Hi');
    expect(nextRevealChunk('', 12), '');
  });

  testWidgets('typewriter paints a dumped paragraph in several ticks', (tester) async {
    final paints = <String>[];
    final typewriter = ChatTypewriter(
      onReveal: paints.add,
      charsPerTick: 6,
      tick: const Duration(milliseconds: 20),
    );

    typewriter.add('Faith comes by hearing the word.');
    await tester.pump();
    expect(paints, isEmpty);

    await tester.pump(const Duration(milliseconds: 20));
    expect(paints, isNotEmpty);
    expect(paints.last.length, lessThan('Faith comes by hearing the word.'.length));

    await tester.pump(const Duration(milliseconds: 400));
    expect(paints.last, 'Faith comes by hearing the word.');
    typewriter.dispose();
  });

  testWidgets('waitUntilDrained completes after the last tick', (tester) async {
    final paints = <String>[];
    final typewriter = ChatTypewriter(
      onReveal: paints.add,
      charsPerTick: 8,
      tick: const Duration(milliseconds: 16),
    );

    typewriter.add('Hello there friend');
    final drained = typewriter.waitUntilDrained();
    await tester.pump(const Duration(milliseconds: 200));
    await drained;
    expect(paints.last, 'Hello there friend');
    typewriter.dispose();
  });

  testWidgets('flush paints remaining text immediately', (tester) async {
    final paints = <String>[];
    final typewriter = ChatTypewriter(
      onReveal: paints.add,
      charsPerTick: 4,
      tick: const Duration(milliseconds: 50),
    );

    typewriter.add('ABCDEFGHIJKL');
    await tester.pump(const Duration(milliseconds: 50));
    expect(paints.last.length, lessThan(12));
    typewriter.flush();
    expect(paints.last, 'ABCDEFGHIJKL');
    typewriter.dispose();
  });
}
