from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0013_userchathistory"),
    ]

    operations = [
        migrations.AddField(
            model_name="ingesteddocument",
            name="topic_metadata",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Searchable topic title/topics/keywords/summary for video (and optional doc) RAG.",
            ),
        ),
    ]
