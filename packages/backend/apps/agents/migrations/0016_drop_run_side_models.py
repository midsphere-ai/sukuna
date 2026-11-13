"""Drop run-side models after the backend purge.

The sandbox agent server now owns the full run lifecycle, so these tables are
no longer written by Django. ``SandboxCallbackEvent`` was the old Celery-dispatch
idempotency log for webhook-style metering; ``ScheduledTask`` was the Celery Beat
user-level scheduler; ``PersistentSandbox`` was the Claw always-on sandbox
record. None of these survive the purge.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("agents", "0015_scheduledtask_scheduling_improvements"),
    ]

    operations = [
        migrations.DeleteModel(name="SandboxCallbackEvent"),
        migrations.DeleteModel(name="ScheduledTask"),
        migrations.DeleteModel(name="PersistentSandbox"),
    ]
