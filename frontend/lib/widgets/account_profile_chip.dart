import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/l10n/app_locale.dart';
import 'package:flutter_application_1/screens/prayer_inbox_screen.dart';
import 'package:flutter_application_1/screens/response_reports_inbox_screen.dart';
import 'package:flutter_application_1/screens/settings_screen.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_application_1/services/auth_service.dart';
import 'package:flutter_application_1/widgets/brand_gradient.dart';
import 'package:flutter_application_1/widgets/user_account_badge.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';

const _navy = Color(0xFF1B264F);
const _gold = Color(0xFFD4AF37);
const _pink = Color(0xFFa1375a);

/// App-bar account chip used on chatbot, media, and subscriptions.
class AccountProfileChip extends StatelessWidget {
  const AccountProfileChip({
    super.key,
    required this.apiService,
    this.isMobile = false,
    this.dense = false,
    this.onOpenMedia,
    this.onOpenPrayerInbox,
    this.onOpenResponseReports,
    this.onSignedOut,
  });

  final ApiService apiService;
  final bool isMobile;
  /// Drops outer AppBar padding so this can stack above the language globe.
  final bool dense;
  final VoidCallback? onOpenMedia;
  final VoidCallback? onOpenPrayerInbox;
  final VoidCallback? onOpenResponseReports;
  final VoidCallback? onSignedOut;

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthController>();
    final user = auth.user;
    if (!auth.isAuthenticated || user == null) return const SizedBox.shrink();
    // Rebuild when language changes so the sheet/chip stay in sync.
    context.watch<LocaleController>();

