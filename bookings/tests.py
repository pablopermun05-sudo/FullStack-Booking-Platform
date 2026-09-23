from django.test import TestCase
from django.urls import reverse
from .models import User, Property, Booking, PropertyAvailability
from datetime import date, timedelta
from django.core.exceptions import ValidationError
from django.db import IntegrityError

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
            default_price_per_night=100,
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
            default_price_per_night=10,
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
            default_price_per_night=0,
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
            default_price_per_night=-10,
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
            default_price_per_night=50,
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
            default_price_per_night=50,
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
            default_price_per_night=50,
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
            default_price_per_night=80,
            image="test.jpg",
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

class PropertyAvailabilityTestCase(TestCase):

    def setUp(self):
        self.owner = User.objects.create_user(
            username="availability_owner",
            email="availability_owner@test.com",
            password="123"
        )

        self.property = Property.objects.create(
            title="Casa Disponibilidad",
            description="Desc",
            location="Madrid",
            default_price_per_night=100,
            image="test.jpg",
            children=2,
            adults=2,
            rooms=2,
            owner=self.owner
        )

    # Test that a valid availability configuration passes validation
    def test_valid_availability(self):
        availability = PropertyAvailability(
            property=self.property,
            date=date.today(),
            price_per_night=120,
            status="OPEN",
            min_nights=2,
        )

        try:
            availability.full_clean()
        except ValidationError:
            self.fail("Should not raise ValidationError")

    # Test that an availability cannot have a price of zero
    def test_invalid_availability_price_zero(self):
        availability = PropertyAvailability(
            property=self.property,
            date=date.today(),
            price_per_night=0,
            status="OPEN",
            min_nights=1,
        )

        with self.assertRaises(ValidationError):
            availability.full_clean()

    # Test that an availability cannot have a negative price
    def test_invalid_availability_negative_price(self):
        availability = PropertyAvailability(
            property=self.property,
            date=date.today(),
            price_per_night=-10,
            status="OPEN",
            min_nights=1,
        )

        with self.assertRaises(ValidationError):
            availability.full_clean()

    # Test that the minimum number of nights must be at least 1
    def test_invalid_availability_min_nights(self):
        availability = PropertyAvailability(
            property=self.property,
            date=date.today(),
            price_per_night=120,
            status="OPEN",
            min_nights=0,
        )

        with self.assertRaises(ValidationError):
            availability.full_clean()

    # Test that past dates cannot be configured
    def test_invalid_availability_past_date(self):
        availability = PropertyAvailability(
            property=self.property,
            date=date.today() - timedelta(days=1),
            price_per_night=120,
            status="OPEN",
            min_nights=1,
        )

        with self.assertRaises(ValidationError):
            availability.full_clean()

    # Test that the property defaults are returned when there is no override
    def test_get_for_date_returns_property_defaults(self):
        availability = PropertyAvailability.get_for_date(
            self.property,
            date.today(),
        )

        self.assertEqual(
            availability["price_per_night"],
            self.property.default_price_per_night,
        )
        self.assertEqual(availability["status"], "OPEN")
        self.assertEqual(
            availability["min_nights"],
            self.property.default_min_nights,
        )

    # Test that an override is returned when one exists for the requested date
    def test_get_for_date_returns_override(self):
        PropertyAvailability.objects.create(
            property=self.property,
            date=date.today(),
            price_per_night=150,
            status="CLOSED",
            min_nights=3,
        )

        availability = PropertyAvailability.get_for_date(
            self.property,
            date.today(),
        )

        self.assertEqual(availability["price_per_night"], 150)
        self.assertEqual(availability["status"], "CLOSED")
        self.assertEqual(availability["min_nights"], 3)

    # Test that a range returns both property defaults and date overrides
    def test_get_for_range_returns_defaults_and_overrides(self):
        start_date = date.today()
        end_date = start_date + timedelta(days=3)

        PropertyAvailability.objects.create(
            property=self.property,
            date=start_date + timedelta(days=1),
            price_per_night=150,
            status="CLOSED",
            min_nights=3,
        )

        availability = PropertyAvailability.get_for_range(
            self.property,
            start_date,
            end_date,
        )

        self.assertEqual(len(availability), 3)

        # The first day has no override, so property defaults are returned
        self.assertEqual(
            availability[0]["price_per_night"],
            self.property.default_price_per_night,
        )
        self.assertEqual(availability[0]["status"], "OPEN")

        # The second day has an override
        self.assertEqual(availability[1]["price_per_night"], 150)
        self.assertEqual(availability[1]["status"], "CLOSED")
        self.assertEqual(availability[1]["min_nights"], 3)

        # The third day has no override, so property defaults are returned
        self.assertEqual(
            availability[2]["price_per_night"],
            self.property.default_price_per_night,
        )
        self.assertEqual(availability[2]["status"], "OPEN")

    # Test that price cannot exceed the maximum allowed value
    def test_invalid_availability_price_exceeds_max(self):
        availability = PropertyAvailability(
            property=self.property,
            date=date.today(),
            price_per_night=100000,
            status="OPEN",
            min_nights=1,
        )

        with self.assertRaises(ValidationError):
            availability.full_clean()

    # Test that a property cannot have duplicate availability records for the same date
    def test_unique_property_availability_date(self):
        PropertyAvailability.objects.create(
            property=self.property,
            date=date.today(),
            price_per_night=120,
            status="OPEN",
            min_nights=1,
        )

        with self.assertRaises(IntegrityError):
            PropertyAvailability.objects.create(
                property=self.property,
                date=date.today(),
                price_per_night=130,
                status="CLOSED",
                min_nights=2,
            )

    def test_save_availability_rejects_past_date(self):
        self.client.force_login(self.owner)

        past_date = date.today() - timedelta(days=1)

        response = self.client.post(
            reverse(
                "property_availability_save",
                kwargs={"property_id": self.property.pk},
            ),
            {
                "start_date": past_date.isoformat(),
                "end_date": past_date.isoformat(),
                "status": "OPEN",
                "min_nights": "1",
                "price_per_night": "150",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "Cannot modify availability for past dates",
        )

        self.assertFalse(
            PropertyAvailability.objects.filter(
                property=self.property,
                date=past_date,
            ).exists()
        )

    def test_save_availability_rejects_booked_dates(self):
        tenant = User.objects.create_user(
            username="availability_tenant",
            email="availability_tenant@test.com",
            password="123",
        )

        booking_start = date.today() + timedelta(days=5)
        booking_end = booking_start + timedelta(days=3)

        Booking.objects.create(
            tenant=tenant,
            property=self.property,
            initial_date=booking_start,
            final_date=booking_end,
        )

        self.client.force_login(self.owner)

        response = self.client.post(
            reverse(
                "property_availability_save",
                kwargs={"property_id": self.property.pk},
            ),
            {
                "start_date": booking_start.isoformat(),
                "end_date": booking_start.isoformat(),
                "status": "CLOSED",
                "min_nights": "2",
                "price_per_night": "150",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "No se pueden modificar días que tienen reservas.",
        )

        self.assertFalse(
            PropertyAvailability.objects.filter(
                property=self.property,
                date=booking_start,
            ).exists()
        )

    def test_save_availability_rejects_non_owner(self):
        user = User.objects.create_user(
            username="availability_user",
            email="availability_user@test.com",
            password="123",
        )

        self.client.force_login(user)

        start_date = date.today() + timedelta(days=5)

        response = self.client.post(
            reverse(
                "property_availability_save",
                kwargs={"property_id": self.property.pk},
            ),
            {
                "start_date": start_date.isoformat(),
                "end_date": start_date.isoformat(),
                "status": "CLOSED",
                "min_nights": "2",
                "price_per_night": "150",
            },
        )

        self.assertEqual(response.status_code, 403)

        self.assertFalse(
            PropertyAvailability.objects.filter(
                property=self.property,
                date=start_date,
            ).exists()
        )

    def test_save_availability_rejects_get_request(self):
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse(
                "property_availability_save",
                kwargs={"property_id": self.property.pk},
            )
        )

        self.assertEqual(response.status_code, 405)
        self.assertEqual(
            response.json()["error"],
            "Method not allowed",
        )

    def test_save_availability_updates_range(self):
        self.client.force_login(self.owner)

        start_date = date.today() + timedelta(days=5)
        end_date = start_date + timedelta(days=2)

        response = self.client.post(
            reverse(
                "property_availability_save",
                kwargs={"property_id": self.property.pk},
            ),
            {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "status": "CLOSED",
                "min_nights": "3",
                "price_per_night": "150",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["updated_count"], 3)

        availability = PropertyAvailability.objects.filter(
            property=self.property,
            date__range=[start_date, end_date],
        ).order_by("date")

        self.assertEqual(availability.count(), 3)

        for item in availability:
            self.assertEqual(item.status, "CLOSED")
            self.assertEqual(item.min_nights, 3)
            self.assertEqual(item.price_per_night, 150)

    def test_save_availability_allows_staff_user(self):
        staff_user = User.objects.create_user(
            username="availability_staff",
            email="availability_staff@test.com",
            password="123",
            is_staff=True,
        )

        self.client.force_login(staff_user)

        start_date = date.today() + timedelta(days=5)

        response = self.client.post(
            reverse(
                "property_availability_save",
                kwargs={"property_id": self.property.pk},
            ),
            {
                "start_date": start_date.isoformat(),
                "end_date": start_date.isoformat(),
                "status": "CLOSED",
                "min_nights": "2",
                "price_per_night": "150",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["updated_count"], 1)

        availability = PropertyAvailability.objects.get(
            property=self.property,
            date=start_date,
        )

        self.assertEqual(availability.status, "CLOSED")
        self.assertEqual(availability.min_nights, 2)
        self.assertEqual(availability.price_per_night, 150)

    def test_save_availability_rejects_invalid_date_range(self):
        self.client.force_login(self.owner)

        start_date = date.today() + timedelta(days=10)
        end_date = start_date - timedelta(days=1)

        response = self.client.post(
            reverse(
                "property_availability_save",
                kwargs={"property_id": self.property.pk},
            ),
            {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "status": "OPEN",
                "min_nights": "1",
                "price_per_night": "150",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "Start date must be before or equal to end date",
        )

        self.assertFalse(
            PropertyAvailability.objects.filter(
                property=self.property,
            ).exists()
        )

    def test_save_availability_rejects_invalid_status(self):
        self.client.force_login(self.owner)

        start_date = date.today() + timedelta(days=5)

        response = self.client.post(
            reverse(
                "property_availability_save",
                kwargs={"property_id": self.property.pk},
            ),
            {
                "start_date": start_date.isoformat(),
                "end_date": start_date.isoformat(),
                "status": "INVALID",
                "min_nights": "1",
                "price_per_night": "150",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "Invalid status",
        )

        self.assertFalse(
            PropertyAvailability.objects.filter(
                property=self.property,
                date=start_date,
            ).exists()
        )