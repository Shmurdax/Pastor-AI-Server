from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0002_subscription_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="cancel_at_period_end",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="profile",
            name="current_period_end",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
