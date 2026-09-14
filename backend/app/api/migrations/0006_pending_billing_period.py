from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0005_mediavideo_privacy_hash"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="pending_billing_period",
            field=models.CharField(
                blank=True,
                choices=[("monthly", "Monthly"), ("yearly", "Yearly")],
                default="",
                help_text="Scheduled monthly/yearly switch that takes effect at current_period_end.",
                max_length=16,
            ),
        ),
    ]
