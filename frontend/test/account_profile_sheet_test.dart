import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:flutter_application_1/widgets/account_profile_chip.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('profile sheet lists Media library above View plans', (tester) async {
    final auth = AuthController();
    auth.user = const AuthUser(
      id: '1',
      email: 'member@test.com',
      name: 'Jane Member',
      isPremium: true,
      subscriptionStatus: 'active',
    );
    auth.token = 'test-token';

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

    expect(find.text('Media library'), findsOneWidget);
    expect(find.text('View plans'), findsOneWidget);
    expect(
      tester.getTopLeft(find.text('Media library')).dy,
      lessThan(tester.getTopLeft(find.text('View plans')).dy),
    );
    expect(find.text('Email members'), findsNothing);
  });

  testWidgets('staff profile sheet shows Email members', (tester) async {
    final auth = AuthController();
    auth.user = const AuthUser(
      id: '2',
      email: 'pastor@test.com',
      name: 'Pastor Don',
      isStaff: true,
      isPremium: true,
      subscriptionStatus: 'free',
    );
    auth.token = 'staff-token';

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

    expect(find.text('Prayer inbox'), findsOneWidget);
    expect(find.text('Email members'), findsOneWidget);
  });

  testWidgets('account chip is visible for a signed-in user', (tester) async {
    final auth = AuthController();
    auth.user = const AuthUser(
      id: '1',
      email: 'member@test.com',
      name: 'Jane Member',
      isPremium: true,
      subscriptionStatus: 'active',
    );
    auth.token = 'test-token';

    await tester.pumpWidget(
      ChangeNotifierProvider<AuthController>.value(
        value: auth,
        child: MaterialApp(
          home: Scaffold(
            appBar: AppBar(
              actions: [
                AccountProfileChip(apiService: ApiService()),
              ],
            ),
          ),
        ),
      ),
    );

    expect(find.byType(AccountProfileChip), findsOneWidget);
    expect(find.text('Jane'), findsOneWidget);
  });
}
