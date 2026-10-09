from django.core.management.base import BaseCommand

from bookings.models import Booking, BookingChangeProposal

class Command(BaseCommand):
    help = "Expira las reservas pendientes cuyo plazo ha vencido."

    def handle(self, *args, **options):
        expired_count = Booking.expire_pending_bookings()
        expired_proposals_count = (
            BookingChangeProposal.expire_pending_proposals()
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Reservas expiradas: {expired_count}"
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Propuestas de cambio expiradas: {expired_proposals_count}"
            )
        )