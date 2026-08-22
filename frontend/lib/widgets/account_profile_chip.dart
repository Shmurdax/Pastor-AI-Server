import 'package:flutter/material.dart';
import 'package:flutter_application_1/controllers/auth_controller.dart';
import 'package:flutter_application_1/screens/email_notification_screen.dart';
import 'package:flutter_application_1/screens/prayer_inbox_screen.dart';
import 'package:flutter_application_1/services/api_service.dart';
import 'package:flutter_application_1/services/auth_service.dart';
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
    this.onOpenMedia,
    this.onOpenSubscriptions,
    this.onOpenPrayerInbox,
    this.onSignedOut,
  });

  final ApiService apiService;
  final bool isMobile;
  final VoidCallback? onOpenMedia;
  final VoidCallback? onOpenSubscriptions;
  final VoidCallback? onOpenPrayerInbox;
  final VoidCallback? onSignedOut;

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthController>();
    final user = auth.user;
    if (!auth.isAuthenticated || user == null) return const SizedBox.shrink();

    return Padding(
      padding: EdgeInsets.only(top: isMobile ? 20 : 45, right: isMobile ? 8 : 24),
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
            onOpenSubscriptions: onOpenSubscriptions,
            onOpenPrayerInbox: onOpenPrayerInbox,
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
  VoidCallback? onOpenSubscriptions,
  VoidCallback? onOpenPrayerInbox,
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
        child: Consumer<AuthController>(
          builder: (context, auth, _) {
            final user = auth.user;
            if (user == null) return const SizedBox.shrink();
            return Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Your account', style: GoogleFonts.figtree(fontSize: 20, fontWeight: FontWeight.bold, color: _navy)),
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
                        ? 'Premium stays active until ${formatPremiumAccessUntil(user.currentPeriodEnd)}. Auto-renewal is off.'
                        : 'Premium member${user.billingPeriod.isNotEmpty ? ' · ${user.billingPeriod}' : ''}.',
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
                    label: Text('Media library', style: GoogleFonts.figtree(color: _navy, fontWeight: FontWeight.bold)),
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
                      if (onOpenSubscriptions != null) {
                        onOpenSubscriptions();
                      }
                    },
                    icon: const Icon(Icons.workspace_premium_outlined, color: _navy),
                    label: Text('View plans', style: GoogleFonts.figtree(color: _navy, fontWeight: FontWeight.bold)),
                    style: OutlinedButton.styleFrom(
                      side: const BorderSide(color: _gold, width: 1.5),
                      padding: const EdgeInsets.symmetric(vertical: 14),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    ),
                  ),
                ),
                if (user.isPaidPremium && !user.cancelAtPeriodEnd) ...[
                  const SizedBox(height: 12),
                  SizedBox(
                    width: double.infinity,
                    child: OutlinedButton.icon(
                      onPressed: () => _unsubscribeFromPremium(
                        hostContext: context,
                        sheetContext: ctx,
                        apiService: apiService,
                      ),
                      icon: const Icon(Icons.cancel_outlined, color: _pink),
                      label: Text('Unsubscribe', style: GoogleFonts.figtree(color: _pink, fontWeight: FontWeight.bold)),
                      style: OutlinedButton.styleFrom(
                        side: const BorderSide(color: _pink),
                        padding: const EdgeInsets.symmetric(vertical: 14),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                      ),
                    ),
                  ),
                ],
                const SizedBox(height: 12),
                if (user.isStaff) ...[
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton.icon(
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
                      label: Text('Prayer inbox', style: GoogleFonts.figtree(fontWeight: FontWeight.bold)),
                      style: FilledButton.styleFrom(
                        backgroundColor: _navy,
                        padding: const EdgeInsets.symmetric(vertical: 14),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                      ),
                    ),
                  ),
                  const SizedBox(height: 12),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton.icon(
                      onPressed: () {
                        Navigator.of(ctx).pop();
                        Navigator.of(context).push(
                          MaterialPageRoute(
                            builder: (_) => EmailNotificationScreen(apiService: apiService),
                          ),
                        );
                      },
                      icon: const Icon(Icons.mail_outline),
                      label: Text('Email members', style: GoogleFonts.figtree(fontWeight: FontWeight.bold)),
                      style: FilledButton.styleFrom(
                        backgroundColor: _navy,
                        padding: const EdgeInsets.symmetric(vertical: 14),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                      ),
                    ),
                  ),
                  const SizedBox(height: 12),
                ],
                if (kUseMockAuth)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Text(
                      'Demo mode: auth is mocked until Django endpoints are ready.',
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
                    label: Text('Sign out', style: GoogleFonts.figtree(color: _pink, fontWeight: FontWeight.bold)),
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

Future<void> _unsubscribeFromPremium({
  required BuildContext hostContext,
  required BuildContext sheetContext,
  required ApiService apiService,
}) async {
  final auth = hostContext.read<AuthController>();
  final user = auth.user;
  if (user == null || !user.isPaidPremium) return;

  final confirmed = await showDialog<bool>(
    context: sheetContext,
    builder: (dialogCtx) => AlertDialog(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      title: Text('Unsubscribe from Premium?', style: GoogleFonts.figtree(color: _navy, fontWeight: FontWeight.bold)),
      content: Text(
        'You will keep Premium benefits until ${formatPremiumAccessUntil(user.currentPeriodEnd)}. '
        'After that, your account returns to the Free plan and auto-renewal stops.',
        style: GoogleFonts.figtree(height: 1.45),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(dialogCtx).pop(false),
          child: Text('Keep Premium', style: GoogleFonts.figtree(color: _navy, fontWeight: FontWeight.w600)),
        ),
        FilledButton(
          onPressed: () => Navigator.of(dialogCtx).pop(true),
          style: FilledButton.styleFrom(backgroundColor: _pink),
          child: Text('Unsubscribe', style: GoogleFonts.figtree(fontWeight: FontWeight.bold)),
        ),
      ],
    ),
  );
  if (confirmed != true) return;

  try {
    apiService.setAccessToken(auth.token);
    final result = await apiService.cancelSubscription();
    final userJson = result['user'];
    if (userJson is Map<String, dynamic>) {
      await auth.applyUser(AuthUser.fromJson(userJson));
    } else {
      await auth.refreshMe();
    }
    if (!hostContext.mounted) return;
    ScaffoldMessenger.of(hostContext).showSnackBar(
      SnackBar(
        content: Text(
          'Auto-renewal is off. Premium stays until ${formatPremiumAccessUntil(auth.user?.currentPeriodEnd)}.',
        ),
      ),
    );
  } catch (e) {
    if (!hostContext.mounted) return;
    ScaffoldMessenger.of(hostContext).showSnackBar(
      SnackBar(
        content: Text(e.toString().replaceFirst(RegExp(r'^Exception:\s*'), '')),
      ),
    );
  }
}
