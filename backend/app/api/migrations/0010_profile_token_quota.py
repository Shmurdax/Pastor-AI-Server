# Generated manually for Premium chat token budgets.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0009_password_reset_code"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="token_balance",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Remaining chat tokens (includes secret monthly rollover).",
            ),
        ),
        migrations.AddField(
            model_name="profile",
            name="tokens_spent",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Lifetime tokens consumed by chat generations.",
            ),
        ),
        migrations.AddField(
            model_name="profile",
            name="token_period_key",
            field=models.CharField(
                blank=True,
                default="",
                help_text="YYYY-MM of the last monthly token grant applied.",
                max_length=7,
            ),
        ),
        migrations.AddField(
            model_name="profile",
            name="tokens_used_today",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Tokens consumed on token_usage_day (daily pacing).",
            ),
        ),
        migrations.AddField(
            model_name="profile",
            name="token_usage_day",
            field=models.DateField(
                blank=True,
                help_text="Local calendar day for tokens_used_today.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="profile",
            name="token_cooldown_until",
            field=models.DateTimeField(
                blank=True,
                help_text="When set, chat is blocked until this time (daily binge cooldown).",
                null=True,
            ),
        ),
    ]
