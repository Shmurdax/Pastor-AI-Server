# Generated manually for Stripe subscription fields on Profile

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="billing_period",
            field=models.CharField(blank=True, default="", max_length=16),
        ),
        migrations.AddField(
            model_name="profile",
            name="stripe_customer_id",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="profile",
            name="stripe_subscription_id",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="profile",
            name="subscription_status",
            field=models.CharField(default="free", max_length=32),
        ),
    ]
