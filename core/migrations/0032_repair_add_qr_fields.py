from django.db import migrations

class Migration(migrations.Migration):

    dependencies = [
        ("core", "0031_alter_logentry_options_remove_customuser_date_joined_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE core_customuser
                ADD COLUMN IF NOT EXISTS qr_code_value varchar(255);
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql="""
                ALTER TABLE core_customuser
                ADD COLUMN IF NOT EXISTS qr_code_image varchar(100);
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql="""
                CREATE UNIQUE INDEX IF NOT EXISTS core_customuser_qr_code_value_uniq
                ON core_customuser (qr_code_value)
                WHERE qr_code_value IS NOT NULL;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
