from django.db import migrations, models


def backfill_source_kind(apps, schema_editor):
    IngestedDocument = apps.get_model("core", "IngestedDocument")
    IngestedDocument.objects.filter(original_extension=".md").update(source_kind="website")
    video_exts = (
        ".mp4",
        ".m4v",
        ".mov",
        ".avi",
        ".mkv",
        ".webm",
        ".wmv",
        ".flv",
        ".mpeg",
        ".mpg",
        ".3gp",
        ".ogv",
        ".ts",
        ".mts",
        ".m2ts",
    )
    IngestedDocument.objects.filter(original_extension__in=video_exts).update(source_kind="video")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_chatmessage_user"),
    ]

    operations = [
        migrations.AlterField(
            model_name="ingesteddocument",
            name="original_extension",
            field=models.CharField(max_length=16),
        ),
        migrations.AddField(
            model_name="ingesteddocument",
            name="source_kind",
            field=models.CharField(
                choices=[("document", "Document"), ("video", "Video"), ("website", "Website")],
                db_index=True,
                default="document",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="ingestionjob",
            name="job_kind",
            field=models.CharField(
                choices=[("document", "Document"), ("video", "Video"), ("website", "Website")],
                db_index=True,
                default="document",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="ingestionjob",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.RunPython(backfill_source_kind, migrations.RunPython.noop),
    ]
