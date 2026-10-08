from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0012_remove_profile_token_quota"),
    ]

    operations = [
        migrations.CreateModel(
            name="EpisodeNote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("episode_date", models.DateField(db_index=True, unique=True)),
                ("original_filename", models.CharField(max_length=255)),
                ("stored_filename", models.CharField(max_length=255)),
                ("search_text", models.TextField(blank=True, default="")),
                ("topics", models.JSONField(blank=True, default=list)),
                ("content_hash", models.CharField(db_index=True, max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "media_video",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="episode_note",
                        to="api.mediavideo",
                    ),
                ),
            ],
            options={
                "ordering": ["-episode_date", "original_filename"],
            },
        ),
    ]
