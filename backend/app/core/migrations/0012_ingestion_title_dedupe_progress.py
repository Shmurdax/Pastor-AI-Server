from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_merge_20260826_2310"),
    ]

    operations = [
        migrations.AddField(
            model_name="ingesteddocument",
            name="normalized_title",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                help_text="Lowercase alphanumeric key from prettified title for near-duplicate detection.",
                max_length=300,
            ),
        ),
        migrations.AddField(
            model_name="ingesteddocument",
            name="content_hash",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                help_text="SHA-256 of cleaned extracted text (or transcript) for near-duplicate detection.",
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name="ingestionjob",
            name="current_file",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Filename currently being processed (for live progress UI).",
                max_length=512,
            ),
        ),
    ]
