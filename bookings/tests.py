from django.test import TestCase
from .models import User, Property, Booking
from datetime import date, timedelta
from django.core.exceptions import ValidationError


class PropertyTestCase(TestCase):

    def setUp(self):
        self.u1 = User.objects.create_user(
            username="owner1",
            email="o1@test.com",
            password="123"
        )
        self.u2 = User.objects.create_user(
            username="tenant1",
            email="t1@test.com",
            password="123"
        )

        self.p1 = Property(
            title="Apartamento Centro",
            description="Desc",
            location="Madrid",
            image="test.jpg",
            price_per_night=100,
            children=2,
            adults=2,
            rooms=2,
            notice_period_days=0,
            owner=self.u1
        )

        self.p2 = Property(
            title="Estudio",
            description="Desc",
            location="Madrid",
            image="test.jpg",
            price_per_night=10,
            children=0,
            adults=1,
            rooms=1,
            notice_period_days=3,
            owner=self.u1
        )

        self.p_free = Property(
            title="Error Precio",
            description="Desc",
            location="Madrid",
            image="test.jpg",
            price_per_night=0,
            children=0,
            adults=1,
            rooms=1,
            notice_period_days=0,
            owner=self.u1
        )

        self.p_negative = Property(
            title="Error Negativo",
            description="Desc",
            location="Madrid",
            image="test.jpg",
            price_per_night=-10,
            children=0,
            adults=1,
            rooms=1,
            notice_period_days=0,
            owner=self.u1
        )

        self.p_no_adults = Property(
            title="Error Adultos",
            description="Desc",
            location="Madrid",
            image="test.jpg",
            price_per_night=50,
            children=0,
            adults=0,
            rooms=1,
            notice_period_days=0,
            owner=self.u1
        )

        self.p_no_rooms = Property(
            title="Error Cuartos",
            description="Desc",
            location="Madrid",
            image="test.jpg",
            price_per_night=50,
            children=0,
            adults=2,
            rooms=0,
            notice_period_days=0,
            owner=self.u1
        )
        
        # Nueva propiedad de prueba para validar que no sea negativa la antelación
        self.p_negative_notice = Property(
            title="Error Antelación Negativa",
            description="Desc",
            location="Madrid",
            image="test.jpg",
            price_per_night=50,
            children=0,
            adults=2,
            rooms=1,
            notice_period_days=-5,  # Valor inválido
            owner=self.u1
        )

    def test_valid_property(self):
        try:
            self.p1.full_clean()
            self.p2.full_clean()
        except ValidationError:
            self.fail("Should not raise ValidationError")

    def test_invalid_property_free_price(self):
        with self.assertRaises(ValidationError):
            self.p_free.full_clean()

    def test_invalid_property_negative_price(self):
        with self.assertRaises(ValidationError):
            self.p_negative.full_clean()

    def test_invalid_property_adults(self):
        with self.assertRaises(ValidationError):
            self.p_no_adults.full_clean()

    def test_invalid_property_rooms(self):
        with self.assertRaises(ValidationError):
            self.p_no_rooms.full_clean()

    #Verifica que la base de datos o el validador rechacen antelaciones negativas
    def test_invalid_property_negative_notice_days(self):
        with self.assertRaises(ValidationError):
            self.p_negative_notice.full_clean()

class BookingTestCase(TestCase):

    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner",
            email="owner@test.com",
            password="123"
        )

        self.tenant = User.objects.create_user(
            username="tenant",
            email="tenant@test.com",
            password="123"
        )

        self.property = Property.objects.create(
            title="Casa Rural",
            description="Desc",
            location="Madrid",
            image="test.jpg",
            price_per_night=80,
            children=2,
            adults=2,
            rooms=2,
            owner=self.owner
        )

        self.booking1 = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today(),
            final_date=date.today() + timedelta(days=3)
        )
        self.booking2 = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today(),
            final_date=date.today() + timedelta(days=3)
        )

    def test_valid_booking(self):
        try:
            self.booking1.full_clean()
        except ValidationError:
            self.fail("Should not raise ValidationError")

    def test_overlap_booking(self):
        # Repito el código anterior para que me de error de solapamiento
        try:
            self.booking1.full_clean()
            self.booking1.save()
            self.booking2.full_clean()
            self.fail("Should raise ValidationError")
        except ValidationError:
            pass

    # Test que verifica que una reserva puede empezar el mismo día que otra termina
    def test_overlap_booking_sharing_checkout_day(self):
        self.booking1.save()

        # Esta reserva empieza justo el día que la anterior se va
        booking_same_day = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=self.booking1.final_date,
            final_date=self.booking1.final_date + timedelta(days=2),
        )
        try:
            booking_same_day.full_clean()
        except ValidationError:
            self.fail(
                "Debería permitir reservar si el check-in coincide con el check-out de otra reserva."
            )

    # Test que verifica que se respeta el periodo de antelación de la propiedad
    def test_booking_notice_period_error(self):
        # Forzamos que la propiedad pida 3 días de antelación
        self.property.notice_period_days = 3
        self.property.save()

        # Intentamos reservar para mañana (solo 1 día de antelación)
        invalid_booking = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=1),
            final_date=date.today() + timedelta(days=3),
        )

        with self.assertRaises(ValidationError):
            invalid_booking.full_clean()

    def test_owner_cannot_book_own_property(self):
        booking_by_owner = Booking(
            tenant=self.owner,  # El propietario intenta reservar
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
        )
        with self.assertRaises(ValidationError):
            booking_by_owner.full_clean()

    def test_invalid_booking_dates(self):
        booking = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=3),
        )

        with self.assertRaises(ValidationError):
            booking.full_clean()

    def test_booking_same_checkin_checkout_date(self):
        booking = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=5),
        )

        with self.assertRaises(ValidationError):
            booking.full_clean()