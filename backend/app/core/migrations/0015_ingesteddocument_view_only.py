from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_ingesteddocument_topic_metadata"),
    ]

    operations = [
        migrations.AddField(
            model_name="ingesteddocument",
            name="view_only",
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text="When enabled, members can read this PDF in the app but cannot download it.",
            ),
        ),
        migrations.AddField(
            model_name="ingestionjob",
            name="view_only",
            field=models.BooleanField(
                default=False,
                help_text="When enabled, files in this job are stored as view-only (not downloadable) on the frontend.",
                verbose_name="Make view only",
            ),
        ),
    ]
