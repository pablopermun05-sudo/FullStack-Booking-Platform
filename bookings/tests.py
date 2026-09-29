from django.test import TestCase
from django.urls import reverse
from .models import User, OwnerProfile, Property, Booking, PropertyAvailability, can_manage_properties
from django.contrib.auth.models import AnonymousUser
from datetime import date, timedelta
from django.core.exceptions import ValidationError
from django.utils import timezone

class OwnerProfileTestCase(TestCase):
    def test_owner_profile_is_pending_by_default(self):
        user = User.objects.create_user(
            username="owner",
            password="password123",
            email="owner@example.com",
            first_name="Owner",
            last_name="User",
        )

        owner_profile = OwnerProfile.objects.create(user=user)

        self.assertEqual(owner_profile.status, "PENDING")
        self.assertEqual(owner_profile.get_status_display(), "Pendiente")
        self.assertIsNotNone(owner_profile.created_at)
        self.assertIsNone(owner_profile.reviewed_at)

    def test_owner_profile_has_one_to_one_relationship_with_user(self):
        user = User.objects.create_user(
            username="owner",
            password="password123",
            email="owner@example.com",
            first_name="Owner",
            last_name="User",
        )

        owner_profile = OwnerProfile.objects.create(user=user)

        self.assertEqual(user.owner_profile, owner_profile)

    def test_owner_profile_can_be_approved(self):
        user = User.objects.create_user(
            username="owner",
            password="password123",
            email="owner@example.com",
            first_name="Owner",
            last_name="User",
        )

        owner_profile = OwnerProfile.objects.create(user=user)

        owner_profile.status = "APPROVED"
        owner_profile.reviewed_at = timezone.now()
        owner_profile.save()

        owner_profile.refresh_from_db()

        self.assertEqual(owner_profile.status, "APPROVED")
        self.assertIsNotNone(owner_profile.reviewed_at)

    def test_owner_profile_can_be_rejected(self):
        user = User.objects.create_user(
            username="owner",
            password="password123",
            email="owner@example.com",
            first_name="Owner",
            last_name="User",
        )

        owner_profile = OwnerProfile.objects.create(user=user)

        owner_profile.status = "REJECTED"
        owner_profile.reviewed_at = timezone.now()
        owner_profile.save()

        owner_profile.refresh_from_db()

        self.assertEqual(owner_profile.status, "REJECTED")
        self.assertIsNotNone(owner_profile.reviewed_at)

class OwnerPermissionTestCase(TestCase):
    def test_user_without_owner_profile_is_not_approved_owner(self):
        user = User.objects.create_user(
            username="customer",
            password="password123",
            email="customer@example.com",
            first_name="Customer",
            last_name="User",
        )

        self.assertFalse(user.is_approved_owner)

    def test_pending_owner_is_not_approved_owner(self):
        user = User.objects.create_user(
            username="owner",
            password="password123",
            email="owner@example.com",
            first_name="Owner",
            last_name="User",
        )

        OwnerProfile.objects.create(
            user=user,
            status="PENDING",
        )

        self.assertFalse(user.is_approved_owner)

    def test_rejected_owner_is_not_approved_owner(self):
        user = User.objects.create_user(
            username="owner",
            password="password123",
            email="owner@example.com",
            first_name="Owner",
            last_name="User",
        )

        OwnerProfile.objects.create(
            user=user,
            status="REJECTED",
        )

        self.assertFalse(user.is_approved_owner)

    def test_approved_owner_is_approved_owner(self):
        user = User.objects.create_user(
            username="owner",
            password="password123",
            email="owner@example.com",
            first_name="Owner",
            last_name="User",
        )

        OwnerProfile.objects.create(
            user=user,
            status="APPROVED",
        )

        self.assertTrue(user.is_approved_owner)

    def test_customer_cannot_manage_properties(self):
        user = User.objects.create_user(
            username="customer",
            password="password123",
            email="customer@example.com",
            first_name="Customer",
            last_name="User",
        )

        self.assertFalse(can_manage_properties(user))

    def test_pending_owner_cannot_manage_properties(self):
        user = User.objects.create_user(
            username="owner",
            password="password123",
            email="owner@example.com",
            first_name="Owner",
            last_name="User",
        )

        OwnerProfile.objects.create(
            user=user,
            status="PENDING",
        )

        self.assertFalse(can_manage_properties(user))

    def test_rejected_owner_cannot_manage_properties(self):
        user = User.objects.create_user(
            username="owner",
            password="password123",
            email="owner@example.com",
            first_name="Owner",
            last_name="User",
        )

        OwnerProfile.objects.create(
            user=user,
            status="REJECTED",
        )

        self.assertFalse(can_manage_properties(user))

    def test_approved_owner_can_manage_properties(self):
        user = User.objects.create_user(
            username="owner",
            password="password123",
            email="owner@example.com",
            first_name="Owner",
            last_name="User",
        )

        OwnerProfile.objects.create(
            user=user,
            status="APPROVED",
        )

        self.assertTrue(can_manage_properties(user))

    def test_staff_can_manage_properties(self):
        user = User.objects.create_user(
            username="staff",
            password="password123",
            email="staff@example.com",
            first_name="Staff",
            last_name="User",
            is_staff=True,
        )

        self.assertTrue(can_manage_properties(user))

    def test_superuser_can_manage_properties(self):
        user = User.objects.create_superuser(
            username="admin",
            password="password123",
            email="admin@example.com",
            first_name="Admin",
            last_name="User",
        )

        self.assertTrue(can_manage_properties(user))

    def test_anonymous_user_cannot_manage_properties(self):
        self.assertFalse(can_manage_properties(AnonymousUser()))

