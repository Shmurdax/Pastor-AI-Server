import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

const _navy = Color(0xFF1B264F);
const _gold = Color(0xFFD4AF37);

/// Shown only after a successful Premium purchase.
/// Closing it (button, barrier tap, or back) returns control to the caller,
/// which should pop back to the chatbot.
Future<void> showPurchaseCompleteDialog(BuildContext context) {
  return showDialog<void>(
    context: context,
    barrierDismissible: true,
    builder: (ctx) => const PurchaseCompleteDialog(),
  );
}

class PurchaseCompleteDialog extends StatelessWidget {
  const PurchaseCompleteDialog({super.key});

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      titlePadding: const EdgeInsets.fromLTRB(24, 28, 24, 0),
      contentPadding: const EdgeInsets.fromLTRB(24, 16, 24, 8),
      actionsPadding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
      title: Column(
        children: [
          Container(
            width: 64,
            height: 64,
            decoration: BoxDecoration(
              color: _gold.withValues(alpha: 0.2),
              shape: BoxShape.circle,
            ),
            child: const Icon(Icons.check_circle, color: _gold, size: 40),
          ),
          const SizedBox(height: 16),
          Text(
            'Purchase complete',
            textAlign: TextAlign.center,
            style: GoogleFonts.figtree(
              color: _navy,
              fontWeight: FontWeight.bold,
              fontSize: 22,
            ),
          ),
        ],
      ),
      content: Text(
        'Welcome to Premium. Unlimited chat history and member media are unlocked.',
        textAlign: TextAlign.center,
        style: GoogleFonts.figtree(
          fontSize: 15,
          height: 1.45,
          color: Colors.black54,
        ),
      ),
      actions: [
        SizedBox(
          width: double.infinity,
          child: FilledButton(
            onPressed: () => Navigator.of(context).pop(),
            style: FilledButton.styleFrom(
              backgroundColor: _navy,
              foregroundColor: Colors.white,
              padding: const EdgeInsets.symmetric(vertical: 14),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(12),
              ),
            ),
            child: Text(
              'Back to chatbot',
              style: GoogleFonts.figtree(fontWeight: FontWeight.bold, fontSize: 16),
            ),
          ),
        ),
      ],
    );
  }
}
