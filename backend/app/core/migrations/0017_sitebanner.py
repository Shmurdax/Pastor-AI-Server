from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0016_ingesteddocument_in_library"),
    ]

    operations = [
        migrations.CreateModel(
            name="SiteBanner",
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
                ("enabled", models.BooleanField(default=False)),
                (
                    "mode",
                    models.CharField(
                        choices=[
                            ("downtime", "Downtime notice"),
                            ("custom", "Custom message"),
                        ],
                        default="downtime",
                        max_length=16,
                    ),
                ),
                ("reason", models.CharField(blank=True, default="", max_length=300)),
                ("starts_at", models.DateTimeField(blank=True, null=True)),
                ("ends_at", models.DateTimeField(blank=True, null=True)),
                ("starts_label", models.CharField(blank=True, default="", max_length=80)),
                ("ends_label", models.CharField(blank=True, default="", max_length=80)),
                ("custom_message", models.TextField(blank=True, default="")),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Website banner",
            },
        ),
    ]
