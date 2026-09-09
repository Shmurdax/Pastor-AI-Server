import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/l10n/app_locale.dart';
import 'package:flutter_application_1/screens/media_library_screen.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  test('media grid tiles keep most of their height for the 16:9 video', () {
    const viewportWidth = 1100.0;
    const crossAxisCount = 3;
    const horizontalPadding = 64.0;
    const spacing = 20.0;
    final ratio = mediaGridChildAspectRatio(
      viewportWidth: viewportWidth,
      crossAxisCount: crossAxisCount,
      horizontalPadding: horizontalPadding,
    );
    expect(ratio, greaterThan(1.15));
    expect(ratio, lessThan(1.55));

    final tileWidth =
        (viewportWidth - horizontalPadding - spacing * (crossAxisCount - 1)) /
        crossAxisCount;
    final tileHeight = tileWidth / ratio;
    final videoHeight = tileWidth * 9 / 16;
    expect(videoHeight / tileHeight, greaterThan(0.68));
  });

  test('narrow two-column tiles still leave only a thin caption strip', () {
    final ratio = mediaGridChildAspectRatio(
      viewportWidth: 800,
      crossAxisCount: 2,
      horizontalPadding: 64,
    );
    expect(ratio, greaterThan(1.1));
    expect(ratio, greaterThan(0.82));
  });

  testWidgets('premium media grid paints compact tiles without overflow', (tester) async {
    TestWidgetsFlutterBinding.ensureInitialized();
    GoogleFonts.config.allowRuntimeFetching = false;
    SharedPreferences.setMockInitialValues({});
    tester.view.physicalSize = const Size(1100, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    final auth = AuthController();
    auth.token = 'test-token';
    auth.user = const AuthUser(
      id: '1',
      email: 'premium@test.com',
      name: 'Premium',
      isPremium: true,
    );

    await tester.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider<AuthController>.value(value: auth),
          ChangeNotifierProvider(create: (_) => LocaleController()),
        ],
        child: const MaterialApp(home: MediaLibraryScreen()),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));

    expect(tester.takeException(), isNull);
    expect(find.text('Welcome to Media'), findsOneWidget);
    expect(find.text('Morning Devotional — Faith Over Fear'), findsOneWidget);
  });
}
