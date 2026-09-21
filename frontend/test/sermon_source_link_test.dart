import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_application_1/widgets/sermon_source_link.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';

void main() {
  setUpAll(() {
    GoogleFonts.config.allowRuntimeFetching = false;
  });

  Future<void> pumpLink(
    WidgetTester tester, {
    required ValueNotifier<int> rebuilds,
  }) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          backgroundColor: const Color(0xFF1B264F),
          body: Center(
            child: SizedBox(
              width: 320,
              child: ValueListenableBuilder<int>(
                valueListenable: rebuilds,
                builder: (context, _, __) {
                  return SermonSourceLink(
                    title: 'Pregnant With a Promise',
                    onTap: () {},
                  );
                },
              ),
            ),
          ),
        ),
      ),
    );
  }

  Color? hoverColor() {
    final container = find.byKey(const ValueKey('sermonSourceHover'));
    final widget = container.evaluate().single.widget as AnimatedContainer;
    final decoration = widget.decoration as BoxDecoration?;
    return decoration?.color;
  }

  testWidgets('sidebar sermon source hover stays after the parent rebuilds', (
    tester,
  ) async {
    final rebuilds = ValueNotifier<int>(0);
    addTearDown(rebuilds.dispose);
    await pumpLink(tester, rebuilds: rebuilds);

    final gesture = await tester.createGesture(kind: PointerDeviceKind.mouse);
    await gesture.addPointer(location: Offset.zero);
    addTearDown(gesture.removePointer);
    await tester.pump();

    expect(
      tester.state<SermonSourceLinkState>(find.byType(SermonSourceLink)).hovered,
      isFalse,
    );

    await gesture.moveTo(tester.getCenter(find.text('Pregnant With a Promise')));
    await tester.pump();
    expect(
      tester.state<SermonSourceLinkState>(find.byType(SermonSourceLink)).hovered,
      isTrue,
    );
    expect(hoverColor()!.a, greaterThan(0));

    rebuilds.value++;
    await tester.pump();

    expect(
      tester.state<SermonSourceLinkState>(find.byType(SermonSourceLink)).hovered,
      isTrue,
    );
    expect(hoverColor()!.a, greaterThan(0));
  });

  testWidgets('sidebar sermon source hover clears when the pointer leaves', (
    tester,
  ) async {
    final rebuilds = ValueNotifier<int>(0);
    addTearDown(rebuilds.dispose);
    await pumpLink(tester, rebuilds: rebuilds);

    final gesture = await tester.createGesture(kind: PointerDeviceKind.mouse);
    await gesture.addPointer(location: Offset.zero);
    addTearDown(gesture.removePointer);
    await tester.pump();

    await gesture.moveTo(tester.getCenter(find.text('Pregnant With a Promise')));
    await tester.pump();
    expect(
      tester.state<SermonSourceLinkState>(find.byType(SermonSourceLink)).hovered,
      isTrue,
    );

    await gesture.moveTo(const Offset(0, 0));
    await tester.pump();
    expect(
      tester.state<SermonSourceLinkState>(find.byType(SermonSourceLink)).hovered,
      isFalse,
    );
  });
}
