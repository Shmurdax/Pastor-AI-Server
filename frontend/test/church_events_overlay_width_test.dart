import 'package:flutter_application_1/widgets/church_events_nav_overlay.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('events panel is 4/5 of a phone and 3/4 of a tablet', () {
    expect(churchEventsOverlayWidth(390), 390 * 4 / 5);
    expect(churchEventsOverlayWidth(599), 599 * 4 / 5);
    expect(churchEventsOverlayWidth(600), 600 * 3 / 4);
    expect(churchEventsOverlayWidth(800), 800 * 3 / 4);
    expect(churchEventsOverlayWidth(1023), 1023 * 3 / 4);
    expect(churchEventsOverlayWidth(1024), 1024 * 0.3);
    expect(churchEventsOverlayWidth(1280), 1280 * 0.3);
  });
}
