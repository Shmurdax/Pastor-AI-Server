/// Distance from the end of the thread that still counts as "at the bottom".
const kChatStickToBottomThreshold = 64.0;

/// Follows a generating reply only while the user is already at the bottom.
///
/// Streaming used to jump the scroll view to the end on every token, which
/// cancelled in-progress drags and locked the viewport to the latest text.
/// Pause follow as soon as the user scrolls away (or starts dragging); resume
/// when they return to the bottom or tap Back to bottom.
class ChatStreamScrollPolicy {
  ChatStreamScrollPolicy({
    this.nearBottomThreshold = kChatStickToBottomThreshold,
  });

  final double nearBottomThreshold;

  bool stickToBottom = true;
  bool userDragging = false;

  bool get shouldFollowStream => stickToBottom && !userDragging;

  void onUserDragStart() {
    userDragging = true;
  }

  /// Mouse wheel / trackpad / drag toward earlier messages.
  void onUserScrollTowardStart() {
    stickToBottom = false;
  }

  /// Mouse wheel / trackpad / drag toward newer messages.
  void onUserScrollTowardEnd(double distanceFromBottom) {
    if (distanceFromBottom <= nearBottomThreshold) {
      stickToBottom = true;
    }
  }

  void onUserDragEnd(double distanceFromBottom) {
    final wasDragging = userDragging;
    userDragging = false;
    if (!wasDragging) return;
    if (distanceFromBottom > nearBottomThreshold) {
      stickToBottom = false;
    }
    // If they dragged back to the live end, [onUserScrollTowardEnd] already
    // restuck. A tiny drag away stays unstuck so the next token cannot yank.
  }

  void pinToBottom() {
    userDragging = false;
    stickToBottom = true;
  }
}
