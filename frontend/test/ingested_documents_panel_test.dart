import 'package:flutter/material.dart';
import 'package:flutter_application_1/l10n/app_strings.dart';
import 'package:flutter_application_1/models/ingested_document.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_application_1/widgets/ingested_documents_panel.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUpAll(() {
    GoogleFonts.config.allowRuntimeFetching = false;
  });

  testWidgets('catalog lists PDFs, filters search, and opens on tap', (tester) async {
    IngestedDocumentItem? opened;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SizedBox(
            width: 360,
            height: 640,
            child: IngestedDocumentsPanel(
              apiService: ApiService(),
              strings: AppStrings('en'),
              onClose: () {},
              onOpenDocument: (doc) => opened = doc,
              documentsLoader: () async => const [
                IngestedDocumentItem(
                  id: 1,
                  title: 'Hope In Christ',
                  viewOnly: false,
                  scriptureRefs: ['John 3:16'],
                ),
                IngestedDocumentItem(
                  id: 2,
                  title: 'Book Transcript',
                  viewOnly: true,
                ),
              ],
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('All documents'), findsOneWidget);
    expect(find.text('Book Transcript'), findsOneWidget);
    expect(find.text('Hope In Christ'), findsOneWidget);
    expect(find.text('View only'), findsWidgets);
    expect(find.byType(RawScrollbar), findsOneWidget);
    expect(
      tester.getTopLeft(find.text('Book Transcript')).dy <
          tester.getTopLeft(find.text('Hope In Christ')).dy,
      isTrue,
    );

    await tester.enterText(find.byType(TextField), 'book');
    await tester.pumpAndSettle();
    expect(find.text('Book Transcript'), findsOneWidget);
    expect(find.text('Hope In Christ'), findsNothing);

    await tester.enterText(find.byType(TextField), 'John 3:16');
    await tester.pumpAndSettle();
    expect(find.text('Hope In Christ'), findsOneWidget);
    expect(find.text('Book Transcript'), findsNothing);
    expect(find.text('Mentions John 3:16'), findsOneWidget);

    await tester.tap(find.text('Hope In Christ'));
    expect(opened?.id, 1);
  });
}
