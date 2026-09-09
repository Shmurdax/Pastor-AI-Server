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
}