class RegistrationTestCase(TestCase):
    def test_customer_registration_creates_user_without_owner_profile(self):
        response = self.client.post(
            reverse("register"),
            {
                "first_name": "Customer",
                "last_name": "User",
                "username": "customer",
                "email": "customer@example.com",
                "phone_number": "+34600000000",
                "account_type": "customer",
                "password1": "StrongPassword123!",
                "password2": "StrongPassword123!",
            },
        )

        self.assertRedirects(response, reverse("index"))

        user = User.objects.get(username="customer")

        self.assertFalse(
            OwnerProfile.objects.filter(user=user).exists()
        )

    def test_owner_registration_creates_pending_owner_profile(self):
        response = self.client.post(
            reverse("register"),
            {
                "first_name": "Owner",
                "last_name": "User",
                "username": "owner",
                "email": "owner@example.com",
                "phone_number": "+34600000001",
                "account_type": "owner",
                "password1": "StrongPassword123!",
                "password2": "StrongPassword123!",
            },
        )

        self.assertRedirects(response, reverse("index"))

        user = User.objects.get(username="owner")
        owner_profile = OwnerProfile.objects.get(user=user)

        self.assertEqual(owner_profile.status, "PENDING")
        self.assertIsNone(owner_profile.reviewed_at)

    def test_owner_registration_logs_user_in(self):
        self.client.post(
            reverse("register"),
            {
                "first_name": "Owner",
                "last_name": "User",
                "username": "owner",
                "email": "owner@example.com",
                "phone_number": "+34600000002",
                "account_type": "owner",
                "password1": "StrongPassword123!",
                "password2": "StrongPassword123!",
            },
        )

        user = User.objects.get(username="owner")

        self.assertEqual(
            int(self.client.session["_auth_user_id"]),
            user.pk,
        )

    def test_customer_registration_logs_user_in(self):
        self.client.post(
            reverse("register"),
            {
                "first_name": "Customer",
                "last_name": "User",
                "username": "customer",
                "email": "customer@example.com",
                "phone_number": "+34600000003",
                "account_type": "customer",
                "password1": "StrongPassword123!",
                "password2": "StrongPassword123!",
            },
        )

        user = User.objects.get(username="customer")

        self.assertEqual(
            int(self.client.session["_auth_user_id"]),
            user.pk,
        )

    def test_invalid_account_type_does_not_create_user(self):
        response = self.client.post(
            reverse("register"),
            {
                "first_name": "Invalid",
                "last_name": "User",
                "username": "invalid",
                "email": "invalid@example.com",
                "phone_number": "+34600000004",
                "account_type": "admin",
                "password1": "StrongPassword123!",
                "password2": "StrongPassword123!",
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertFalse(
            User.objects.filter(username="invalid").exists()
        )

class PropertyManagementPermissionTestCase(TestCase):
    def create_user(self, username, email, **kwargs):
        return User.objects.create_user(
            username=username,
            password="Password123!",
            email=email,
            first_name="Test",
            last_name="User",
            **kwargs,
        )

    def create_owner(self, username, email, status):
        user = self.create_user(username, email)

        OwnerProfile.objects.create(
            user=user,
            status=status,
        )

        return user

    def create_property(self, owner):
        return Property.objects.create(
            title="Test property",
            description="Test description",
            location="Madrid",
            image="test.jpg",
            default_price_per_night=100,
            default_min_nights=1,
            children=2,
            adults=2,
            rooms=2,
            notice_period_days=0,
            allow_pets=False,
            owner=owner,
        )

    def test_customer_cannot_create_property(self):
        customer = self.create_user(
            "customer",
            "customer@example.com",
        )

        self.client.force_login(customer)

        response = self.client.get(reverse("create_property"))

        self.assertEqual(response.status_code, 403)

    def test_pending_owner_cannot_create_property(self):
        owner = self.create_owner(
            "pending",
            "pending@example.com",
            "PENDING",
        )

        self.client.force_login(owner)

        response = self.client.get(reverse("create_property"))

        self.assertEqual(response.status_code, 403)

    def test_rejected_owner_cannot_create_property(self):
        owner = self.create_owner(
            "rejected",
            "rejected@example.com",
            "REJECTED",
        )

        self.client.force_login(owner)

        response = self.client.get(reverse("create_property"))

        self.assertEqual(response.status_code, 403)

    def test_approved_owner_can_access_create_property(self):
        owner = self.create_owner(
            "approved",
            "approved@example.com",
            "APPROVED",
        )

        self.client.force_login(owner)

        response = self.client.get(reverse("create_property"))

        self.assertEqual(response.status_code, 200)

    def test_staff_can_access_create_property(self):
        staff = self.create_user(
            "staff",
            "staff@example.com",
            is_staff=True,
        )

        self.client.force_login(staff)

        response = self.client.get(reverse("create_property"))

        self.assertEqual(response.status_code, 200)

    def test_anonymous_user_can_access_property_availability_data(self):
        owner = self.create_owner(
            "owner",
            "owner@example.com",
            "APPROVED",
        )

        property = self.create_property(owner=owner)

        response = self.client.get(
            reverse(
                "property_availability_data",
                args=[property.pk],
            ),
            {
                "start_date": "2026-10-01",
                "end_date": "2026-10-03",
            },
        )

        self.assertEqual(response.status_code, 200)

    def test_owner_can_access_own_property(self):
        owner = self.create_owner(
            "owner",
            "owner@example.com",
            "APPROVED",
        )

        property = self.create_property(owner=owner)

        self.client.force_login(owner)

        response = self.client.get(
            reverse(
                "edit_property",
                args=[property.pk],
            )
        )

        self.assertEqual(response.status_code, 200)

    def test_approved_owner_cannot_access_other_owner_property(self):
        owner = self.create_owner(
            "owner",
            "owner@example.com",
            "APPROVED",
        )

        other_owner = self.create_owner(
            "other",
            "other@example.com",
            "APPROVED",
        )

        property = self.create_property(owner=other_owner)

        self.client.force_login(owner)

        response = self.client.get(
            reverse(
                "edit_property",
                args=[property.pk],
            )
        )

        self.assertEqual(response.status_code, 403)

    def test_staff_can_access_other_owner_property(self):
        staff = self.create_user(
            "staff",
            "staff@example.com",
            is_staff=True,
        )

        owner = self.create_owner(
            "owner",
            "owner@example.com",
            "APPROVED",
        )

        property = self.create_property(owner=owner)

        self.client.force_login(staff)

        response = self.client.get(
            reverse(
                "edit_property",
                args=[property.pk],
            )
        )

        self.assertEqual(response.status_code, 200)

    def test_customer_cannot_access_my_properties(self):
        customer = self.create_user(
            "customer",
            "customer@example.com",
        )

        self.client.force_login(customer)

        response = self.client.get(reverse("my_properties"))

        self.assertEqual(response.status_code, 403)

    def test_approved_owner_can_access_my_properties(self):
        owner = self.create_owner(
            "owner",
            "owner@example.com",
            "APPROVED",
        )

        self.client.force_login(owner)

        response = self.client.get(reverse("my_properties"))

        self.assertEqual(response.status_code, 200)

    def test_other_owner_cannot_access_property_availability(self):
        owner = self.create_owner(
            "owner",
            "owner@example.com",
            "APPROVED",
        )

        other_owner = self.create_owner(
            "other",
            "other@example.com",
            "APPROVED",
        )

        property = self.create_property(owner=other_owner)

        self.client.force_login(owner)

        response = self.client.get(
            reverse(
                "property_availability",
                args=[property.pk],
            )
        )

        self.assertEqual(response.status_code, 403)

    def test_property_owner_can_access_property_availability(self):
        owner = self.create_owner(
            "owner",
            "owner@example.com",
            "APPROVED",
        )

        property = self.create_property(owner=owner)

        self.client.force_login(owner)

        response = self.client.get(
            reverse(
                "property_availability",
                args=[property.pk],
            )
        )

        self.assertEqual(response.status_code, 200)

    def test_staff_can_access_other_owner_property_availability(self):
        staff = self.create_user(
            "staff",
            "staff@example.com",
            is_staff=True,
        )

        owner = self.create_owner(
            "owner",
            "owner@example.com",
            "APPROVED",
        )

        property = self.create_property(owner=owner)

        self.client.force_login(staff)

        response = self.client.get(
            reverse(
                "property_availability",
                args=[property.pk],
            )
        )

        self.assertEqual(response.status_code, 200)

    def test_other_owner_cannot_save_property_availability(self):
        owner = self.create_owner(
            "owner",
            "owner@example.com",
            "APPROVED",
        )

        other_owner = self.create_owner(
            "other",
            "other@example.com",
            "APPROVED",
        )

        property = self.create_property(owner=other_owner)

        self.client.force_login(owner)

        response = self.client.post(
            reverse(
                "property_availability_save",
                args=[property.pk],
            ),
            {
                "start_date": "2026-10-01",
                "end_date": "2026-10-03",
                "status": "OPEN",
                "min_nights": "1",
                "price_per_night": "100",
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_other_owner_cannot_reset_property_availability(self):
        owner = self.create_owner(
            "owner",
            "owner@example.com",
            "APPROVED",
        )

        other_owner = self.create_owner(
            "other",
            "other@example.com",
            "APPROVED",
        )

        property = self.create_property(owner=other_owner)

        self.client.force_login(owner)

        response = self.client.post(
            reverse(
                "property_availability_reset",
                args=[property.pk],
            ),
            {
                "start_date": "2026-10-01",
                "end_date": "2026-10-03",
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_anonymous_user_cannot_create_property(self):
        response = self.client.get(reverse("create_property"))

        self.assertEqual(response.status_code, 302)

class OwnerProfileAdminTestCase(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username="admin",
            password="password123",
            email="admin@example.com",
            first_name="Admin",
            last_name="User",
        )

        self.owner_user = User.objects.create_user(
            username="owner",
            password="password123",
            email="owner@example.com",
            first_name="Owner",
            last_name="User",
        )

        self.owner_profile = OwnerProfile.objects.create(
            user=self.owner_user,
            status="PENDING",
        )

        self.client.force_login(self.admin_user)

    def test_admin_can_access_owner_profiles(self):
        response = self.client.get(
            reverse("admin:bookings_ownerprofile_changelist")
        )

        self.assertEqual(response.status_code, 200)

    def test_admin_can_approve_owner(self):
        response = self.client.post(
            reverse("admin:bookings_ownerprofile_changelist"),
            {
                "action": "approve_owners",
                "_selected_action": [self.owner_profile.pk],
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)

        self.owner_profile.refresh_from_db()

        self.assertEqual(
            self.owner_profile.status,
            "APPROVED",
        )
        self.assertIsNotNone(
            self.owner_profile.reviewed_at,
        )

    def test_admin_can_reject_owner(self):
        response = self.client.post(
            reverse("admin:bookings_ownerprofile_changelist"),
            {
                "action": "reject_owners",
                "_selected_action": [self.owner_profile.pk],
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)

        self.owner_profile.refresh_from_db()

        self.assertEqual(
            self.owner_profile.status,
            "REJECTED",
        )
        self.assertIsNotNone(
            self.owner_profile.reviewed_at,
        )

class NavigationTestCase(TestCase):
    def create_user(self, username, email, **kwargs):
        return User.objects.create_user(
            username=username,
            password="Password123!",
            email=email,
            first_name="Test",
            last_name="User",
            **kwargs,
        )

    def create_owner(self, username, email, status):
        user = self.create_user(username, email)

        OwnerProfile.objects.create(
            user=user,
            status=status,
        )

        return user

    def test_anonymous_user_does_not_see_property_management_links(self):
        response = self.client.get(reverse("index"))

        self.assertNotContains(response, "Registrar Vivienda")
        self.assertNotContains(response, "Mis Viviendas")
        self.assertNotContains(response, "Mis Reservas")

    def test_customer_does_not_see_property_management_links(self):
        customer = self.create_user(
            "customer",
            "customer@example.com",
        )

        self.client.force_login(customer)

        response = self.client.get(reverse("index"))

        self.assertNotContains(response, "Registrar Vivienda")
        self.assertNotContains(response, "Mis Viviendas")
        self.assertContains(response, "Mis Reservas")

    def test_pending_owner_does_not_see_property_management_links(self):
        owner = self.create_owner(
            "pending",
            "pending@example.com",
            "PENDING",
        )

        self.client.force_login(owner)

        response = self.client.get(reverse("index"))

        self.assertNotContains(response, "Registrar Vivienda")
        self.assertNotContains(response, "Mis Viviendas")
        self.assertContains(response, "Mis Reservas")

    def test_rejected_owner_does_not_see_property_management_links(self):
        owner = self.create_owner(
            "rejected",
            "rejected@example.com",
            "REJECTED",
        )

        self.client.force_login(owner)

        response = self.client.get(reverse("index"))

        self.assertNotContains(response, "Registrar Vivienda")
        self.assertNotContains(response, "Mis Viviendas")
        self.assertContains(response, "Mis Reservas")

    def test_approved_owner_sees_property_management_links(self):
        owner = self.create_owner(
            "approved",
            "approved@example.com",
            "APPROVED",
        )

        self.client.force_login(owner)

        response = self.client.get(reverse("index"))

        self.assertContains(response, "Registrar Vivienda")
        self.assertContains(response, "Mis Viviendas")
        self.assertContains(response, "Mis Reservas")

    def test_staff_sees_property_management_links(self):
        staff = self.create_user(
            "staff",
            "staff@example.com",
            is_staff=True,
        )

        self.client.force_login(staff)

        response = self.client.get(reverse("index"))

        self.assertContains(response, "Registrar Vivienda")
        self.assertContains(response, "Mis Viviendas")
        self.assertContains(response, "Mis Reservas")

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

class AuthenticationTestCase(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="logout_user",
            email="logout@test.com",
            password="testpassword123",
        )

    def test_logout_rejects_non_post_request(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("logout"))

        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.json()["error"], "Method not allowed")
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_logout_logs_user_out(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse("logout"))

        self.assertRedirects(response, reverse("index"))
        self.assertFalse(response.wsgi_request.user.is_authenticated)

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

    def test_booking_rejects_closed_date(self):
        closed_date = date.today() + timedelta(days=5)

        PropertyAvailability.objects.create(
            property=self.property,
            date=closed_date,
            price_per_night=80,
            status="CLOSED",
            min_nights=1,
        )

        booking = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=closed_date,
            final_date=closed_date + timedelta(days=2),
        )

        with self.assertRaises(ValidationError):
            booking.full_clean()

    def test_booking_respects_min_nights_on_arrival_date(self):
        arrival_date = date.today() + timedelta(days=5)

        PropertyAvailability.objects.create(
            property=self.property,
            date=arrival_date,
            price_per_night=80,
            status="OPEN",
            min_nights=3,
        )

        booking = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=arrival_date,
            final_date=arrival_date + timedelta(days=2),
        )

        with self.assertRaises(ValidationError):
            booking.full_clean()

    def test_booking_accepts_arrival_date_min_nights(self):
        arrival_date = date.today() + timedelta(days=5)

        PropertyAvailability.objects.create(
            property=self.property,
            date=arrival_date,
            price_per_night=80,
            status="OPEN",
            min_nights=3,
        )

        booking = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=arrival_date,
            final_date=arrival_date + timedelta(days=3),
        )

        try:
            booking.full_clean()
        except ValidationError:
            self.fail("La reserva debería cumplir el mínimo de noches del día de llegada.")

    def test_booking_uses_only_arrival_date_min_nights(self):
        arrival_date = date.today() + timedelta(days=5)
        following_date = arrival_date + timedelta(days=1)

        PropertyAvailability.objects.create(
            property=self.property,
            date=arrival_date,
            price_per_night=80,
            status="OPEN",
            min_nights=2,
        )

        PropertyAvailability.objects.create(
            property=self.property,
            date=following_date,
            price_per_night=80,
            status="OPEN",
            min_nights=5,
        )

        booking = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=arrival_date,
            final_date=arrival_date + timedelta(days=2),
        )

        try:
            booking.full_clean()
        except ValidationError:
            self.fail(
                "El mínimo de noches debe depender únicamente "
                "del día de llegada."
            )

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

    def test_confirm_booking_rejects_non_post_request(self):
        self.client.force_login(self.tenant)

        response = self.client.get(
            reverse(
                "confirm_booking",
                kwargs={"property_id": self.property.pk},
            )
        )

        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.json()["error"], "Method not allowed")


    def test_confirm_booking_rejects_invalid_json(self):
        self.client.force_login(self.tenant)

        response = self.client.post(
            reverse(
                "confirm_booking",
                kwargs={"property_id": self.property.pk},
            ),
            data="{invalid-json",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "JSON inválido")


    def test_confirm_booking_rejects_invalid_date_format(self):
        self.client.force_login(self.tenant)

        response = self.client.post(
            reverse(
                "confirm_booking",
                kwargs={"property_id": self.property.pk},
            ),
            data={
                "start": "not-a-date",
                "end": "2026-10-10",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "Formato de fecha inválido.",
        )


    def test_confirm_booking_rejects_missing_dates(self):
        self.client.force_login(self.tenant)

        response = self.client.post(
            reverse(
                "confirm_booking",
                kwargs={"property_id": self.property.pk},
            ),
            data={
                "start": "2026-10-01",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "Ambas fechas deben ser seleccionadas.",
        )


    def test_confirm_booking_returns_404_for_invalid_property(self):
        self.client.force_login(self.tenant)

        response = self.client.post(
            reverse(
                "confirm_booking",
                kwargs={"property_id": 999999},
            ),
            data={
                "start": "2026-10-01",
                "end": "2026-10-05",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)

    def test_confirm_booking_rejects_closed_date(self):
        self.client.force_login(self.tenant)

        arrival_date = date.today() + timedelta(days=5)

        PropertyAvailability.objects.create(
            property=self.property,
            date=arrival_date,
            price_per_night=80,
            status="CLOSED",
            min_nights=1,
        )

        response = self.client.post(
            reverse(
                "confirm_booking",
                kwargs={"property_id": self.property.pk},
            ),
            data={
                "start": arrival_date.isoformat(),
                "end": (arrival_date + timedelta(days=2)).isoformat(),
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_confirm_booking_rejects_insufficient_min_nights(self):
        self.client.force_login(self.tenant)

        arrival_date = date.today() + timedelta(days=5)

        PropertyAvailability.objects.create(
            property=self.property,
            date=arrival_date,
            price_per_night=80,
            status="OPEN",
            min_nights=3,
        )

        response = self.client.post(
            reverse(
                "confirm_booking",
                kwargs={"property_id": self.property.pk},
            ),
            data={
                "start": arrival_date.isoformat(),
                "end": (arrival_date + timedelta(days=2)).isoformat(),
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_confirm_booking_allows_closed_checkout_date(self):
        self.client.force_login(self.tenant)

        arrival_date = date.today() + timedelta(days=5)
        checkout_date = arrival_date + timedelta(days=2)

        PropertyAvailability.objects.create(
            property=self.property,
            date=checkout_date,
            price_per_night=80,
            status="CLOSED",
            min_nights=1,
        )

        response = self.client.post(
            reverse(
                "confirm_booking",
                kwargs={"property_id": self.property.pk},
            ),
            data={
                "start": arrival_date.isoformat(),
                "end": checkout_date.isoformat(),
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["message"],
            "Reserva confirmada.",
        )

        self.assertTrue(
            Booking.objects.filter(
                tenant=self.tenant,
                property=self.property,
                initial_date=arrival_date,
                final_date=checkout_date,
            ).exists()
        )

    def test_delete_booking_rejects_non_post_request(self):
        self.client.force_login(self.tenant)

        booking = Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
        )

        response = self.client.get(
            reverse(
                "delete_booking",
                kwargs={"booking_id": booking.pk},
            )
        )

        self.assertEqual(response.status_code, 405)
        self.assertEqual(
            response.json()["error"],
            "Method not allowed",
        )

        self.assertTrue(
            Booking.objects.filter(pk=booking.pk).exists()
        )

    def test_booking_returns_404_for_invalid_property(self):
        self.client.force_login(self.tenant)

        response = self.client.get(
            reverse("booking", kwargs={"property_id": 999999}),
            {
                "start": (date.today() + timedelta(days=5)).isoformat(),
                "end": (date.today() + timedelta(days=7)).isoformat(),
            },
        )

        self.assertEqual(response.status_code, 404)

    def test_booking_endpoint_rejects_closed_date(self):
        self.client.force_login(self.tenant)

        closed_date = date.today() + timedelta(days=5)

        PropertyAvailability.objects.create(
            property=self.property,
            date=closed_date,
            price_per_night=80,
            status="CLOSED",
            min_nights=1,
        )

        response = self.client.get(
            reverse("booking", kwargs={"property_id": self.property.pk}),
            {
                "start": closed_date.isoformat(),
                "end": (closed_date + timedelta(days=2)).isoformat(),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "El alojamiento no está disponible en todas las fechas seleccionadas.",
        )

    def test_booking_endpoint_allows_closed_checkout_date(self):
        self.client.force_login(self.tenant)
        
        arrival_date = date.today() + timedelta(days=5)
        checkout_date = arrival_date + timedelta(days=2)

        PropertyAvailability.objects.create(
            property=self.property,
            date=checkout_date,
            price_per_night=80,
            status="CLOSED",
            min_nights=1,
        )

        response = self.client.get(
            reverse("booking", kwargs={"property_id": self.property.pk}),
            {
                "start": arrival_date.isoformat(),
                "end": checkout_date.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["available"])

    def test_booking_endpoint_rejects_stay_shorter_than_arrival_min_nights(self):
        self.client.force_login(self.tenant)

        arrival_date = date.today() + timedelta(days=5)

        PropertyAvailability.objects.create(
            property=self.property,
            date=arrival_date,
            price_per_night=80,
            status="OPEN",
            min_nights=3,
        )

        response = self.client.get(
            reverse("booking", kwargs={"property_id": self.property.pk}),
            {
                "start": arrival_date.isoformat(),
                "end": (arrival_date + timedelta(days=2)).isoformat(),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "La estancia debe ser de al menos 3 noches.",
        )

    def test_booking_endpoint_accepts_valid_availability(self):
        self.client.force_login(self.tenant)

        arrival_date = date.today() + timedelta(days=5)

        PropertyAvailability.objects.create(
            property=self.property,
            date=arrival_date,
            price_per_night=80,
            status="OPEN",
            min_nights=3,
        )

        response = self.client.get(
            reverse("booking", kwargs={"property_id": self.property.pk}),
            {
                "start": arrival_date.isoformat(),
                "end": (arrival_date + timedelta(days=3)).isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["available"])

    def test_booking_defaults_to_confirmed(self):
        booking = Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
        )

        self.assertEqual(booking.status, "CONFIRMED")


    def test_booking_status_can_be_changed(self):
        booking = Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            status="CANCELLED",
        )

        self.assertEqual(booking.status, "CANCELLED")


    def test_booking_has_expected_status_choices(self):
        statuses = dict(Booking.STATUS_CHOICES)

        self.assertEqual(
            statuses,
            {
                "PENDING": "Pendiente",
                "CONFIRMED": "Confirmada",
                "CANCELLED": "Cancelada",
                "EXPIRED": "Expirada",
            },
        )

class PropertySearchTestCase(TestCase):

    def test_properties_rejects_invalid_initial_date(self):
        response = self.client.get(
            reverse("properties"),
            {
                "initial_date": "not-a-date",
                "final_date": "2026-10-10",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "Invalid date format",
        )

    def test_properties_rejects_invalid_final_date(self):
        response = self.client.get(
            reverse("properties"),
            {
                "initial_date": "2026-10-01",
                "final_date": "not-a-date",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "Invalid date format",
        )

    def test_properties_rejects_invalid_adults(self):
        response = self.client.get(
            reverse("properties"),
            {"adults": "not-a-number"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "Introduce un número válido para indicar el número de adultos.",
        )


    def test_properties_rejects_invalid_children(self):
        response = self.client.get(
            reverse("properties"),
            {"children": "not-a-number"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "Introduce un número válido para indicar el número de niños.",
        )


    def test_properties_rejects_invalid_rooms(self):
        response = self.client.get(
            reverse("properties"),
            {"rooms": "not-a-number"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "Introduce un número válido para indicar el número de habitaciones.",
        )

class PropertyAvailabilityTestCase(TestCase):

    def setUp(self):
        self.owner = User.objects.create_user(
            username="availability_owner",
            email="availability_owner@test.com",
            password="123",
        )

        OwnerProfile.objects.create(
            user=self.owner,
            status="APPROVED",
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

        with self.assertRaises(ValidationError):
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

    def test_save_availability_rejects_invalid_min_nights(self):
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
                "status": "OPEN",
                "min_nights": "invalid",
                "price_per_night": "150",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "Invalid minimum nights",
        )

        self.assertFalse(
            PropertyAvailability.objects.filter(
                property=self.property,
                date=start_date,
            ).exists()
        )

    def test_save_availability_rejects_invalid_price(self):
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
                "status": "OPEN",
                "min_nights": "1",
                "price_per_night": "invalid",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "Invalid price",
        )

        self.assertFalse(
            PropertyAvailability.objects.filter(
                property=self.property,
                date=start_date,
            ).exists()
        )

    def test_save_availability_rejects_missing_fields(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse(
                "property_availability_save",
                kwargs={"property_id": self.property.pk},
            ),
            {
                "start_date": (
                    date.today() + timedelta(days=5)
                ).isoformat(),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "All fields are required",
        )

        self.assertEqual(
            PropertyAvailability.objects.filter(
                property=self.property,
            ).count(),
            0,
        )

    def test_invalid_availability_status(self):
        availability = PropertyAvailability(
            property=self.property,
            date=date.today(),
            price_per_night=120,
            status="INVALID",
            min_nights=1,
        )

        with self.assertRaises(ValidationError):
            availability.full_clean()

    def test_save_availability_updates_existing_date(self):
        start_date = date.today() + timedelta(days=5)

        PropertyAvailability.objects.create(
            property=self.property,
            date=start_date,
            price_per_night=100,
            status="OPEN",
            min_nights=1,
        )

        self.client.force_login(self.owner)

        response = self.client.post(
            reverse(
                "property_availability_save",
                kwargs={"property_id": self.property.pk},
            ),
            {
                "start_date": start_date.isoformat(),
                "end_date": start_date.isoformat(),
                "status": "CLOSED",
                "min_nights": "3",
                "price_per_night": "200",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["updated_count"], 1)

        availability = PropertyAvailability.objects.get(
            property=self.property,
            date=start_date,
        )

        self.assertEqual(availability.price_per_night, 200)
        self.assertEqual(availability.status, "CLOSED")
        self.assertEqual(availability.min_nights, 3)

        self.assertEqual(
            PropertyAvailability.objects.filter(
                property=self.property,
                date=start_date,
            ).count(),
            1,
        )

    def test_save_availability_rejects_invalid_date_format(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse(
                "property_availability_save",
                kwargs={"property_id": self.property.pk},
            ),
            {
                "start_date": "not-a-date",
                "end_date": "also-not-a-date",
                "status": "OPEN",
                "min_nights": "1",
                "price_per_night": "150",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "Invalid date format",
        )

        self.assertEqual(
            PropertyAvailability.objects.filter(
                property=self.property,
            ).count(),
            0,
        )