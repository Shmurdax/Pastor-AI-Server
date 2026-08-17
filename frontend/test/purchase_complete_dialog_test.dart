import 'package:flutter/material.dart';
import 'package:flutter_application_1/widgets/purchase_complete_dialog.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';

void main() {
  setUpAll(() {
    GoogleFonts.config.allowRuntimeFetching = false;
  });

  testWidgets('purchase complete dialog is only shown when requested', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) {
            return Scaffold(
              body: Column(
                children: [
                  const Text('Checkout'),
                  FilledButton(
                    onPressed: () => showPurchaseCompleteDialog(context),
                    child: const Text('Complete purchase'),
                  ),
                ],
              ),
            );
          },
        ),
      ),
    );

    expect(find.text('Purchase complete'), findsNothing);
    expect(find.text('Checkout'), findsOneWidget);

    await tester.tap(find.text('Complete purchase'));
    await tester.pumpAndSettle();

    expect(find.text('Purchase complete'), findsOneWidget);
    expect(find.text('Back to chatbot'), findsOneWidget);

    await tester.tap(find.text('Back to chatbot'));
    await tester.pumpAndSettle();

    expect(find.text('Purchase complete'), findsNothing);
    expect(find.text('Checkout'), findsOneWidget);
  });

  testWidgets('closing the dialog pops back to the chatbot route', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: const Scaffold(body: Text('Chatbot')),
      ),
    );

    final navigator = tester.state<NavigatorState>(find.byType(Navigator));
    navigator.push(
      MaterialPageRoute<void>(
        builder: (context) => Scaffold(
          body: FilledButton(
            onPressed: () async {
              await showPurchaseCompleteDialog(context);
              if (context.mounted) {
                Navigator.of(context).popUntil((route) => route.isFirst);
              }
            },
            child: const Text('Finish purchase'),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Chatbot'), findsNothing);
    await tester.tap(find.text('Finish purchase'));
    await tester.pumpAndSettle();
    expect(find.text('Purchase complete'), findsOneWidget);

    await tester.tap(find.text('Back to chatbot'));
    await tester.pumpAndSettle();

    expect(find.text('Purchase complete'), findsNothing);
    expect(find.text('Finish purchase'), findsNothing);
    expect(find.text('Chatbot'), findsOneWidget);
  });
}
