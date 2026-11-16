from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from core.services.fake_deposit import fake_deposit
from payments.models import Chain


class Command(BaseCommand):
    help = "Inject and process a confirmed deposit through FakeProvider."

    def add_arguments(self, parser) -> None:
        parser.add_argument("username")
        parser.add_argument("chain", choices=Chain.values)
        parser.add_argument("transaction_id")
        parser.add_argument("amount_atomic", type=int)
        parser.add_argument("base_units_per_coin", type=int)
        parser.add_argument("--confirmations", type=int)

    def handle(self, *args, **options) -> None:
        user = get_user_model().objects.filter(username=options["username"]).first()
        if user is None:
            raise CommandError("User does not exist.")
        confirmations = options["confirmations"]
        if confirmations is None:
            from django.conf import settings

            confirmations = settings.MARKET_CHAIN_CONFIRMATIONS[options["chain"]]
        try:
            deposit = fake_deposit(
                user=user,
                chain=options["chain"],
                transaction_id=options["transaction_id"],
                amount_atomic=options["amount_atomic"],
                base_units_per_coin=options["base_units_per_coin"],
                confirmations=confirmations,
            )
        except (ValueError, RuntimeError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            self.style.SUCCESS(
                f"Deposit {deposit.pk}: {deposit.state}, "
                f"{deposit.base_amount} base units."
            )
        )
