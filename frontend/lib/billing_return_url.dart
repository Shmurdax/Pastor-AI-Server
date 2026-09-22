import 'package:flutter_application_1/billing_return_url_stub.dart'
    if (dart.library.html) 'package:flutter_application_1/billing_return_url_web.dart'
    as impl;

/// Remove `billing` and `session_id` from the browser URL after checkout.
void clearBillingReturnQuery() => impl.clearBillingReturnQuery();
