from pathlib import Path

from django.db import migrations, models


def set_default_titles(apps, schema_editor):
    IngestedDocument = apps.get_model("core", "IngestedDocument")
    for doc in IngestedDocument.objects.all():
        name = doc.source_name or ""
        stem = Path(name).stem or "document"
        doc.title = stem
        doc.save(update_fields=["title"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_ingestion_job_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="ingesteddocument",
            name="title",
            field=models.CharField(
                default="",
                max_length=300,
                blank=True,
                help_text="Display name for links and APIs (defaults from filename; edit to match sermon titles in your app).",
            ),
        ),
        migrations.RunPython(set_default_titles, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="ingesteddocument",
            name="title",
            field=models.CharField(
                max_length=300,
                help_text="Display name for links and APIs (defaults from filename; edit to match sermon titles in your app).",
            ),
        ),
    ]
