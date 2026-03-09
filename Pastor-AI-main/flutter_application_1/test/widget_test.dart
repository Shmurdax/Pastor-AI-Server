
import 'package:flutter_test/flutter_test.dart';
// Ensure this matches your project name/file
import 'package:flutter_application_1/main.dart'; 

void main() {
  testWidgets('Sermon Brain UI loads test', (WidgetTester tester) async {
    // 1. Build our app (Using the correct class name)
    await tester.pumpWidget(const SermonBrainApp());

    // 2. Verify the Disclaimer screen appears first
    expect(find.text('Important Notice'), findsOneWidget);
    expect(find.text('I Understand & Proceed'), findsOneWidget);

    // 3. Tap the consent button
    await tester.tap(find.text('I Understand & Proceed'));
    await tester.pumpAndSettle(); // Wait for the transition

    // 4. Verify we are now in the Chat Interface
    expect(find.text('Ask about a sermon...'), findsOneWidget);
  });
}