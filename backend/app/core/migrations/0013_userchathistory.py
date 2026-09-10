from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0012_ingestion_title_dedupe_progress"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserChatHistory",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("entries", models.JSONField(blank=True, default=list)),
                (
                    "active_session_id",
                    models.CharField(blank=True, default="", max_length=64),
                ),
                ("schema_version", models.PositiveSmallIntegerField(default=1)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chat_history_backup",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "User chat history",
                "verbose_name_plural": "User chat histories",
            },
        ),
    ]
