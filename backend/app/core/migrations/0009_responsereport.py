from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0008_churchevent"),
    ]

    operations = [
        migrations.CreateModel(
            name="ResponseReport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("user_query_snapshot", models.TextField()),
                ("ai_response_snapshot", models.TextField()),
                (
                    "reason",
                    models.CharField(
                        choices=[
                            ("inaccurate", "Inaccurate information"),
                            ("off_topic", "Off topic"),
                            ("harmful_unsafe", "Harmful or unsafe"),
                            ("confusing", "Confusing or unclear"),
                            ("other", "Other"),
                        ],
                        max_length=32,
                    ),
                ),
                ("details", models.TextField(blank=True, max_length=2000)),
                ("session_id", models.TextField(blank=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("new", "New"),
                            ("reviewed", "Reviewed"),
                            ("dismissed", "Dismissed"),
                        ],
                        default="new",
                        max_length=16,
                    ),
                ),
                ("staff_notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "chat_message",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reports",
                        to="core.chatmessage",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="response_reports",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="responsereport",
            index=models.Index(fields=["status", "-created_at"], name="core_respon_status_6f0c8a_idx"),
        ),
        migrations.AddIndex(
            model_name="responsereport",
            index=models.Index(fields=["session_id", "chat_message"], name="core_respon_session_0c5e91_idx"),
        ),
    ]
