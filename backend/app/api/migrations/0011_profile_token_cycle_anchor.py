# Generated manually for anniversary-based token grants.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0010_profile_token_quota"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="token_cycle_anchor",
            field=models.DateField(
                blank=True,
                help_text="First Premium subscribe day; monthly token grants land on this day each month.",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="profile",
            name="token_period_key",
            field=models.CharField(
                blank=True,
                default="",
                help_text="YYYY-MM-DD start of the last anniversary token grant period.",
                max_length=10,
            ),
        ),
    ]
