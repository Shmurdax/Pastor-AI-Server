from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0006_pending_billing_period"),
    ]

    operations = [
        migrations.CreateModel(
            name="MailchimpExportRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("started_by", models.CharField(blank=True, default="", max_length=150)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("candidate_count", models.PositiveIntegerField(default=0)),
                ("added", models.PositiveIntegerField(default=0)),
                ("updated", models.PositiveIntegerField(default=0)),
                ("skipped", models.PositiveIntegerField(default=0)),
                ("failed", models.PositiveIntegerField(default=0)),
                ("error_summary", models.TextField(blank=True, default="")),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
