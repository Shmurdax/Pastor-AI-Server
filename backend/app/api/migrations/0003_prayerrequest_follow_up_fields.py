from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0002_profile"),
    ]

    operations = [
        migrations.AddField(
            model_name="prayerrequest",
            name="contacted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="prayerrequest",
            name="followed_up",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="prayerrequest",
            name="pastor_notes",
            field=models.TextField(blank=True),
        ),
    ]
