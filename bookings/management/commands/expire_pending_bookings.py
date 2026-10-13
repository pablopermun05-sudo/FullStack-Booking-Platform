from django.core.management.base import BaseCommand

from bookings.models import Booking


class Command(BaseCommand):
    help = "Expira las reservas pendientes cuyo plazo ha vencido."

    def handle(self, *args, **options):
        expired_count = Booking.expire_pending_bookings()

        self.stdout.write(
            self.style.SUCCESS(
                f"Reservas expiradas: {expired_count}"
            )
        )