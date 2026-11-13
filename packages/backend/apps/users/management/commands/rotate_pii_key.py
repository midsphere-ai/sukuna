"""Management command to re-encrypt all User PII fields with a new Fernet key."""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from apps.users.encryption import re_encrypt


class Command(BaseCommand):
    help = "Re-encrypt all User PII fields (email, name, nickname) from old key to new key."

    def add_arguments(self, parser):
        parser.add_argument(
            "--old-key",
            required=True,
            help="The current Fernet encryption key.",
        )
        parser.add_argument(
            "--new-key",
            required=True,
            help="The new Fernet encryption key to re-encrypt with.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report counts without modifying data.",
        )

    def handle(self, *args, **options):
        old_key = options["old_key"]
        new_key = options["new_key"]
        dry_run = options["dry_run"]

        # Read raw ciphertext using raw SQL to bypass EncryptedCharField.from_db_value()
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, email, name, nickname FROM users_user")
            rows = cursor.fetchall()

        total = len(rows)
        self.stdout.write(f"Found {total} user(s) to process.")

        if dry_run:
            self.stdout.write(
                self.style.WARNING("Dry-run mode — no changes will be made.")
            )

        rotated = 0
        errors = 0

        for user_id, email, name, nickname in rows:
            try:
                updates = {}
                params = []

                if email and email.startswith("gAAAAA"):
                    updates["email"] = re_encrypt(old_key, new_key, email)

                if name and name.startswith("gAAAAA"):
                    updates["name"] = re_encrypt(old_key, new_key, name)

                if nickname and nickname.startswith("gAAAAA"):
                    updates["nickname"] = re_encrypt(old_key, new_key, nickname)

                if updates:
                    if not dry_run:
                        set_clause = ", ".join(f"{col} = %s" for col in updates)
                        params = list(updates.values()) + [user_id]
                        with connection.cursor() as cursor:
                            cursor.execute(
                                f"UPDATE users_user SET {set_clause} WHERE id = %s",
                                params,
                            )
                    rotated += 1

            except Exception as e:
                errors += 1
                self.stderr.write(
                    self.style.ERROR(f"Error rotating user {user_id}: {e}")
                )

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"Would rotate {rotated} user(s). {errors} error(s)."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"Rotated {rotated} user(s). {errors} error(s).")
            )

        if errors:
            raise CommandError(f"{errors} user(s) failed key rotation.")
