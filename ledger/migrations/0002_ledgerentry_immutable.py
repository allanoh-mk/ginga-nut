from django.db import migrations


def install_immutability_trigger(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    schema_editor.execute(
        """
        CREATE FUNCTION ledger_entry_reject_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'ledger entries are immutable';
        END;
        $$
        """
    )
    schema_editor.execute(
        """
        CREATE TRIGGER ledger_entry_immutable
        BEFORE UPDATE OR DELETE ON ledger_ledgerentry
        FOR EACH ROW
        EXECUTE FUNCTION ledger_entry_reject_mutation()
        """
    )


def remove_immutability_trigger(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    schema_editor.execute("DROP TRIGGER ledger_entry_immutable ON ledger_ledgerentry")
    schema_editor.execute("DROP FUNCTION ledger_entry_reject_mutation()")


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            install_immutability_trigger,
            reverse_code=remove_immutability_trigger,
        ),
    ]
