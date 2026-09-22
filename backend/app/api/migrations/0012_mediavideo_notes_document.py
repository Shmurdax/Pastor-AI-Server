from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0011_profile_token_cycle_anchor"),
        ("core", "0016_ingesteddocument_in_library"),
    ]

    operations = [
        migrations.AddField(
            model_name="mediavideo",
            name="notes_document",
            field=models.ForeignKey(
                blank=True,
                help_text="Study notes shown with this Walk through the Word video.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="media_videos",
                to="core.ingesteddocument",
            ),
        ),
        migrations.AddField(
            model_name="mediavideo",
            name="notes_document_manual",
            field=models.BooleanField(
                default=False,
                help_text="If set, automatic note matching will not overwrite notes_document.",
            ),
        ),
    ]
