import 'package:flutter/material.dart';
import 'package:flutter_application_1/chat_stream_scroll.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('follows the stream until the user scrolls away', () {
    final policy = ChatStreamScrollPolicy();
    expect(policy.shouldFollowStream, isTrue);

    policy.onUserScrollTowardStart();
    expect(policy.stickToBottom, isFalse);
    expect(policy.shouldFollowStream, isFalse);
  });

  test('pauses follow for the whole drag so jumpTo cannot cancel it', () {
    final policy = ChatStreamScrollPolicy();
    policy.onUserDragStart();
    expect(policy.shouldFollowStream, isFalse);

    // Still near the bottom mid-drag — must not resume until the gesture ends.
    policy.onUserScrollTowardStart();
    expect(policy.shouldFollowStream, isFalse);

    policy.onUserDragEnd(400);
    expect(policy.userDragging, isFalse);
    expect(policy.stickToBottom, isFalse);
    expect(policy.shouldFollowStream, isFalse);
  });

  test('a short drag away stays unstuck after release', () {
    final policy = ChatStreamScrollPolicy();
    policy.onUserDragStart();
    policy.onUserScrollTowardStart();
    policy.onUserDragEnd(20);
    expect(policy.shouldFollowStream, isFalse);
  });

  test('resumes follow when the user returns to the bottom', () {
    final policy = ChatStreamScrollPolicy();
    policy.onUserScrollTowardStart();
    expect(policy.shouldFollowStream, isFalse);

    policy.onUserScrollTowardEnd(120);
    expect(policy.shouldFollowStream, isFalse);

    policy.onUserScrollTowardEnd(20);
    expect(policy.shouldFollowStream, isTrue);
  });

  test('resumes follow after dragging back to the bottom', () {
    final policy = ChatStreamScrollPolicy();
    policy.onUserScrollTowardStart();
    policy.onUserDragStart();
    policy.onUserScrollTowardEnd(10);
    policy.onUserDragEnd(10);
    expect(policy.shouldFollowStream, isTrue);
  });

  test('ScrollEnd without a drag does not restick a wheel scroll away', () {
    final policy = ChatStreamScrollPolicy();
    policy.onUserScrollTowardStart();
    policy.onUserDragEnd(10);
    expect(policy.shouldFollowStream, isFalse);
  });

  test('pinToBottom restores follow after the user scrolled away', () {
    final policy = ChatStreamScrollPolicy();
    policy.onUserDragStart();
    policy.onUserScrollTowardStart();
    policy.onUserDragEnd(800);

    policy.pinToBottom();
    expect(policy.userDragging, isFalse);
    expect(policy.shouldFollowStream, isTrue);
  });

  testWidgets('dragging up unsticks so later jumps cannot pin the list', (tester) async {
    final policy = ChatStreamScrollPolicy();
    final controller = ScrollController();
    addTearDown(controller.dispose);

    await tester.pumpWidget(
      MaterialApp(
        home: NotificationListener<ScrollNotification>(
          onNotification: (notification) {
            if (notification.depth != 0) return false;
            if (notification is ScrollStartNotification &&
                notification.dragDetails != null) {
              policy.onUserDragStart();
            } else if (notification is ScrollUpdateNotification) {
              final delta = notification.scrollDelta ?? 0;
              if (delta < 0) policy.onUserScrollTowardStart();
            } else if (notification is ScrollEndNotification) {
              policy.onUserDragEnd(
                notification.metrics.maxScrollExtent - notification.metrics.pixels,
              );
            }
            return false;
          },
          child: ListView.builder(
            controller: controller,
            itemCount: 40,
            itemBuilder: (_, i) => SizedBox(height: 80, child: Text('item $i')),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    controller.jumpTo(controller.position.maxScrollExtent);
    await tester.pump();
    expect(policy.shouldFollowStream, isTrue);

    await tester.drag(find.byType(ListView), const Offset(0, 400));
    await tester.pumpAndSettle();
    expect(policy.shouldFollowStream, isFalse);

    final offsetAfterUserScroll = controller.offset;
    if (policy.shouldFollowStream) {
      controller.jumpTo(controller.position.maxScrollExtent);
      await tester.pump();
    }
    expect(controller.offset, offsetAfterUserScroll);
  });
}
