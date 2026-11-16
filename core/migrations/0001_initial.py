from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="FinancialJob",
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
                ("job_type", models.CharField(max_length=32)),
                ("payload", models.JSONField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "claimed_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("error", models.TextField(blank=True)),
            ],
            options={
                "ordering": ("created_at", "pk"),
                "indexes": [
                    models.Index(
                        fields=["completed_at", "claimed_at", "created_at"],
                        name="core_finjob_pending_idx",
                    )
                ],
            },
        ),
    ]
