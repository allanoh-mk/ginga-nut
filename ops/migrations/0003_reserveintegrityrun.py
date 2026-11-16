from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ops", "0002_marketswitch"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReserveIntegrityRun",
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
                ("results", models.JSONField(default=dict)),
                ("shortfall_chains", models.JSONField(default=list)),
                ("unmeasurable_chains", models.JSONField(default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ("-created_at", "-pk")},
        ),
    ]
