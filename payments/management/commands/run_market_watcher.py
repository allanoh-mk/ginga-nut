import time

from django.core.management.base import BaseCommand

from core.services.watch_chain import watch_chain
from payments.models import Chain


class Command(BaseCommand):
    help = "Refresh server-side rates and poll configured chain providers."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--interval", type=int, default=60)

    def handle(self, *args, **options) -> None:
        if options["interval"] <= 0:
            raise ValueError("Watcher interval must be positive.")
        while True:
            for chain in Chain.values:
                deposits = watch_chain(chain)
                self.stdout.write(f"{chain}: observed {len(deposits)} deposits.")
            if options["once"]:
                return
            time.sleep(options["interval"])
