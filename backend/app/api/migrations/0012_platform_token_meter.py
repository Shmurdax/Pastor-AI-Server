# Generated manually for platform-wide monthly token meter.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0011_profile_token_cycle_anchor"),
    ]

    operations = [
        migrations.CreateModel(
            name="PlatformTokenMeter",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "period_key",
                    models.CharField(
                        db_index=True,
                        help_text="Calendar month YYYY-MM.",
                        max_length=7,
                        unique=True,
                    ),
                ),
                ("tokens_used", models.BigIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-period_key"],
                "verbose_name": "Premium chat token pool",
                "verbose_name_plural": "Premium chat token pools",
            },
        ),
        migrations.AlterField(
            model_name="profile",
            name="token_balance",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Deprecated per-user remaining balance (unused; platform pool gates chat).",
            ),
        ),
        migrations.AlterField(
            model_name="profile",
            name="token_cooldown_until",
            field=models.DateTimeField(
                blank=True,
                help_text="Admin chat restriction: when set, this user cannot chat until this time.",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="profile",
            name="token_cycle_anchor",
            field=models.DateField(
                blank=True,
                help_text="Deprecated first-subscribe anniversary for token grants.",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="profile",
            name="token_period_key",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Deprecated anniversary grant key.",
                max_length=10,
            ),
        ),
        migrations.AlterField(
            model_name="profile",
            name="tokens_spent",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Lifetime tokens this account contributed to the platform pool.",
            ),
        ),
        migrations.AlterField(
            model_name="profile",
            name="tokens_used_today",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Tokens consumed on token_usage_day (diagnostics).",
            ),
        ),
    ]
