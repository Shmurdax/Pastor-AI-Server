from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0017_sitebanner"),
    ]

    operations = [
        migrations.AddField(
            model_name="userchathistory",
            name="deleted_session_ids",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
