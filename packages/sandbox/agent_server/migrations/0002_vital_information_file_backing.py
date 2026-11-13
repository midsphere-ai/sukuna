# Generated for knowledge manager upgrade — Phase A

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("agent_server", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="vitalinformation",
            name="file_path",
            field=models.CharField(blank=True, default="", max_length=512),
        ),
        migrations.AddField(
            model_name="vitalinformation",
            name="content_hash",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="vitalinformation",
            name="scope",
            field=models.CharField(
                choices=[("conversation", "Conversation"), ("project", "Project")],
                default="conversation",
                max_length=20,
            ),
        ),
        migrations.AddIndex(
            model_name="vitalinformation",
            index=models.Index(
                fields=["conversation_id", "file_path"],
                name="idx_vital_info_conv_filepath",
            ),
        ),
    ]
