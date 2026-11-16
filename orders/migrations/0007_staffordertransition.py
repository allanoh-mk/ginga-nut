import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0006_remove_order_funded_order_has_required_parties_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="StaffOrderTransition",
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
                (
                    "from_state",
                    models.CharField(
                        choices=[
                            ("DRAFT", "Draft"),
                            ("FUNDED", "Funded"),
                            ("ACCEPTED", "Accepted"),
                            ("PACKED", "Packed"),
                            ("DISPATCHED", "Dispatched"),
                            ("DELIVERED", "Delivered"),
                            ("DISPUTED", "Disputed"),
                            ("FINALIZED", "Finalized"),
                            ("SETTLEMENT_PENDING", "Settlement pending multisig"),
                            ("REFUNDED", "Refunded"),
                            ("PARTIAL", "Partially ruled"),
                            ("CANCELLED", "Cancelled"),
                            ("EXPIRED", "Expired"),
                        ],
                        max_length=24,
                    ),
                ),
                (
                    "to_state",
                    models.CharField(
                        choices=[
                            ("DRAFT", "Draft"),
                            ("FUNDED", "Funded"),
                            ("ACCEPTED", "Accepted"),
                            ("PACKED", "Packed"),
                            ("DISPATCHED", "Dispatched"),
                            ("DELIVERED", "Delivered"),
                            ("DISPUTED", "Disputed"),
                            ("FINALIZED", "Finalized"),
                            ("SETTLEMENT_PENDING", "Settlement pending multisig"),
                            ("REFUNDED", "Refunded"),
                            ("PARTIAL", "Partially ruled"),
                            ("CANCELLED", "Cancelled"),
                            ("EXPIRED", "Expired"),
                        ],
                        max_length=24,
                    ),
                ),
                ("reason", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "actor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="staff_order_transitions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="staff_transition_logs",
                        to="orders.order",
                    ),
                ),
            ],
            options={"ordering": ("-created_at", "-pk")},
        ),
        migrations.AddIndex(
            model_name="staffordertransition",
            index=models.Index(
                fields=["order", "created_at"],
                name="orders_stf_ord_created_idx",
            ),
        ),
    ]
