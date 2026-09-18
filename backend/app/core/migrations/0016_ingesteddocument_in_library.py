from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0015_ingesteddocument_view_only"),
    ]

    operations = [
        migrations.AddField(
            model_name="ingesteddocument",
            name="in_library",
            field=models.BooleanField(
                db_index=True,
                default=True,
                help_text="When off, chat/RAG still uses this file but it is hidden from the sermon library.",
            ),
        ),
        migrations.AddField(
            model_name="ingestionjob",
            name="in_library",
            field=models.BooleanField(
                default=True,
                help_text="When off, files are embedded for chat but hidden from the sermon library.",
                verbose_name="Show in sermon library",
            ),
        ),
    ]
