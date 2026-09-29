import 'package:flutter_application_1/widgets/church_events_nav_overlay.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('events panel is 4/5 of a phone and 500px on a tablet', () {
    expect(churchEventsOverlayWidth(390), 390 * 4 / 5);
    expect(churchEventsOverlayWidth(599), 599 * 4 / 5);
    expect(churchEventsOverlayWidth(600), 500);
    expect(churchEventsOverlayWidth(800), 500);
    expect(churchEventsOverlayWidth(1023), 500);
    expect(churchEventsOverlayWidth(1024), 300);
    expect(churchEventsOverlayWidth(1280), 300);

    expect(churchEventsOverlayCentered(390), isTrue);
    expect(churchEventsOverlayCentered(599), isTrue);
    expect(churchEventsOverlayCentered(600), isFalse);
    expect(churchEventsOverlayCentered(800), isFalse);
    expect(churchEventsOverlayCentered(1023), isFalse);
    expect(churchEventsOverlayCentered(1024), isFalse);
  });
}
