// ignore_for_file: avoid_web_libraries_in_flutter, deprecated_member_use

import 'dart:html' as html;

import 'package:flutter_application_1/billing_return_query.dart';

void clearBillingReturnQuery() {
  final current = Uri.parse(html.window.location.href);
  final next = uriWithoutBillingReturn(current);
  if (next == current) return;
  html.window.history.replaceState(null, '', next.toString());
}
