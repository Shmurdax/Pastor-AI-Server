import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/screens/settings_screen.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:flutter_application_1/widgets/account_profile_chip.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _FakeAuthService extends AuthService {
  String? lastCurrent;
  String? lastNew;
  Object? throwOnChange;

  @override
  Future<void> changePassword({
    required String token,
    required String currentPassword,
    required String newPassword,
  }) async {
    if (throwOnChange != null) throw throwOnChange!;
    lastCurrent = currentPassword;
    lastNew = newPassword;
  }
}

AuthController _readyAuth(AuthUser user) {
  final auth = AuthController(restoreSession: false);
  auth.user = user;
  auth.token = 'tok';
  auth.sessionReady = true;
  return auth;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUpAll(() {
    GoogleFonts.config.allowRuntimeFetching = false;
  });

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('settings shows password form for password accounts', (tester) async {
    tester.view.physicalSize = const Size(800, 1400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    final auth = _readyAuth(
      const AuthUser(
        id: '1',
        email: 'member@test.com',
        name: 'Jane Member',
        isPremium: true,
        subscriptionStatus: 'active',
        hasUsablePassword: true,
      ),
    );
    final fakeAuth = _FakeAuthService();

    await tester.pumpWidget(
      ChangeNotifierProvider<AuthController>.value(
        value: auth,
        child: MaterialApp(
          home: SettingsScreen(
            apiService: ApiService(),
            authService: fakeAuth,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Settings'), findsOneWidget);
    expect(find.text('Edit'), findsOneWidget);
    expect(find.text('Current password'), findsNothing);
    expect(find.text('Update password'), findsNothing);
    expect(find.text('Update payment method'), findsOneWidget);
    expect(find.text('Unsubscribe'), findsOneWidget);

    await tester.tap(find.text('Edit'));
    await tester.pumpAndSettle();

    expect(find.text('Current password'), findsOneWidget);
    expect(find.text('Update password'), findsOneWidget);
    expect(find.text('Cancel'), findsOneWidget);

    await tester.enterText(find.widgetWithText(TextFormField, 'Current password'), 'OldPass123!');
    await tester.enterText(find.widgetWithText(TextFormField, 'New password'), 'NewPass123!');
    await tester.enterText(find.widgetWithText(TextFormField, 'Confirm new password'), 'NewPass123!');
    await tester.tap(find.text('Update password'));
    await tester.pumpAndSettle();

    expect(fakeAuth.lastCurrent, 'OldPass123!');
    expect(fakeAuth.lastNew, 'NewPass123!');
    expect(find.text('Password updated.'), findsOneWidget);
    expect(find.text('Edit'), findsOneWidget);
    expect(find.text('Current password'), findsNothing);
  });

  testWidgets('google-only accounts see password unavailable message', (tester) async {
    final auth = _readyAuth(
      const AuthUser(
        id: '2',
        email: 'google@test.com',
        name: 'Google User',
        hasUsablePassword: false,
      ),
    );

    await tester.pumpWidget(
      ChangeNotifierProvider<AuthController>.value(
        value: auth,
        child: MaterialApp(
          home: SettingsScreen(apiService: ApiService()),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.textContaining('signed in with Google'), findsOneWidget);
    expect(find.text('Update password'), findsNothing);
    expect(find.text('Update payment method'), findsNothing);
    expect(find.text('Unsubscribe'), findsNothing);
  });

  testWidgets('profile sheet Settings opens settings screen', (tester) async {
    tester.view.physicalSize = const Size(800, 1400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    final auth = _readyAuth(
      const AuthUser(
        id: '1',
        email: 'member@test.com',
        name: 'Jane Member',
        isPremium: true,
        subscriptionStatus: 'active',
      ),
    );

    await tester.pumpWidget(
      ChangeNotifierProvider<AuthController>.value(
        value: auth,
        child: MaterialApp(
          home: Scaffold(
            body: Builder(
              builder: (context) => TextButton(
                onPressed: () => showAccountProfileSheet(
                  context,
                  apiService: ApiService(),
                ),
                child: const Text('Open profile'),
              ),
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.text('Open profile'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Settings'));
    await tester.pumpAndSettle();

    expect(find.byType(SettingsScreen), findsOneWidget);
    expect(find.text('Password'), findsOneWidget);
  });
}
