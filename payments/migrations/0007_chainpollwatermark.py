from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0006_moneroorderescrow_moneroorderescrowevent_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ChainPollWatermark",
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
                ("provider", models.CharField(max_length=32)),
                (
                    "chain",
                    models.CharField(
                        choices=[
                            ("BTC", "BTC"),
                            ("LTC", "LTC"),
                            ("TRC20", "TRC-20"),
                            ("XMR", "XMR"),
                        ],
                        max_length=8,
                    ),
                ),
                ("last_block", models.PositiveBigIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.AddConstraint(
            model_name="chainpollwatermark",
            constraint=models.UniqueConstraint(
                fields=("provider", "chain"),
                name="payments_unique_chain_poll_watermark",
            ),
        ),
    ]
