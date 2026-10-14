from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.db import OperationalError, models, transaction
from phonenumber_field.modelfields import PhoneNumberField
from django.core.exceptions import ValidationError
from datetime import date, timedelta
from django.utils import timezone
from builtins import property as python_property
from decimal import Decimal, InvalidOperation
from django.db.models import Q, DateTimeField, F, Func, Value
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateRangeField, DateTimeRangeField, RangeOperators
import random
import time
import uuid

class User(AbstractUser):
    first_name = models.CharField("Nombre", max_length=150, blank=False)
    last_name = models.CharField("Apellidos", max_length=150, blank=False)
    email = models.EmailField(unique=True)
    phone_number = PhoneNumberField(null=True, blank=True, unique=True)

    class Meta:
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"

    def __str__(self):
        return self.username

    @property
    def is_approved_owner(self):
        return hasattr(self, "owner_profile") and self.owner_profile.status == "APPROVED"

class OwnerProfile(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pendiente"),
        ("APPROVED", "Aprobado"),
        ("REJECTED", "Rechazado"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="owner_profile",
    )
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default="PENDING",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Perfil de propietario"
        verbose_name_plural = "Perfiles de propietarios"

    def __str__(self):
        return f"{self.user} - {self.get_status_display()}"

def can_manage_properties(user):
    if not user.is_authenticated:
        return False
    return user.is_staff or user.is_approved_owner

class Property(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField()
    location = models.CharField(max_length=255)
    image = models.ImageField(upload_to='properties/')
    default_price_per_night = models.DecimalField(max_digits=7, decimal_places=2)
    default_min_nights = models.PositiveIntegerField(default=1)
    children = models.PositiveIntegerField()
    adults = models.PositiveIntegerField()
    rooms = models.PositiveIntegerField()
    notice_period_days = models.PositiveIntegerField(default=0)
    allow_pets = models.BooleanField(default=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="properties")
    
    class Meta:
        verbose_name = "Propiedad"
        verbose_name_plural = "Propiedades"

    def __str__(self):
        return self.title

    def clean(self):
        if self.default_price_per_night <= 0:
            raise ValidationError("El precio por noche debe ser mayor que 0")
        if self.default_min_nights < 1:
            raise ValidationError("El número mínimo de noches debe ser al menos 1")
        if self.adults == 0:
            raise ValidationError("El número máximos de adultos no puede ser 0")
        if self.rooms == 0:
            raise ValidationError("El número de habitaciones no puede ser 0")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

class BookingDateRange(Func):
    function = "DATERANGE"
    output_field = DateRangeField()

    def __init__(self, start, end, **extra):
        super().__init__(
            start,
            end,
            Value("[)"),
            **extra,
        )

class BookingInventoryRange(Func):
    output_field = DateTimeRangeField()

    def __init__(
        self,
        created_at="created_at",
        expires_at="expires_at",
        status="status",
        **extra,
    ):
        super().__init__(
            F(created_at),
            F(expires_at),
            F(status),
            **extra,
        )

    def as_sql(self, compiler, connection, **extra_context):
        created_at, expires_at, status = self.source_expressions

        created_sql, created_params = compiler.compile(created_at)
        expires_sql, expires_params = compiler.compile(expires_at)
        status_sql, status_params = compiler.compile(status)

        sql = (
            "CASE "
            f"WHEN {status_sql} = 'CONFIRMED' "
            f"THEN TSTZRANGE("
            f"{created_sql}, "
            f"'infinity'::timestamptz, "
            f"'[)'"
            f") "
            f"WHEN {status_sql} = 'PENDING' "
            f"AND {expires_sql} IS NOT NULL "
            f"AND {expires_sql} > {created_sql} "
            f"THEN TSTZRANGE("
            f"{created_sql}, "
            f"{expires_sql}, "
            f"'[)'"
            f") "
            "ELSE TSTZRANGE(NULL, NULL, '[)') "
            "END"
        )

        params = (
            *created_params,
            *expires_params,
            *status_params,
        )

        return sql, params

class BookingHoldInventoryRange(Func):
    output_field = DateTimeRangeField()

    def __init__(
        self,
        created_at="created_at",
        expires_at="expires_at",
        **extra,
    ):
        super().__init__(
            F(created_at),
            F(expires_at),
            **extra,
        )

    def as_sql(self, compiler, connection, **extra_context):
        created_at, expires_at = self.source_expressions

        created_sql, created_params = compiler.compile(created_at)
        expires_sql, expires_params = compiler.compile(expires_at)

        sql = (
            "CASE "
            f"WHEN {expires_sql} > {created_sql} "
            f"THEN TSTZRANGE("
            f"{created_sql}, {expires_sql}, '[)'"
            f") "
            "ELSE TSTZRANGE(NULL, NULL, '[)') "
            "END"
        )

        params = (
            *expires_params,
            *created_params,
            *created_params,
            *expires_params,
        )

        return sql, params
        
class Booking(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pendiente"),
        ("CONFIRMED", "Confirmada"),
        ("CANCELLED", "Cancelada"),
        ("EXPIRED", "Expirada"),
    ]

    ACTIVE_STATUSES = ("PENDING", "CONFIRMED")

    tenant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="bookings",
        null=True,
        blank=True,
    )

    guest_first_name = models.CharField("Nombre del huésped", max_length=150)
    guest_last_name = models.CharField("Apellidos del huésped", max_length=150)
    guest_email = models.EmailField("Email del huésped")
    guest_phone_number = PhoneNumberField("Teléfono del huésped")

    guest_country = models.CharField("País del huésped", max_length=100)
    guest_region = models.CharField("Región del huésped", max_length=100, blank=True)
    guest_city = models.CharField("Ciudad del huésped", max_length=100)
    guest_postal_code = models.CharField("Código postal del huésped", max_length=20, blank=True)
    guest_address = models.CharField("Dirección del huésped", max_length=255)

    is_for_self = models.BooleanField("La reserva es para sí mismo", default=True)
    is_business_trip = models.BooleanField("Viaje de trabajo", default=False)

    tax_id = models.CharField("CIF", max_length=50, blank=True)

    guest_count = models.PositiveIntegerField("Número de huéspedes", default=1)

    special_requests = models.TextField("Peticiones especiales", blank=True)
    arrival_time = models.TimeField("Hora de llegada")
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="bookings")
    initial_date = models.DateField()
    final_date = models.DateField()
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default="PENDING",
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    def is_expired(self):
        if self.status != "PENDING":
            return False
        if self.expires_at is None:
            return False
        return self.expires_at <= timezone.now()

    def confirm(self):
        with transaction.atomic():
            booking = type(self).objects.select_for_update().get(pk=self.pk)

            if booking.status != "PENDING":
                self.status = booking.status
                return False

            if booking.is_expired():
                booking.status = "EXPIRED"
                booking.save_base(update_fields=["status"])
                self.status = booking.status
                return False

            booking.status = "CONFIRMED"
            booking.save(update_fields=["status"])
            self.status = booking.status

            return True

    def expire(self):
        with transaction.atomic():
            booking = type(self).objects.select_for_update().get(pk=self.pk)

            if not booking.is_expired():
                self.status = booking.status
                return False

            booking.status = "EXPIRED"
            booking.save_base(update_fields=["status"])

            self.status = booking.status
            return True

    def cancel(self):
        with transaction.atomic():
            booking = type(self).objects.select_for_update().get(
                pk=self.pk
            )

            if booking.status not in ("PENDING", "CONFIRMED"):
                self.status = booking.status
                return False

            booking.status = "CANCELLED"
            booking.save(update_fields=["status"])

            self.status = booking.status
            return True
    
    @classmethod
    def expire_pending_bookings(cls):
        now = timezone.now()

        return cls.objects.filter(
            status="PENDING",
            expires_at__isnull=False,
            expires_at__lte=now,
        ).update(status="EXPIRED")

    @classmethod
    def create_pending(cls, *, tenant, property, initial_date, final_date, expires_at, guest_first_name, guest_last_name, guest_email, guest_phone_number, guest_country, guest_city, guest_address, guest_count, arrival_time, guest_region="", guest_postal_code="", is_for_self=True, is_business_trip=False, tax_id="", special_requests="", hold_token=None):
        max_retries = 3

        for attempt in range(max_retries):
            try:
                with transaction.atomic():
                    locked_property = Property.objects.select_for_update().get(
                        pk=property.pk
                    )

                    now = timezone.now()

                    if expires_at <= now:
                        raise ValidationError(
                            "La retención ha caducado. Selecciona las fechas de nuevo."
                        )

                    if not hold_token:
                        raise ValidationError(
                            "Es necesaria una retención válida para crear la reserva."
                        )

                    hold = BookingHold.objects.select_for_update().filter(
                        token=hold_token,
                        property=locked_property,
                        initial_date=initial_date,
                        final_date=final_date,
                        expires_at__gt=now,
                    ).first()

                    if hold is None:
                        raise ValidationError(
                            "La retención ha caducado o ya no es válida."
                        )

                    if hold.expires_at != expires_at:
                        raise ValidationError(
                            "El vencimiento de la retención no coincide."
                        )

                    holds = BookingHold.objects.filter(
                        property=locked_property,
                        initial_date__lt=final_date,
                        final_date__gt=initial_date,
                        expires_at__gt=now,
                    ).exclude(token=hold.token)

                    if holds.exists():
                        raise ValidationError(
                            "Estas fechas están retenidas por otra sesión."
                        )

                    booking = cls.objects.create(
                        tenant=tenant,
                        property=locked_property,
                        initial_date=initial_date,
                        final_date=final_date,
                        status="PENDING",
                        expires_at=expires_at,
                        guest_first_name=guest_first_name,
                        guest_last_name=guest_last_name,
                        guest_email=guest_email,
                        guest_phone_number=guest_phone_number,
                        guest_country=guest_country,
                        guest_region=guest_region,
                        guest_city=guest_city,
                        guest_postal_code=guest_postal_code,
                        guest_address=guest_address,
                        is_for_self=is_for_self,
                        is_business_trip=is_business_trip,
                        tax_id=tax_id,
                        guest_count=guest_count,
                        special_requests=special_requests,
                        arrival_time=arrival_time,
                    )

                    availability = PropertyAvailability.get_for_range(
                        property,
                        initial_date,
                        final_date,
                    )

                    BookingNight.objects.bulk_create(
                        [
                            BookingNight(
                                booking=booking,
                                date=night["date"],
                                price_per_night=night["price_per_night"],
                            )
                            for night in availability
                        ]
                    )

                    return booking

            except OperationalError as exc:
                # PostgreSQL: 40P01 = deadlock_detected
                cause = exc.__cause__

                sqlstate = (
                    getattr(cause, "sqlstate", None)
                    or getattr(cause, "pgcode", None)
                )

                if sqlstate != "40P01":
                    raise

                if attempt == max_retries - 1:
                    raise

                # Pequeña espera aleatoria para evitar que ambos hilos
                # vuelvan a chocar inmediatamente.
                time.sleep(random.uniform(0.05, 0.20))

    @python_property
    def total_price(self):
        return sum(
            (night.price_per_night for night in self.nights.all()),
            Decimal("0"),
        )

    class Meta:
        verbose_name = "Reserva"
        verbose_name_plural = "Reservas"
        constraints = [
            models.CheckConstraint(
                condition=Q(initial_date__lt=F("final_date")),
                name="booking_valid_date_range",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(status="PENDING")
                    | Q(expires_at__isnull=False)
                ),
                name="booking_pending_requires_expiration",
            ),
            ExclusionConstraint(
                name="booking_no_concurrent_inventory_overlap",
                condition=(
                    Q(initial_date__lt=F("final_date"))
                    & Q(status__in=["PENDING", "CONFIRMED"])
                ),
                expressions=[
                    (
                        BookingDateRange(
                            "initial_date",
                            "final_date",
                        ),
                        RangeOperators.OVERLAPS,
                    ),
                    (
                        F("property"),
                        RangeOperators.EQUAL,
                    ),
                    (
                        BookingInventoryRange(),
                        RangeOperators.OVERLAPS,
                    ),
                ],
            ),
        ]

    def __str__(self):
        return f"Reserva de {self.tenant} en {self.property.title}"

    def clean(self):
        # Primero validamos que las fechas tengan sentido
        if self.initial_date >= self.final_date:
            raise ValidationError("La fecha de salida debe ser posterior a la de entrada.")
        
        min_allowed_date = date.today() + timedelta(
            days=self.property.notice_period_days
        )

        # Comprobamos que la fecha inicial cumpla con la antelación exigida por el propietario de la vivienda
        if self.initial_date < min_allowed_date:
            raise ValidationError("La fecha de entrada debe cumplir con la antelación exigida por el propietario de la vivienda.")

        # El dueño no puede reservar su propiedad
        if self.tenant is not None and self.tenant == self.property.owner:
            raise ValidationError("No puedes reservar tu propia vivienda.")

        if self.guest_count < 1:
            raise ValidationError("El número de huéspedes debe ser al menos 1.")

        if self.is_business_trip and not self.tax_id:
            raise ValidationError(
                "El CIF es obligatorio para las reservas por viaje de trabajo."
            )

        total_nights = (self.final_date - self.initial_date).days

        availability = PropertyAvailability.get_for_range(
            self.property,
            self.initial_date,
            self.final_date
        )

        closed_dates = [
            day["date"]
            for day in availability
            if day["status"] == "CLOSED"
        ]

        if closed_dates:
            raise ValidationError(
                "El alojamiento no está disponible en todas las fechas seleccionadas."
            )

        arrival_availability = PropertyAvailability.get_for_date(
            self.property,
            self.initial_date
        )

        if total_nights < arrival_availability["min_nights"]:
            raise ValidationError(
                f"La estancia debe ser de al menos "
                f"{arrival_availability['min_nights']} noches."
            )

        if self.status == "PENDING":
            if self.expires_at is None:
                raise ValidationError(
                    "Una reserva pendiente debe tener una fecha de expiración."
                )

            if self.expires_at <= timezone.now():
                raise ValidationError(
                    "La fecha de expiración debe ser posterior al momento actual."
                )

            if self.expires_at <= self.created_at:
                raise ValidationError(
                    "La fecha de expiración debe ser posterior a la fecha de creación."
                )

        # Buscamos reservas existentes que choquen.
        # Una reserva CONFIRMED siempre bloquea.
        # Una reserva PENDING solo bloquea mientras no haya expirado.
        now = timezone.now()

        bookings = Booking.objects.filter(
            property=self.property,
            initial_date__lt=self.final_date,
            final_date__gt=self.initial_date,
        ).filter(
            Q(status="CONFIRMED")
            |
            Q(
                status="PENDING",
                expires_at__gt=now,
            )
        )

        if self.pk:
            bookings = bookings.exclude(pk=self.pk)

        if bookings.exists():
            raise ValidationError(
                "Ya hay una reserva en esas fechas"
            )

    def validate_constraints(self, exclude=None):
        exclude = exclude or set()

        for constraint in self._meta.constraints:
            # Django no puede validar correctamente esta ExclusionConstraint
            # dinámica en Python sobre instancias nuevas. PostgreSQL la aplica
            # como garantía definitiva de concurrencia.
            if constraint.name == "booking_no_concurrent_inventory_overlap":
                continue

            constraint.validate(
                self.__class__,
                self,
                exclude=exclude,
            )
    
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

