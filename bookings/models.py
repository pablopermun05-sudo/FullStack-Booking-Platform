from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.db import models
from phonenumber_field.modelfields import PhoneNumberField
from django.core.exceptions import ValidationError
from datetime import date, timedelta

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

class Booking(models.Model):
    tenant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bookings")
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="bookings")
    initial_date = models.DateField()
    final_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Reserva"
        verbose_name_plural = "Reservas"

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
        if self.tenant == self.property.owner:
            raise ValidationError("No puedes reservar tu propia vivienda.")

        # Buscamos reservas existentes que choquen
        bookings = Booking.objects.filter(
            property=self.property,
            initial_date__lt=self.final_date,
            final_date__gt=self.initial_date
        )

        # Si el objeto ya existe en la BD (es una edición), lo excluimos del chequeo
        if self.pk:
            bookings = bookings.exclude(pk=self.pk)

        if bookings.exists():
            raise ValidationError("Ya hay una reserva en esas fechas")
    
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

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
        availability = []

        current_date = start_date

        while current_date < end_date:
            availability.append({
                "date": current_date,
                **cls.get_for_date(property, current_date),
            })

            current_date += timedelta(days=1)

        return availability

    def clean(self):
        if self.price_per_night <= 0:
            raise ValidationError(
                "El precio por noche debe ser mayor que 0"
            )

        if self.min_nights < 1:
            raise ValidationError(
                "El número mínimo de noches debe ser al menos 1"
            )

        if self.date < date.today():
            raise ValidationError(
                "No se puede configurar la disponibilidad de una fecha pasada"
            )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["property", "date"],
                name="unique_property_availability_date",
            ),
        ]