    return Padding(
      padding: dense
          ? EdgeInsets.zero
          : EdgeInsets.only(top: isMobile ? 20 : 45, right: isMobile ? 8 : 24),
      child: Material(
        color: const Color(0xFFF8F4E8),
        shape: const StadiumBorder(),
        clipBehavior: Clip.none,
        child: InkWell(
          customBorder: const StadiumBorder(),
          onTap: () => showAccountProfileSheet(
            context,
            apiService: apiService,
            onOpenMedia: onOpenMedia,
            onOpenPrayerInbox: onOpenPrayerInbox,
            onOpenResponseReports: onOpenResponseReports,
            onSignedOut: onSignedOut,
          ),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(6, 6, 14, 6),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                CircleAvatar(
                  radius: 14,
                  backgroundColor: _gold.withValues(alpha: 0.25),
                  child: Text(
                    user.name.isNotEmpty ? user.name[0].toUpperCase() : '?',
                    style: GoogleFonts.figtree(fontSize: 12, fontWeight: FontWeight.bold, color: _navy),
                  ),
                ),
                const SizedBox(width: 8),
                UserNameWithAccountBadge(
                  user: user,
                  firstNameOnly: true,
                  style: GoogleFonts.figtree(fontWeight: FontWeight.w600, color: _navy),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

Future<void> showAccountProfileSheet(
  BuildContext context, {
  required ApiService apiService,
  VoidCallback? onOpenMedia,
  VoidCallback? onOpenPrayerInbox,
  VoidCallback? onOpenResponseReports,
  VoidCallback? onSignedOut,
}) {
  if (context.read<AuthController>().user == null) return Future.value();

  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
    ),
    builder: (ctx) {
      return Padding(
        padding: const EdgeInsets.fromLTRB(24, 24, 24, 32),
        child: Consumer2<AuthController, LocaleController>(
          builder: (context, auth, locale, _) {
            final user = auth.user;
            if (user == null) return const SizedBox.shrink();
            final s = locale.strings;
            return Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(s.yourAccount, style: GoogleFonts.figtree(fontSize: 20, fontWeight: FontWeight.bold, color: _navy)),
                const SizedBox(height: 20),
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: CircleAvatar(
                    backgroundColor: _gold.withValues(alpha: 0.2),
                    child: Text(
                      user.name.isNotEmpty ? user.name[0].toUpperCase() : '?',
                      style: GoogleFonts.figtree(fontWeight: FontWeight.bold, color: _navy),
                    ),
                  ),
                  title: UserNameWithAccountBadge(
                    user: user,
                    style: GoogleFonts.figtree(fontWeight: FontWeight.w600),
                  ),
                  subtitle: Text(user.email, style: GoogleFonts.figtree(color: Colors.black54)),
                ),
                if (user.isPaidPremium) ...[
                  const SizedBox(height: 4),
                  Text(
                    user.cancelAtPeriodEnd
                        ? s.premiumActiveUntilCancel(
                            formatPremiumAccessUntil(user.currentPeriodEnd),
                          )
                        : user.pendingBillingPeriod.isNotEmpty
                            ? s.premiumMemberSwitching(
                                user.billingPeriod.isNotEmpty
                                    ? user.billingPeriod
                                    : s.billingActive,
                                user.pendingBillingPeriod,
                                formatPremiumAccessUntil(user.currentPeriodEnd),
                              )
                            : s.premiumMember(user.billingPeriod),
                    style: GoogleFonts.figtree(fontSize: 13, color: Colors.black54, height: 1.35),
                  ),
                ],
                const SizedBox(height: 12),
                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: () {
                      Navigator.of(ctx).pop();
                      if (onOpenMedia != null) {
                        onOpenMedia();
                      }
                    },
                    icon: const Icon(Icons.video_library_outlined, color: _navy),
                    label: Text(s.mediaLibrary, style: GoogleFonts.figtree(color: _navy, fontWeight: FontWeight.bold)),
                    style: OutlinedButton.styleFrom(
                      side: const BorderSide(color: _navy, width: 1.5),
                      padding: const EdgeInsets.symmetric(vertical: 14),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: () {
                      Navigator.of(ctx).pop();
                      Navigator.of(context).push(
                        MaterialPageRoute(
                          builder: (_) => SettingsScreen(apiService: apiService),
                        ),
                      );
                    },
                    icon: const Icon(Icons.settings_outlined, color: _navy),
                    label: Text(
                      s.settings,
                      style: GoogleFonts.figtree(color: _navy, fontWeight: FontWeight.bold),
                    ),
                    style: OutlinedButton.styleFrom(
                      side: const BorderSide(color: _navy, width: 1.5),
                      padding: const EdgeInsets.symmetric(vertical: 14),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                if (user.isStaff) ...[
                  SizedBox(
                    width: double.infinity,
                    child: BrandGradientFilledButton(
                      onPressed: () {
                        Navigator.of(ctx).pop();
                        if (onOpenPrayerInbox != null) {
                          onOpenPrayerInbox();
                        } else {
                          Navigator.of(context).push(
                            MaterialPageRoute(
                              builder: (_) => PrayerInboxScreen(apiService: apiService),
                            ),
                          );
                        }
                      },
                      icon: const Icon(Icons.volunteer_activism_outlined),
                      label: Text(s.prayerInbox, style: GoogleFonts.figtree(fontWeight: FontWeight.bold)),
                    ),
                  ),
                  const SizedBox(height: 12),
                  SizedBox(
                    width: double.infinity,
                    child: BrandGradientFilledButton(
                      onPressed: () {
                        Navigator.of(ctx).pop();
                        if (onOpenResponseReports != null) {
                          onOpenResponseReports();
                        } else {
                          Navigator.of(context).push(
                            MaterialPageRoute(
                              builder: (_) => ResponseReportsInboxScreen(apiService: apiService),
                            ),
                          );
                        }
                      },
                      icon: const Icon(Icons.flag_outlined),
                      label: Text(s.responseReports, style: GoogleFonts.figtree(fontWeight: FontWeight.bold)),
                    ),
                  ),
                  const SizedBox(height: 12),
                ],
                if (kUseMockAuth)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Text(
                      s.demoModeAuthMocked,
                      style: GoogleFonts.figtree(fontSize: 12, color: Colors.black45),
                    ),
                  ),
                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: () async {
                      Navigator.of(ctx).pop();
                      await auth.logout();
                      apiService.setAccessToken(null);
                      onSignedOut?.call();
                    },
                    icon: const Icon(Icons.logout, color: _pink),
                    label: Text(s.signOut, style: GoogleFonts.figtree(color: _pink, fontWeight: FontWeight.bold)),
                    style: OutlinedButton.styleFrom(
                      side: const BorderSide(color: _pink),
                      padding: const EdgeInsets.symmetric(vertical: 14),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    ),
                  ),
                ),
              ],
            );
          },
        ),
      );
    },
  );
}
