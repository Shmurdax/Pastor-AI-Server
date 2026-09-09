import 'dart:async';

/// Prefer a word boundary shortly after [maxChars] so tokens stay readable.
String nextRevealChunk(String pending, int maxChars) {
  if (pending.isEmpty) return '';
  if (pending.length <= maxChars) return pending;
  final limit = maxChars.clamp(1, pending.length);
  final lookAheadEnd = (limit + 8).clamp(0, pending.length);
  final lookAhead = pending.substring(limit, lookAheadEnd);
  final space = lookAhead.indexOf(RegExp(r'\s'));
  if (space >= 0) return pending.substring(0, limit + space + 1);
  return pending.substring(0, limit);
}

/// Paints incoming chat text in small ticks so the bubble always grows.
class ChatTypewriter {
  ChatTypewriter({
    required this.onReveal,
    this.charsPerTick = 12,
    this.tick = const Duration(milliseconds: 24),
  });

  final void Function(String revealed) onReveal;
  final int charsPerTick;
  final Duration tick;

  String _pending = '';
  String revealed = '';
  Timer? _timer;
  Completer<void>? _drained;
  bool _closed = false;

  bool get hasPending => _pending.isNotEmpty;

  void add(String delta) {
    if (delta.isEmpty || _closed) return;
    _pending += delta;
    _ensureTimer();
  }

  Future<void> waitUntilDrained() async {
    if (_pending.isEmpty && _timer == null) return;
    _drained ??= Completer<void>();
    return _drained!.future;
  }

  void flush() {
    if (_pending.isNotEmpty) {
      revealed += _pending;
      _pending = '';
      onReveal(revealed);
    }
    _stopTimer();
    _completeDrained();
  }

  void reset() {
    _pending = '';
    revealed = '';
    _stopTimer();
    _completeDrained();
  }

  void dispose() {
    _closed = true;
    _stopTimer();
    _completeDrained();
  }

  void _ensureTimer() {
    _timer ??= Timer.periodic(tick, (_) => _tick());
  }

  void _tick() {
    if (_pending.isEmpty) {
      _stopTimer();
      _completeDrained();
      return;
    }
    final take = nextRevealChunk(_pending, charsPerTick);
    revealed += take;
    _pending = _pending.substring(take.length);
    onReveal(revealed);
    if (_pending.isEmpty) {
      _stopTimer();
      _completeDrained();
    }
  }

  void _stopTimer() {
    _timer?.cancel();
    _timer = null;
  }

  void _completeDrained() {
    final pending = _drained;
    _drained = null;
    if (pending != null && !pending.isCompleted) {
      pending.complete();
    }
  }
}