class BookingChangeProposal(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ACCEPTED = "ACCEPTED", "Accepted"
        REJECTED = "REJECTED", "Rejected"
        EXPIRED = "EXPIRED", "Expired"
        
    original_booking_snapshot = models.JSONField(
        null=True,
        blank=True,
    )
    booking = models.ForeignKey(
        Booking,
        on_delete=models.CASCADE,
        related_name="change_proposals",
    )
    proposed_initial_date = models.DateField()
    proposed_final_date = models.DateField()
    proposed_guest_count = models.PositiveIntegerField()
    proposed_total_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    proposed_nightly_prices = models.JSONField(default=list, blank=True)

    access_token_hash = models.CharField(
        max_length=64,
        unique=True,
        null=True,
        blank=True,
        editable=False,
    )

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(
        default=timezone.now,
        editable=False,
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["booking"],
                condition=Q(status="PENDING"),
                name="one_pending_change_proposal_per_booking",
            ),
            models.CheckConstraint(
                condition=Q(proposed_initial_date__lt=models.F("proposed_final_date")),
                name="change_proposal_valid_date_range",
            ),
            models.CheckConstraint(
                condition=Q(proposed_guest_count__gte=1),
                name="change_proposal_positive_guest_count",
            ),
        ]
        ordering = ["-created_at"]

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.proposed_initial_date
            and self.proposed_final_date
            and self.proposed_initial_date >= self.proposed_final_date
        ):
            errors["proposed_final_date"] = (
                "The check-out date must be after the check-in date."
            )

        if self.proposed_guest_count is not None:
            if self.proposed_guest_count < 1:
                errors["proposed_guest_count"] = (
                    "At least one guest is required."
                )
            elif self.booking_id and self.booking.property_id:
                property_obj = self.booking.property
                capacity = property_obj.adults + property_obj.children

                if self.proposed_guest_count > capacity:
                    errors["proposed_guest_count"] = (
                        f"This property accommodates at most {capacity} guests."
                    )

        if self.created_at and self.expires_at:
            if self.expires_at <= self.created_at:
                errors["expires_at"] = (
                    "The expiration time must be after the creation time."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.created_at is None:
            self.created_at = timezone.now()

        if self.expires_at is None:
            self.expires_at = self.created_at + timedelta(hours=48)

        # Al cambiar únicamente el estado de una propuesta existente,
        # no volver a validar la fecha de caducidad.
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            update_fields = set(update_fields)
            kwargs["update_fields"] = update_fields

            if update_fields.issubset({"status"}):
                return super().save(*args, **kwargs)

        self.full_clean()
        super().save(*args, **kwargs)
    
    def calculate_price_snapshot(self):
        nightly_rates = PropertyAvailability.get_for_range(
            self.booking.property,
            self.proposed_initial_date,
            self.proposed_final_date,
        )

        nightly_prices = [
            {
                "date": item["date"].isoformat(),
                "price_per_night": str(item["price_per_night"]),
            }
            for item in nightly_rates
        ]

        total = sum(
            (item["price_per_night"] for item in nightly_rates),
            Decimal("0.00"),
        )

        return nightly_prices, total

    def is_expired(self):
        return (
            self.status == self.Status.PENDING
            and self.expires_at is not None
            and timezone.now() >= self.expires_at
        )

    @classmethod
    def expire_pending_proposals(cls):
        now = timezone.now()

        # Solo obtenemos candidatas; el estado definitivo se valida después de adquirir los bloqueos.
        proposal_ids = list(
            cls.objects.filter(
                status=cls.Status.PENDING,
                expires_at__isnull=False,
                expires_at__lte=now,
            ).values_list("pk", flat=True)
        )

        expired_count = 0

        for proposal_id in proposal_ids:
            with transaction.atomic():
                # Leer la FK sin bloquear la propuesta para mantener el orden Booking -> BookingChangeProposal.
                booking_id = (
                    cls.objects.filter(pk=proposal_id)
                    .values_list("booking_id", flat=True)
                    .first()
                )

                if booking_id is None:
                    continue

                booking = (
                    Booking.objects.select_for_update()
                    .filter(pk=booking_id)
                    .first()
                )

                if booking is None:
                    continue

                proposal = (
                    cls.objects.select_for_update()
                    .filter(pk=proposal_id)
                    .first()
                )

                if proposal is None:
                    continue

                # Revalidar tras esperar por los bloqueos.
                if (
                    proposal.status != cls.Status.PENDING
                    or proposal.expires_at is None
                    or proposal.expires_at > timezone.now()
                ):
                    continue

                proposal.status = cls.Status.EXPIRED
                proposal.save(update_fields=["status"])
                expired_count += 1

        return expired_count

    def __str__(self):
        return f"Change proposal for booking {self.booking_id} ({self.status})"

class BookingChangeAudit(models.Model):
    booking = models.ForeignKey(
        Booking,
        on_delete=models.PROTECT,
        related_name="change_audits",
    )
    actor = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="booking_change_audits",
    )
    changed_at = models.DateTimeField(auto_now_add=True)
    before_values = models.JSONField()
    after_values = models.JSONField()

    class Meta:
        ordering = ["-changed_at"]

    def __str__(self):
        return (
            f"Booking change audit #{self.pk} "
            f"for booking #{self.booking_id}"
        )

