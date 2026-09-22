import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/l10n/app_locale.dart';
import 'package:flutter_application_1/screens/settings_screen.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:flutter_application_1/widgets/account_profile_chip.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _FakeAuthService extends AuthService {
  String? lastPasswordCurrent;
  String? lastPasswordNew;
  String? lastName;
  String? lastEmail;
  String? lastEmailPassword;
  Object? throwOnChange;

  @override
  Future<void> changePassword({
    required String token,
    required String currentPassword,
    required String newPassword,
  }) async {
    if (throwOnChange != null) throw throwOnChange!;
    lastPasswordCurrent = currentPassword;
    lastPasswordNew = newPassword;
  }

  @override
  Future<AuthUser> changeName({
    required String token,
    required String name,
  }) async {
    if (throwOnChange != null) throw throwOnChange!;
    lastName = name;
    return AuthUser(
      id: '1',
      email: 'member@test.com',
      name: name,
      isPremium: true,
      subscriptionStatus: 'active',
      hasUsablePassword: true,
    );
  }

  @override
  Future<AuthUser> changeEmail({
    required String token,
    required String email,
    required String currentPassword,
  }) async {
    if (throwOnChange != null) throw throwOnChange!;
    lastEmail = email;
    lastEmailPassword = currentPassword;
    return AuthUser(
      id: '1',
      email: email,
      name: 'Jane Member',
      isPremium: true,
      subscriptionStatus: 'active',
      hasUsablePassword: true,
      emailVerified: false,
    );
  }
}

AuthController _readyAuth(AuthUser user) {
  final auth = _TestAuthController();
  auth.user = user;
  auth.token = 'tok';
  auth.sessionReady = true;
  return auth;
}

/// Avoid FlutterSecureStorage in widget tests when applying profile updates.
class _TestAuthController extends AuthController {
  _TestAuthController() : super(restoreSession: false);

  @override
  Future<void> applyUser(AuthUser next) async {
    user = next;
    notifyListeners();
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUpAll(() {
    GoogleFonts.config.allowRuntimeFetching = false;
  });

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('settings edits name without password and email with password', (tester) async {
    tester.view.physicalSize = const Size(800, 1800);
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
      MultiProvider(
        providers: [
          ChangeNotifierProvider<AuthController>.value(value: auth),
          ChangeNotifierProvider(create: (_) => LocaleController()),
        ],
        child: MaterialApp(
          home: SettingsScreen(
            apiService: ApiService(),
            authService: fakeAuth,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Jane Member'), findsOneWidget);
    expect(find.text('member@test.com'), findsOneWidget);
    expect(find.byKey(const Key('edit-name')), findsOneWidget);
    expect(find.byKey(const Key('edit-email')), findsOneWidget);
    expect(find.byKey(const Key('edit-password')), findsOneWidget);
    expect(find.text('Update name'), findsNothing);
    expect(find.text('Update email'), findsNothing);
    expect(find.text('Update password'), findsNothing);

    await tester.tap(find.byKey(const Key('edit-name')));
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextFormField, 'Name'), 'Jane Updated');
    await tester.tap(find.text('Update name'));
    await tester.pumpAndSettle();

    expect(fakeAuth.lastName, 'Jane Updated');
    expect(find.text('Name updated.'), findsOneWidget);
    expect(auth.user?.name, 'Jane Updated');

    await tester.tap(find.byKey(const Key('edit-email')));
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextFormField, 'New email'), 'jane.new@test.com');
    await tester.enterText(
      find.widgetWithText(TextFormField, 'Current password'),
      'MemberPass123!',
    );
    await tester.tap(find.text('Update email'));
    await tester.pumpAndSettle();

    expect(fakeAuth.lastEmail, 'jane.new@test.com');
    expect(fakeAuth.lastEmailPassword, 'MemberPass123!');
    expect(find.text('Email updated.'), findsOneWidget);
    expect(auth.user?.email, 'jane.new@test.com');

    await tester.tap(find.byKey(const Key('edit-password')));
    await tester.pumpAndSettle();
    final passwordFields = find.byType(TextFormField);
    // Current, new, confirm — after email form closed, 3 password fields.
    expect(passwordFields, findsNWidgets(3));
    await tester.enterText(passwordFields.at(0), 'OldPass123!');
    await tester.enterText(passwordFields.at(1), 'NewPass123!');
    await tester.enterText(passwordFields.at(2), 'NewPass123!');
    await tester.tap(find.text('Update password'));
    await tester.pumpAndSettle();

    expect(fakeAuth.lastPasswordCurrent, 'OldPass123!');
    expect(fakeAuth.lastPasswordNew, 'NewPass123!');
    expect(find.text('Password updated.'), findsOneWidget);
  });

  testWidgets('google-only accounts can edit name but not email or password', (tester) async {
    tester.view.physicalSize = const Size(800, 1400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    final auth = _readyAuth(
      const AuthUser(
        id: '2',
        email: 'google@test.com',
        name: 'Google User',
        hasUsablePassword: false,
      ),
    );

    await tester.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider<AuthController>.value(value: auth),
          ChangeNotifierProvider(create: (_) => LocaleController()),
        ],
        child: MaterialApp(
          home: SettingsScreen(apiService: ApiService()),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('edit-name')), findsOneWidget);
    expect(find.byKey(const Key('edit-email')), findsNothing);
    expect(find.byKey(const Key('edit-password')), findsNothing);
    expect(find.textContaining('signed in with Google'), findsWidgets);
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
      MultiProvider(
        providers: [
          ChangeNotifierProvider<AuthController>.value(value: auth),
          ChangeNotifierProvider(create: (_) => LocaleController()),
        ],
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
    expect(find.text('Account'), findsOneWidget);
    expect(find.text('Language'), findsOneWidget);
    expect(find.text('Subscription'), findsOneWidget);
    expect(find.text('Name'), findsOneWidget);
    expect(find.text('Email'), findsOneWidget);
    expect(find.text('Password'), findsOneWidget);
  });

  testWidgets('settings language picker updates locale for the whole app', (tester) async {
    tester.view.physicalSize = const Size(800, 1800);
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
    final locale = LocaleController();

    await tester.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider<AuthController>.value(value: auth),
          ChangeNotifierProvider<LocaleController>.value(value: locale),
        ],
        child: MaterialApp(
          home: SettingsScreen(apiService: ApiService()),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Account'), findsOneWidget);
    expect(find.byKey(const Key('language-es')), findsOneWidget);

    await tester.tap(find.byKey(const Key('language-es')));
    await tester.pumpAndSettle();

    expect(locale.languageCode, 'es');
    expect(find.text('Cuenta'), findsOneWidget);
    expect(find.text('Idioma'), findsOneWidget);
    expect(find.text('Suscripción'), findsOneWidget);
  });
}