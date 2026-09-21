import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_application_1/widgets/chat_response_action_button.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  Future<void> pumpButton(
    WidgetTester tester, {
    required ValueNotifier<int> rebuilds,
  }) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Center(
            child: ValueListenableBuilder<int>(
              valueListenable: rebuilds,
              builder: (context, _, __) {
                return ChatResponseActionButton(
                  icon: Icons.copy_rounded,
                  tooltip: 'Copy to clipboard',
                  onTap: () {},
                );
              },
            ),
          ),
        ),
      ),
    );
  }

  List<BoxShadow>? hoverShadows() {
    final container = find.byKey(const ValueKey('chatResponseActionHover'));
    final widget = container.evaluate().single.widget as AnimatedContainer;
    final decoration = widget.decoration as BoxDecoration?;
    return decoration?.boxShadow;
  }

  testWidgets('hover highlight stays after the parent rebuilds', (tester) async {
    final rebuilds = ValueNotifier<int>(0);
    addTearDown(rebuilds.dispose);
    await pumpButton(tester, rebuilds: rebuilds);

    final gesture = await tester.createGesture(kind: PointerDeviceKind.mouse);
    await gesture.addPointer(location: Offset.zero);
    addTearDown(gesture.removePointer);
    await tester.pump();

    expect(hoverShadows(), isEmpty);

    await gesture.moveTo(tester.getCenter(find.byIcon(Icons.copy_rounded)));
    await tester.pump();
    expect(tester.state<ChatResponseActionButtonState>(
      find.byType(ChatResponseActionButton),
    ).hovered, isTrue);
    expect(hoverShadows(), isNotEmpty);

    rebuilds.value++;
    await tester.pump();

    expect(tester.state<ChatResponseActionButtonState>(
      find.byType(ChatResponseActionButton),
    ).hovered, isTrue);
    expect(hoverShadows(), isNotEmpty);
  });

  testWidgets('hover highlight clears when the pointer leaves', (tester) async {
    final rebuilds = ValueNotifier<int>(0);
    addTearDown(rebuilds.dispose);
    await pumpButton(tester, rebuilds: rebuilds);

    final gesture = await tester.createGesture(kind: PointerDeviceKind.mouse);
    await gesture.addPointer(location: Offset.zero);
    addTearDown(gesture.removePointer);
    await tester.pump();

    await gesture.moveTo(tester.getCenter(find.byIcon(Icons.copy_rounded)));
    await tester.pump();
    expect(hoverShadows(), isNotEmpty);

    await gesture.moveTo(const Offset(0, 0));
    await tester.pump();
    expect(tester.state<ChatResponseActionButtonState>(
      find.byType(ChatResponseActionButton),
    ).hovered, isFalse);
    expect(hoverShadows(), isEmpty);
  });
}
