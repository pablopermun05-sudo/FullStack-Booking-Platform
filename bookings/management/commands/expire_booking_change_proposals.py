from django.core.management.base import BaseCommand

from bookings.models import BookingChangeProposal


class Command(BaseCommand):
    help = "Caduca las propuestas de cambio de reserva vencidas."

    def handle(self, *args, **options):
        expired_count = (
            BookingChangeProposal.expire_pending_proposals()
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Propuestas de cambio expiradas: {expired_count}"
            )
        )