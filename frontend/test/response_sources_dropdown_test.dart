import 'package:flutter/material.dart';
import 'package:flutter_application_1/widgets/response_sources_dropdown.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';

void main() {
  setUpAll(() {
    GoogleFonts.config.allowRuntimeFetching = false;
  });

  Future<Size> pumpDropdown(
    WidgetTester tester, {
    required double parentWidth,
    required bool isMobile,
  }) async {
    tester.view.physicalSize = Size(parentWidth + 80, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Center(
            child: SizedBox(
              width: parentWidth,
              child: ResponseSourcesDropdown(
                sources: const ['Pregnant With a Promise'],
                isMobile: isMobile,
                title: 'Sermon sources (1)',
                onSourceTap: (_) {},
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    return tester.getSize(find.byType(ExpansionTile));
  }

  testWidgets('desktop sermon sources header is one-third of the bubble width', (tester) async {
    const parentWidth = 900.0;
    final tileSize = await pumpDropdown(tester, parentWidth: parentWidth, isMobile: false);
    expect(tileSize.width, closeTo(parentWidth / 3, 0.5));
  });

  testWidgets('mobile sermon sources header stays full bubble width', (tester) async {
    const parentWidth = 360.0;
    final tileSize = await pumpDropdown(tester, parentWidth: parentWidth, isMobile: true);
    expect(tileSize.width, closeTo(parentWidth, 0.5));
  });
}