class BookingNight(models.Model):
    booking = models.ForeignKey(
        Booking,
        on_delete=models.CASCADE,
        related_name="nights",
    )
    date = models.DateField()
    price_per_night = models.DecimalField(
        max_digits=7,
        decimal_places=2,
    )

    def __str__(self):
        return f"{self.booking} - {self.date}"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["booking", "date"],
                name="unique_booking_night_date",
            ),
        ]

class PropertyAvailability(models.Model):
    STATUS_CHOICES = [
        ("OPEN", "Open"),
        ("CLOSED", "Closed"),
    ]

    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name="availability",
    )
    date = models.DateField()
    price_per_night = models.DecimalField(
        max_digits=7,
        decimal_places=2,
    )
    status = models.CharField(
        max_length=6,
        choices=STATUS_CHOICES,
    )
    min_nights = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["property", "date"],
                name="unique_property_availability_date",
            ),
        ]
    
    @classmethod
    def get_for_date(cls, property, date):
        availability = cls.objects.filter(
            property=property,
            date=date,
        ).first()

        if availability:
            return {
                "price_per_night": availability.price_per_night,
                "status": availability.status,
                "min_nights": availability.min_nights,
            }

        return {
            "price_per_night": property.default_price_per_night,
            "status": "OPEN",
            "min_nights": property.default_min_nights,
        }

    @classmethod
    def get_for_range(cls, property, start_date, end_date):
        overrides = cls.objects.filter(
            property=property,
            date__gte=start_date,
            date__lt=end_date,
        )

        overrides_by_date = {
            availability.date: availability
            for availability in overrides
        }

        availability = []

        current_date = start_date

        while current_date < end_date:
            override = overrides_by_date.get(current_date)

            if override:
                availability.append({
                    "date": current_date,
                    "price_per_night": override.price_per_night,
                    "status": override.status,
                    "min_nights": override.min_nights,
                })
            else:
                availability.append({
                    "date": current_date,
                    "price_per_night": property.default_price_per_night,
                    "status": "OPEN",
                    "min_nights": property.default_min_nights,
                })

            current_date += timedelta(days=1)

        return availability

    def clean(self):
        super().clean()

        errors = {}

        if self.price_per_night in (None, ""):
            errors["price_per_night"] = (
                "El precio por noche debe ser mayor que 0"
            )
        else:
            try:
                price = Decimal(str(self.price_per_night))
                if not price.is_finite() or price <= 0:
                    errors["price_per_night"] = (
                        "El precio por noche debe ser mayor que 0"
                    )
            except (InvalidOperation, TypeError, ValueError):
                errors["price_per_night"] = (
                    "Introduce un precio por noche válido"
                )

        if isinstance(self.min_nights, bool):
            errors["min_nights"] = (
                "El número mínimo de noches debe ser al menos 1"
            )
        else:
            try:
                min_nights = int(self.min_nights)
                if str(min_nights) != str(self.min_nights).strip() or min_nights < 1:
                    errors["min_nights"] = (
                        "El número mínimo de noches debe ser al menos 1"
                    )
            except (TypeError, ValueError):
                errors["min_nights"] = (
                    "El número mínimo de noches debe ser al menos 1"
                )

        if self.date is not None and self.date < date.today():
            errors["date"] = (
                "No se puede configurar la disponibilidad de una fecha pasada"
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

class BookingHold(models.Model):
    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name="booking_holds",
    )
    initial_date = models.DateField()
    final_date = models.DateField()
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    expires_at = models.DateTimeField()


    class Meta:
        indexes = [
            models.Index(fields=["property", "expires_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(initial_date__lt=F("final_date")),
                name="booking_hold_valid_date_range",
            ),
            ExclusionConstraint(
                name="booking_hold_no_concurrent_overlap",
                condition=Q(initial_date__lt=F("final_date")),
                expressions=[
                    (
                        BookingDateRange(
                            "initial_date",
                            "final_date",
                        ),
                        RangeOperators.OVERLAPS,
                    ),
                    (
                        F("property"),
                        RangeOperators.EQUAL,
                    ),
                    (
                        BookingHoldInventoryRange(),
                        RangeOperators.OVERLAPS,
                    ),
                ],
            ),
        ]

    def is_expired(self):
        return self.expires_at <= timezone.now()

    def __str__(self):
        return (
            f"Retención {self.property_id}: "
            f"{self.initial_date} - {self.final_date}"
        )