from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0004_mediavideo"),
    ]

    operations = [
        migrations.AddField(
            model_name="mediavideo",
            name="privacy_hash",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Unlisted privacy hash from Vimeo URI (/videos/{id}:{hash}).",
                max_length=64,
            ),
        ),
    ]
