import 'package:flutter/widgets.dart';

/// Cross-route hooks for nav actions that live on the main chat screen.
class ChatNavActions {
  static VoidCallback? openEvents;
}

/// Closes page-local panels when the user moves between full-screen routes.
///
/// Dialogs and bottom sheets are ignored. Listeners run after the navigation
/// frame so a panel that was open stays closed when the user comes back.
class AppPageNavigation {
  AppPageNavigation._();

  static final NavigatorObserver observer = _AppPageObserver();
  static final Set<VoidCallback> _listeners = <VoidCallback>{};

  static void addListener(VoidCallback listener) => _listeners.add(listener);

  static void removeListener(VoidCallback listener) =>
      _listeners.remove(listener);

  static void _notify() {
    final listeners = List<VoidCallback>.of(_listeners);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      for (final listener in listeners) {
        listener();
      }
    });
  }
}

class _AppPageObserver extends NavigatorObserver {
  bool _isPage(Route<dynamic>? route) => route is PageRoute;

  @override
  void didPush(Route<dynamic> route, Route<dynamic>? previousRoute) {
    if (previousRoute != null && _isPage(route)) {
      AppPageNavigation._notify();
    }
  }

  @override
  void didReplace({Route<dynamic>? newRoute, Route<dynamic>? oldRoute}) {
    if (_isPage(newRoute)) {
      AppPageNavigation._notify();
    }
  }

  @override
  void didPop(Route<dynamic> route, Route<dynamic>? previousRoute) {
    if (_isPage(route)) {
      AppPageNavigation._notify();
    }
  }
}
