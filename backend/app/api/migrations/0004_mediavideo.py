from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0003_cancel_at_period_end"),
    ]

    operations = [
        migrations.CreateModel(
            name="MediaVideo",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("vimeo_id", models.CharField(db_index=True, max_length=64, unique=True)),
                ("title", models.CharField(max_length=300)),
                ("description", models.TextField(blank=True, default="")),
                ("published_at", models.DateTimeField(db_index=True)),
                ("duration_seconds", models.PositiveIntegerField(default=0)),
                ("thumbnail_url", models.URLField(blank=True, default="")),
                (
                    "access_tier",
                    models.CharField(
                        choices=[("free_preview", "Free preview"), ("premium", "Premium")],
                        db_index=True,
                        default="premium",
                        max_length=32,
                    ),
                ),
                (
                    "access_tier_manual",
                    models.BooleanField(
                        default=False,
                        help_text="If set, Vimeo sync will not overwrite access_tier.",
                    ),
                ),
                ("is_published", models.BooleanField(db_index=True, default=True)),
                ("synced_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-published_at", "title"],
            },
        ),
    ]
