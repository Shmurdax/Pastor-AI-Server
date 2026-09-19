import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:flutter_application_1/widgets/account_profile_chip.dart';
import 'package:flutter_application_1/widgets/brand_gradient.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUpAll(() {
    GoogleFonts.config.allowRuntimeFetching = false;
  });

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('profile sheet keeps Media library and omits View plans', (tester) async {
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
    expect(find.text('View plans'), findsNothing);
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

  testWidgets('staff profile sheet uses brand-gradient prayer and report boxes', (tester) async {
    final auth = AuthController();
    auth.user = const AuthUser(
      id: '9',
      email: 'pastor@test.com',
      name: 'Pastor Don',
      isStaff: true,
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

    expect(find.text('Prayer inbox'), findsOneWidget);
    expect(find.text('Response reports'), findsOneWidget);
    expect(find.byType(BrandGradientFilledButton), findsNWidgets(2));
  });
}
