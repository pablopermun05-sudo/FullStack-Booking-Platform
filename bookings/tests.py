from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from bookings.views import PENDING_BOOKING_MINUTES
from .models import User, OwnerProfile, Property, Booking, BookingChangeProposal, BookingChangeAudit, BookingNight, PropertyAvailability, can_manage_properties
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db import IntegrityError, OperationalError, transaction, close_old_connections
from datetime import date, time, timedelta
import time as time_module
from unittest.mock import patch
import hashlib
import secrets
from urllib.parse import urlparse, parse_qs
from decimal import Decimal
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from django.core.management import call_command
from io import StringIO
from bookings.services import generate_proposal_access_token

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

    def test_staff_editing_other_owner_property_preserves_owner(self):
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

        response = self.client.post(
            reverse(
                "edit_property",
                args=[property.pk],
            ),
            {
                "title": "Updated property",
                "description": property.description,
                "location": property.location,
                "default_price_per_night": "120",
                "default_min_nights": "1",
                "children": "2",
                "adults": "2",
                "rooms": "2",
                "notice_period_days": "0",
                "allow_pets": "",
            },
        )

        self.assertEqual(response.status_code, 302)

        property.refresh_from_db()

        self.assertEqual(property.owner, owner)
        self.assertEqual(property.title, "Updated property")
        self.assertEqual(property.default_price_per_night, Decimal("120"))

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

class BookingTestBase(TestCase):

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

        self.booking_data = {
            "guest_first_name": "Juan",
            "guest_last_name": "García",
            "guest_email": "juan@example.com",
            "guest_phone_number": "+34600111222",
            "guest_country": "España",
            "guest_region": "Madrid",
            "guest_city": "Madrid",
            "guest_postal_code": "28001",
            "guest_address": "Calle Mayor 1",
            "is_for_self": True,
            "is_business_trip": False,
            "tax_id": "",
            "guest_count": 2,
            "special_requests": "",
            "arrival_time": time(18, 0),
        }

        self.booking_payload = {
            **self.booking_data,
            "arrival_time": "18:00",
        }

        self.booking1 = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today(),
            final_date=date.today() + timedelta(days=3),
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data
        )

        self.booking2 = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today(),
            final_date=date.today() + timedelta(days=3),
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data
        )

class BookingModelTestCase(BookingTestBase):

    def test_valid_booking(self):
        self.booking1.full_clean()

    def test_overlap_booking(self):
        self.booking1.full_clean()
        self.booking1.save()

        with self.assertRaises(ValidationError):
            self.booking2.full_clean()

    # Test que verifica que una reserva puede empezar el mismo día que otra termina
    def test_overlap_booking_sharing_checkout_day(self):
        self.booking1.save()

        # Esta reserva empieza justo el día que la anterior se va
        booking_same_day = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=self.booking1.final_date,
            final_date=self.booking1.final_date + timedelta(days=2),
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data
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
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data
        )

        with self.assertRaises(ValidationError):
            invalid_booking.full_clean()

    def test_owner_cannot_book_own_property(self):
        booking_by_owner = Booking(
            tenant=self.owner,  # El propietario intenta reservar
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data
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
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data
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
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data
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
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data
        )

        booking.full_clean()
        

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
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data
        )

        booking.full_clean()

    def test_invalid_booking_dates(self):
        booking = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=3),
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data
        )

        with self.assertRaises(ValidationError):
            booking.full_clean()

    def test_booking_same_checkin_checkout_date(self):
        booking = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=5),
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data
        )

        with self.assertRaises(ValidationError):
            booking.full_clean()

    def test_booking_defaults_to_pending(self):
        booking = Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data
        )

        self.assertEqual(booking.status, "PENDING")


    def test_booking_status_can_be_changed(self):
        booking = Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            status="CANCELLED",
            **self.booking_data
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

    def test_cancelled_booking_does_not_block_dates(self):
        Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            status="CANCELLED",
            **self.booking_data
        )

        booking = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data
        )

        booking.full_clean()

    def test_expired_booking_does_not_block_dates(self):
        Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            status="EXPIRED",
            **self.booking_data
        )

        booking = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data
        )

        booking.full_clean()

    def test_pending_booking_blocks_dates(self):
        Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            status="PENDING",
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data
        )

    def test_confirmed_booking_blocks_dates(self):
        Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            status="CONFIRMED",
            **self.booking_data
        )

        booking = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data
        )

        with self.assertRaises(ValidationError):
            booking.full_clean()

    def test_active_statuses_are_pending_and_confirmed(self):
        self.assertEqual(
            Booking.ACTIVE_STATUSES,
            ("PENDING", "CONFIRMED"),
        )

    def test_booking_night_rejects_duplicate_date_for_same_booking(self):
        initial_date = date.today() + timedelta(days=5)
        final_date = initial_date + timedelta(days=2)

        booking = Booking.create_pending(
            tenant=self.tenant,
            property=self.property,
            initial_date=initial_date,
            final_date=final_date,
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data
        )

        with self.assertRaises(IntegrityError):
            BookingNight.objects.create(
                booking=booking,
                date=initial_date,
                price_per_night=self.property.default_price_per_night,
            )

    def test_anonymous_booking_with_guest_data_is_valid(self):
        booking = Booking(
            tenant=None,
            property=self.property,
            initial_date=date.today() + timedelta(days=2),
            final_date=date.today() + timedelta(days=5),
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data,
        )

        booking.full_clean()

    def test_booking_without_required_guest_data_is_invalid(self):
        booking_data = self.booking_data.copy()
        booking_data["guest_first_name"] = ""

        booking = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=2),
            final_date=date.today() + timedelta(days=5),
            expires_at=timezone.now() + timedelta(minutes=15),
            **booking_data,
        )

        with self.assertRaises(ValidationError):
            booking.full_clean()

    def test_guest_count_must_be_at_least_one(self):
        booking_data = self.booking_data.copy()
        booking_data["guest_count"] = 0

        booking = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            expires_at=timezone.now() + timedelta(minutes=15),
            **booking_data,
        )

        with self.assertRaises(ValidationError):
            booking.full_clean()

    def test_business_trip_requires_tax_id(self):
        booking_data = self.booking_data.copy()
        booking_data["is_business_trip"] = True
        booking_data["tax_id"] = ""

        booking = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            expires_at=timezone.now() + timedelta(minutes=15),
            **booking_data,
        )

        with self.assertRaises(ValidationError):
            booking.full_clean()

    def test_optional_guest_location_fields_can_be_blank(self):
        booking_data = self.booking_data.copy()
        booking_data["guest_region"] = ""
        booking_data["guest_postal_code"] = ""

        booking = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            expires_at=timezone.now() + timedelta(minutes=15),
            **booking_data,
        )

        booking.full_clean()

class BookingLifecycleTestCase(BookingTestBase):

    def test_confirm_changes_pending_booking_to_confirmed(self):
        booking = Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            status="PENDING",
            expires_at=timezone.now() + timedelta(minutes=5),
            **self.booking_data
        )

        result = booking.confirm()

        booking.refresh_from_db()

        self.assertTrue(result)
        self.assertEqual(booking.status, "CONFIRMED")

    def test_confirm_expires_expired_pending_booking(self):
        booking = Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            status="PENDING",
            expires_at=timezone.now() + timedelta(minutes=5),
            **self.booking_data
        )

        Booking.objects.filter(pk=booking.pk).update(
            expires_at=timezone.now() - timedelta(minutes=5)
        )

        booking.refresh_from_db()

        result = booking.confirm()

        booking.refresh_from_db()

        self.assertFalse(result)
        self.assertEqual(booking.status, "EXPIRED")

    def test_confirm_expired_pending_booking_after_confirmed_booking_exists(self):
        initial_date = date.today() + timedelta(days=5)
        final_date = date.today() + timedelta(days=7)

        now = timezone.now()

        expired_pending = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=initial_date,
            final_date=final_date,
            created_at=now - timedelta(minutes=20),
            status="PENDING",
            expires_at=now - timedelta(minutes=5),
            **self.booking_data
        )
        expired_pending.save_base(force_insert=True)

        confirmed_booking = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=initial_date,
            final_date=final_date,
            created_at=now,
            status="CONFIRMED",
            **self.booking_data
        )
        confirmed_booking.save_base(force_insert=True)

        result = expired_pending.confirm()

        expired_pending.refresh_from_db()
        confirmed_booking.refresh_from_db()

        self.assertFalse(result)
        self.assertEqual(expired_pending.status, "EXPIRED")
        self.assertEqual(confirmed_booking.status, "CONFIRMED")

    def test_confirm_does_not_change_confirmed_booking(self):
        booking = Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            status="CONFIRMED",
            expires_at=timezone.now() - timedelta(minutes=5),
            **self.booking_data
        )

        result = booking.confirm()

        booking.refresh_from_db()

        self.assertFalse(result)
        self.assertEqual(booking.status, "CONFIRMED")

    def test_confirm_uses_current_database_state_for_stale_booking_instance(self):
        booking = Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            status="PENDING",
            expires_at=timezone.now() + timedelta(minutes=5),
            **self.booking_data
        )

        stale_booking = Booking.objects.get(pk=booking.pk)

        booking.confirm()

        result = stale_booking.confirm()

        self.assertFalse(result)
        self.assertEqual(stale_booking.status, "CONFIRMED")

        stale_booking.refresh_from_db()

        self.assertEqual(stale_booking.status, "CONFIRMED")

    def test_cancel_changes_confirmed_booking_to_cancelled(self):
        booking = Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            status="CONFIRMED",
            **self.booking_data
        )

        result = booking.cancel()

        booking.refresh_from_db()

        self.assertTrue(result)
        self.assertEqual(booking.status, "CANCELLED")

    def test_cancel_does_not_change_pending_booking(self):
        booking = Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            status="PENDING",
            expires_at=timezone.now() + timedelta(minutes=5),
            **self.booking_data
        )

        result = booking.cancel()

        booking.refresh_from_db()

        self.assertFalse(result)
        self.assertEqual(booking.status, "PENDING")

    def test_cancel_does_not_change_cancelled_booking(self):
        booking = Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            status="CANCELLED",
            **self.booking_data
        )

        result = booking.cancel()

        booking.refresh_from_db()

        self.assertFalse(result)
        self.assertEqual(booking.status, "CANCELLED")

    def test_pending_booking_with_future_expiration_is_not_expired(self):
        booking = Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            status="PENDING",
            expires_at=timezone.now() + timedelta(minutes=5),
            **self.booking_data
        )

        self.assertFalse(booking.is_expired())


    def test_pending_booking_with_past_expiration_is_expired(self):
        booking = Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            status="PENDING",
            expires_at=timezone.now() + timedelta(minutes=5),
            **self.booking_data
        )

        Booking.objects.filter(pk=booking.pk).update(
            expires_at=timezone.now() - timedelta(minutes=5)
        )

        booking.refresh_from_db()

        self.assertTrue(booking.is_expired())

    def test_pending_booking_requires_expiration(self):
        booking = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            status="PENDING",
            **self.booking_data
        )

        with self.assertRaises(ValidationError):
            booking.full_clean()

    def test_expire_changes_expired_pending_booking_to_expired(self):
        booking = Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            status="PENDING",
            expires_at=timezone.now() + timedelta(minutes=5),
            **self.booking_data
        )

        Booking.objects.filter(pk=booking.pk).update(
            expires_at=timezone.now() - timedelta(minutes=5)
        )

        booking.refresh_from_db()

        result = booking.expire()

        booking.refresh_from_db()

        self.assertTrue(result)
        self.assertEqual(booking.status, "EXPIRED")
    
    def test_expire_does_not_change_active_pending_booking(self):
        booking = Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            status="PENDING",
            expires_at=timezone.now() + timedelta(minutes=5),
            **self.booking_data
        )

        result = booking.expire()

        booking.refresh_from_db()

        self.assertFalse(result)
        self.assertEqual(booking.status, "PENDING")

    def test_expire_does_not_change_confirmed_booking(self):
        booking = Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            status="CONFIRMED",
            expires_at=timezone.now() - timedelta(minutes=5),
            **self.booking_data
        )

        result = booking.expire()

        booking.refresh_from_db()

        self.assertFalse(result)
        self.assertEqual(booking.status, "CONFIRMED")

    def test_expire_does_not_change_cancelled_booking(self):
        booking = Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            status="CANCELLED",
            expires_at=timezone.now() - timedelta(minutes=5),
            **self.booking_data
        )

        result = booking.expire()

        booking.refresh_from_db()

        self.assertFalse(result)
        self.assertEqual(booking.status, "CANCELLED")
        
    def test_expire_pending_bookings_expires_expired_bookings(self):
        expired_booking = Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            status="PENDING",
            expires_at=timezone.now() + timedelta(minutes=5),
            **self.booking_data
        )

        Booking.objects.filter(pk=expired_booking.pk).update(
            expires_at=timezone.now() - timedelta(minutes=5)
        )

        Booking.expire_pending_bookings()

        expired_booking.refresh_from_db()

        self.assertEqual(expired_booking.status, "EXPIRED")

    def test_expire_pending_bookings_keeps_active_pending_booking(self):
        pending_booking = Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            status="PENDING",
            expires_at=timezone.now() + timedelta(minutes=5),
            **self.booking_data
        )

        Booking.expire_pending_bookings()

        pending_booking.refresh_from_db()

        self.assertEqual(pending_booking.status, "PENDING")

    def test_expire_pending_bookings_does_not_change_confirmed_bookings(self):
        confirmed_booking = Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            status="CONFIRMED",
            expires_at=timezone.now() - timedelta(minutes=5),
            **self.booking_data
        )

        Booking.expire_pending_bookings()

        confirmed_booking.refresh_from_db()

        self.assertEqual(confirmed_booking.status, "CONFIRMED")

    def test_expire_pending_bookings_returns_expired_count(self):
        booking1 = Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            status="PENDING",
            expires_at=timezone.now() + timedelta(minutes=5),
            **self.booking_data
        )

        booking2 = Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=10),
            final_date=date.today() + timedelta(days=12),
            status="PENDING",
            expires_at=timezone.now() + timedelta(minutes=5),
            **self.booking_data
        )

        Booking.objects.filter(
            pk__in=[booking1.pk, booking2.pk]
        ).update(
            expires_at=timezone.now() - timedelta(minutes=5)
        )

        expired_count = Booking.expire_pending_bookings()

        self.assertEqual(expired_count, 2)

    def test_non_pending_booking_is_not_expired_even_with_past_expiration(self):
        booking = Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=10),
            final_date=date.today() + timedelta(days=12),
            status="CONFIRMED",
            expires_at=timezone.now() - timedelta(minutes=1),
            **self.booking_data
        )

        self.assertFalse(booking.is_expired())

    def test_expire_allows_expired_pending_booking_after_confirmed_booking_exists(self):
        initial_date = date.today() + timedelta(days=5)
        final_date = initial_date + timedelta(days=7)

        now = timezone.now()

        expired_pending = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=initial_date,
            final_date=final_date,
            created_at=now - timedelta(minutes=20),
            status="PENDING",
            expires_at=now - timedelta(minutes=5),
            **self.booking_data
        )
        expired_pending.save_base(force_insert=True)

        confirmed_booking = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=initial_date,
            final_date=final_date,
            created_at=now,
            status="CONFIRMED",
            **self.booking_data
        )
        confirmed_booking.save_base(force_insert=True)

        result = expired_pending.expire()

        expired_pending.refresh_from_db()
        confirmed_booking.refresh_from_db()

        self.assertTrue(result)
        self.assertEqual(expired_pending.status, "EXPIRED")
        self.assertEqual(confirmed_booking.status, "CONFIRMED")

class BookingCreationTestCase(BookingTestBase):

    def test_create_pending_rolls_back_booking_if_booking_nights_creation_fails(self):
        initial_date = date.today() + timedelta(days=5)
        final_date = initial_date + timedelta(days=2)
        attempted_booking_ids = []

        original_bulk_create = BookingNight.objects.bulk_create

        def insert_first_night_then_fail(nights, *args, **kwargs):
            attempted_booking_ids.append(nights[0].booking_id)

            # Simulamos una inserción parcial antes del error.
            original_bulk_create(nights[:1], *args, **kwargs)

            raise RuntimeError("Error después de insertar la primera noche")

        with patch.object(
            BookingNight.objects,
            "bulk_create",
            side_effect=insert_first_night_then_fail,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Error después de insertar la primera noche",
            ):
                Booking.create_pending(
                    tenant=self.tenant,
                    property=self.property,
                    initial_date=initial_date,
                    final_date=final_date,
                    expires_at=timezone.now() + timedelta(minutes=15),
                    **self.booking_data,
                )

        self.assertEqual(len(attempted_booking_ids), 1)
        booking_id = attempted_booking_ids[0]

        # No debe persistir la reserva.
        self.assertFalse(
            Booking.objects.filter(pk=booking_id).exists()
        )

        # Tampoco debe persistir la primera noche insertada.
        self.assertFalse(
            BookingNight.objects.filter(booking_id=booking_id).exists()
        )

    def test_deleting_booking_deletes_its_booking_nights(self):
        initial_date = date.today() + timedelta(days=5)
        final_date = initial_date + timedelta(days=3)

        booking = Booking.create_pending(
            tenant=self.tenant,
            property=self.property,
            initial_date=initial_date,
            final_date=final_date,
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data,
        )

        booking_id = booking.pk

        self.assertEqual(
            BookingNight.objects.filter(booking_id=booking_id).count(),
            3,
        )

        booking.delete()

        self.assertFalse(
            Booking.objects.filter(pk=booking_id).exists()
        )
        self.assertFalse(
            BookingNight.objects.filter(booking_id=booking_id).exists()
        )
    
    def test_create_pending_rolls_back_when_booking_validation_fails(self):
        initial_date = date.today() + timedelta(days=5)
        final_date = initial_date + timedelta(days=2)

        Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=initial_date,
            final_date=final_date,
            status="CONFIRMED",
            guest_first_name="Test",
            guest_last_name="Guest",
            guest_email="test@example.com",
            guest_phone_number="+34600000000",
            guest_country="España",
            guest_city="Madrid",
            guest_address="Calle Test 1",
            guest_count=1,
            arrival_time=time(15, 0),
        )

        with self.assertRaises(ValidationError):
            Booking.create_pending(
                tenant=self.tenant,
                property=self.property,
                initial_date=initial_date,
                final_date=final_date,
                expires_at=timezone.now() + timedelta(minutes=15),
                **self.booking_data
            )

        self.assertEqual(
            Booking.objects.filter(
                tenant=self.tenant,
                property=self.property,
                initial_date=initial_date,
                final_date=final_date,
                status="PENDING",
            ).count(),
            0,
        )

        self.assertEqual(
            BookingNight.objects.filter(
                booking__tenant=self.tenant,
                booking__property=self.property,
                booking__initial_date=initial_date,
                booking__final_date=final_date,
            ).count(),
            0,
        )

    def test_create_pending_rejects_overlap_with_active_pending_booking(self):
        initial_date = date.today() + timedelta(days=5)
        final_date = initial_date + timedelta(days=2)

        Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=initial_date,
            final_date=final_date,
            status="PENDING",
            expires_at=timezone.now() + timedelta(minutes=10),
            **self.booking_data
        )

        with self.assertRaises(ValidationError):
            Booking.create_pending(
                tenant=self.tenant,
                property=self.property,
                initial_date=initial_date,
                final_date=final_date,
                expires_at=timezone.now() + timedelta(minutes=15),
                **self.booking_data
            )

        self.assertEqual(
            Booking.objects.filter(
                property=self.property,
                initial_date=initial_date,
                final_date=final_date,
                status="PENDING",
            ).count(),
            1,
        )

    def test_create_pending_allows_overlap_with_expired_pending_booking(self):
        initial_date = date.today() + timedelta(days=5)
        final_date = initial_date + timedelta(days=2)

        now = timezone.now()

        expired_booking = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=initial_date,
            final_date=final_date,
            created_at=now - timedelta(minutes=20),
            status="PENDING",
            expires_at=now - timedelta(minutes=1),
            **self.booking_data
        )

        expired_booking.save_base(force_insert=True)

        booking = Booking.create_pending(
            tenant=self.tenant,
            property=self.property,
            initial_date=initial_date,
            final_date=final_date,
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data
        )

        self.assertNotEqual(booking.pk, expired_booking.pk)
        self.assertEqual(booking.status, "PENDING")
        self.assertEqual(
            Booking.objects.filter(
                property=self.property,
                initial_date=initial_date,
                final_date=final_date,
                status="PENDING",
            ).count(),
            2,
        )

    def test_create_pending_creates_pending_booking(self):
        expires_at = timezone.now() + timedelta(minutes=15)

        booking = Booking.create_pending(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            expires_at=expires_at,
            **self.booking_data
        )

        self.assertEqual(booking.status, "PENDING")
        self.assertEqual(booking.expires_at, expires_at)

    def test_create_pending_saves_booking(self):
        expires_at = timezone.now() + timedelta(minutes=15)

        booking = Booking.create_pending(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            expires_at=expires_at,
            **self.booking_data
        )

        self.assertIsNotNone(booking.pk)
        self.assertTrue(
            Booking.objects.filter(pk=booking.pk).exists()
        )

    def test_create_pending_creates_booking_night_for_each_stay_night(self):
        booking = Booking.create_pending(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=8),
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data
        )

        nights = booking.nights.order_by("date")

        self.assertEqual(nights.count(), 3)
        self.assertEqual(
            list(nights.values_list("date", flat=True)),
            [
                date.today() + timedelta(days=5),
                date.today() + timedelta(days=6),
                date.today() + timedelta(days=7),
            ],
        )

    def test_create_pending_snapshots_default_price(self):
        booking = Booking.create_pending(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data
        )

        prices = list(
            booking.nights.order_by("date").values_list(
                "price_per_night",
                flat=True,
            )
        )

        self.assertEqual(
            prices,
            [
                self.property.default_price_per_night,
                self.property.default_price_per_night,
            ],
        )

    def test_create_pending_snapshots_availability_price_overrides(self):
        start_date = date.today() + timedelta(days=5)
        middle_date = start_date + timedelta(days=1)
        end_date = start_date + timedelta(days=3)

        PropertyAvailability.objects.create(
            property=self.property,
            date=middle_date,
            price_per_night=150,
            status="OPEN",
            min_nights=1,
        )

        booking = Booking.create_pending(
            tenant=self.tenant,
            property=self.property,
            initial_date=start_date,
            final_date=end_date,
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data
        )

        nights = booking.nights.order_by("date")

        self.assertEqual(nights.count(), 3)

        self.assertEqual(
            list(nights.values_list("price_per_night", flat=True)),
            [
                self.property.default_price_per_night,
                150,
                self.property.default_price_per_night,
            ],
        )

    def test_create_pending_does_not_create_booking_night_for_checkout_date(self):
        start_date = date.today() + timedelta(days=5)
        end_date = start_date + timedelta(days=2)

        booking = Booking.create_pending(
            tenant=self.tenant,
            property=self.property,
            initial_date=start_date,
            final_date=end_date,
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data
        )

        self.assertFalse(
            booking.nights.filter(date=end_date).exists()
        )

    def test_booking_total_price_sums_booking_nights(self):
        start_date = date.today() + timedelta(days=5)
        end_date = start_date + timedelta(days=3)

        booking = Booking.create_pending(
            tenant=self.tenant,
            property=self.property,
            initial_date=start_date,
            final_date=end_date,
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data
        )

        booking.nights.filter(date=start_date).update(price_per_night=100)
        booking.nights.filter(
            date=start_date + timedelta(days=1)
        ).update(price_per_night=120)
        booking.nights.filter(
            date=start_date + timedelta(days=2)
        ).update(price_per_night=150)

        self.assertEqual(booking.total_price, Decimal("370.00"))

    def test_booking_total_price_uses_snapshots(self):
        start_date = date.today() + timedelta(days=5)
        end_date = start_date + timedelta(days=2)

        booking = Booking.create_pending(
            tenant=self.tenant,
            property=self.property,
            initial_date=start_date,
            final_date=end_date,
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data,
        )

        original_prices = list(
            booking.nights.order_by("date").values_list(
                "price_per_night",
                flat=True,
            )
        )

        self.assertEqual(
            original_prices,
            [Decimal("80.00"), Decimal("80.00")],
        )
        self.assertEqual(booking.total_price, Decimal("160.00"))

        self.property.default_price_per_night = Decimal("500.00")
        self.property.save(
            update_fields=["default_price_per_night"]
        )

        booking.refresh_from_db()

        self.assertEqual(booking.total_price, Decimal("160.00"))
        self.assertEqual(
            list(
                booking.nights.order_by("date").values_list(
                    "price_per_night",
                    flat=True,
                )
            ),
            original_prices,
        )

    def test_booking_total_price_is_unaffected_by_property_and_availability_price_changes(self):
        start_date = date.today() + timedelta(days=5)
        middle_date = start_date + timedelta(days=1)
        end_date = start_date + timedelta(days=2)

        availability_override = PropertyAvailability.objects.create(
            property=self.property,
            date=middle_date,
            price_per_night=Decimal("150.00"),
            status="OPEN",
            min_nights=1,
        )

        booking = Booking.create_pending(
            tenant=self.tenant,
            property=self.property,
            initial_date=start_date,
            final_date=end_date,
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data,
        )

        original_prices = list(
            booking.nights.order_by("date").values_list(
                "price_per_night",
                flat=True,
            )
        )

        expected_prices = [
            self.property.default_price_per_night,
            Decimal("150.00"),
        ]

        self.assertEqual(original_prices, expected_prices)
        self.assertEqual(
            booking.total_price,
            sum(expected_prices, Decimal("0.00")),
        )

        original_total = booking.total_price

        self.property.default_price_per_night = Decimal("500.00")
        self.property.save(
            update_fields=["default_price_per_night"]
        )

        availability_override.price_per_night = Decimal("900.00")
        availability_override.save(
            update_fields=["price_per_night"]
        )

        booking.refresh_from_db()

        self.assertEqual(booking.total_price, original_total)

        self.assertEqual(
            list(
                booking.nights.order_by("date").values_list(
                    "price_per_night",
                    flat=True,
                )
            ),
            original_prices,
        )

        self.assertEqual(
            availability_override.price_per_night,
            Decimal("900.00"),
        )

    def test_booking_total_price_is_zero_without_nights(self):
        booking = Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            status="PENDING",
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data
        )

        self.assertEqual(booking.total_price, Decimal("0"))

class BookingAvailabilityViewTestCase(BookingTestBase):

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

    def test_booking_endpoint_rejects_pending_booking(self):
        self.client.login(username="tenant", password="123")

        Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=self.booking1.initial_date,
            final_date=self.booking1.final_date,
            status="PENDING",
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data
        )

        response = self.client.get(
            reverse("booking", args=[self.property.id]),
            {
                "start": self.booking1.initial_date.isoformat(),
                "end": self.booking1.final_date.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "El alojamiento ya está reservado en esas fechas.",
        )

    def test_booking_endpoint_rejects_confirmed_booking(self):
        self.client.login(username="tenant", password="123")

        Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=self.booking1.initial_date,
            final_date=self.booking1.final_date,
            status="CONFIRMED",
            **self.booking_data
        )

        response = self.client.get(
            reverse("booking", args=[self.property.id]),
            {
                "start": self.booking1.initial_date.isoformat(),
                "end": self.booking1.final_date.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "El alojamiento ya está reservado en esas fechas.",
        )

    def test_booking_endpoint_allows_cancelled_booking(self):
        self.client.login(username="tenant", password="123")

        Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=self.booking1.initial_date,
            final_date=self.booking1.final_date,
            status="CANCELLED",
            **self.booking_data
        )

        response = self.client.get(
            reverse("booking", args=[self.property.id]),
            {
                "start": self.booking1.initial_date.isoformat(),
                "end": self.booking1.final_date.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["available"])

    def test_booking_endpoint_allows_expired_booking(self):
        self.client.login(username="tenant", password="123")

        Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=self.booking1.initial_date,
            final_date=self.booking1.final_date,
            status="EXPIRED",
            **self.booking_data
        )

        response = self.client.get(
            reverse("booking", args=[self.property.id]),
            {
                "start": self.booking1.initial_date.isoformat(),
                "end": self.booking1.final_date.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["available"])

    def test_anonymous_user_can_check_booking_availability(self):
        response = self.client.get(
            reverse("booking", args=[self.property.id]),
            {
                "start": str(date.today() + timedelta(days=2)),
                "end": str(date.today() + timedelta(days=5)),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["available"])

class BookingModCreateBookingViewTestCase(BookingTestBase):

    def test_create_booking_rejects_non_post_request(self):
        self.client.force_login(self.tenant)

        response = self.client.get(
            reverse(
                "confirm_booking",
                kwargs={"property_id": self.property.pk},
            )
        )

        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.json()["error"], "Method not allowed")


    def test_create_booking_rejects_invalid_json(self):
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


    def test_create_booking_rejects_invalid_date_format(self):
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


    def test_create_booking_rejects_missing_dates(self):
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

    def test_create_booking_returns_404_for_invalid_property(self):
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

    def test_create_booking_rejects_closed_date(self):
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
                **self.booking_payload,
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_create_booking_rejects_insufficient_min_nights(self):
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
                **self.booking_payload,
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_create_booking_allows_closed_checkout_date(self):
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
                **self.booking_payload,
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["message"],
            "Reserva pendiente.",
        )

        booking = Booking.objects.get(
            tenant=self.tenant,
            property=self.property,
            initial_date=arrival_date,
            final_date=checkout_date,
        )

        self.assertEqual(booking.guest_first_name, "Juan")
        self.assertEqual(booking.guest_last_name, "García")
        self.assertEqual(booking.guest_email, "juan@example.com")
        self.assertEqual(booking.guest_phone_number, "+34600111222")
        self.assertEqual(booking.guest_country, "España")
        self.assertEqual(booking.guest_region, "Madrid")
        self.assertEqual(booking.guest_city, "Madrid")
        self.assertEqual(booking.guest_postal_code, "28001")
        self.assertEqual(booking.guest_address, "Calle Mayor 1")
        self.assertTrue(booking.is_for_self)
        self.assertFalse(booking.is_business_trip)
        self.assertEqual(booking.guest_count, 2)
        self.assertEqual(booking.special_requests, "")
        self.assertEqual(booking.arrival_time, time(18, 0))
        self.assertEqual(booking.status, "PENDING")
        self.assertIsNotNone(booking.expires_at)
        self.assertGreater(booking.expires_at, timezone.now())

    def test_create_booking_sets_pending_expiration(self):
        self.client.force_login(self.tenant)

        arrival_date = date.today() + timedelta(days=5)
        checkout_date = arrival_date + timedelta(days=7)

        before_request = timezone.now()

        response = self.client.post(
            reverse(
                "confirm_booking",
                kwargs={"property_id": self.property.pk},
            ),
            data={
                "start": arrival_date.isoformat(),
                "end": checkout_date.isoformat(),
                **self.booking_payload,
            },
            content_type="application/json",
        )

        after_request = timezone.now()

        self.assertEqual(response.status_code, 200)

        booking = Booking.objects.get(
            tenant=self.tenant,
            property=self.property,
            initial_date=arrival_date,
            final_date=checkout_date,
            **self.booking_data
        )

        self.assertEqual(
            response.json()["booking_id"],
            booking.pk,
        )

        self.assertEqual(booking.status, "PENDING")

        self.assertGreaterEqual(
            booking.expires_at,
            before_request + timedelta(minutes=15),
        )

        self.assertLessEqual(
            booking.expires_at,
            after_request + timedelta(minutes=15),
        )

    def test_anonymous_user_can_create_pending_booking(self):
        response = self.client.post(
            reverse("confirm_booking", args=[self.property.id]),
            data=json.dumps({
                "start": str(date.today() + timedelta(days=2)),
                "end": str(date.today() + timedelta(days=5)),
                **self.booking_payload,
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)

        booking = Booking.objects.get(
            property=self.property,
            tenant=None,
        )

        self.assertEqual(
            response.json()["booking_id"],
            booking.pk,
        )

        self.assertIsNone(booking.tenant)
        self.assertEqual(booking.guest_first_name, "Juan")
        self.assertEqual(booking.guest_last_name, "García")
        self.assertEqual(booking.guest_email, "juan@example.com")
        self.assertEqual(booking.guest_phone_number, "+34600111222")
        self.assertEqual(booking.guest_country, "España")
        self.assertEqual(booking.guest_city, "Madrid")
        self.assertEqual(booking.guest_address, "Calle Mayor 1")
        self.assertEqual(booking.guest_count, 2)
        self.assertEqual(booking.arrival_time, time(18, 0))
        self.assertEqual(booking.status, "PENDING")

    def test_create_booking_requires_guest_data(self):
        response = self.client.post(
            reverse("confirm_booking", args=[self.property.id]),
            data=json.dumps({
                "start": str(date.today() + timedelta(days=2)),
                "end": str(date.today() + timedelta(days=5)),
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "Faltan campos obligatorios.",
        )
        self.assertIn(
            "guest_first_name",
            response.json()["fields"],
        )

    def test_create_booking_rejects_invalid_guest_count(self):
        self.client.force_login(self.tenant)

        payload = self.booking_payload.copy()
        payload["guest_count"] = "abc"

        response = self.client.post(
            reverse(
                "confirm_booking",
                kwargs={"property_id": self.property.pk},
            ),
            data=json.dumps({
                "start": (
                    date.today() + timedelta(days=5)
                ).isoformat(),
                "end": (
                    date.today() + timedelta(days=7)
                ).isoformat(),
                **payload,
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "El número de huéspedes debe ser un número entero.",
        )

    def test_create_booking_rejects_invalid_arrival_time(self):
        self.client.force_login(self.tenant)

        payload = self.booking_payload.copy()
        payload["arrival_time"] = "not-a-time"

        response = self.client.post(
            reverse(
                "confirm_booking",
                kwargs={"property_id": self.property.pk},
            ),
            data=json.dumps({
                "start": (
                    date.today() + timedelta(days=5)
                ).isoformat(),
                "end": (
                    date.today() + timedelta(days=7)
                ).isoformat(),
                **payload,
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "Formato de hora de llegada inválido.",
        )

    def test_create_booking_rejects_business_trip_without_tax_id(self):
        self.client.force_login(self.tenant)

        payload = self.booking_payload.copy()
        payload["is_business_trip"] = True
        payload["tax_id"] = ""

        response = self.client.post(
            reverse(
                "confirm_booking",
                kwargs={"property_id": self.property.pk},
            ),
            data=json.dumps({
                "start": (
                    date.today() + timedelta(days=5)
                ).isoformat(),
                "end": (
                    date.today() + timedelta(days=7)
                ).isoformat(),
                **payload,
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_create_booking_accepts_business_trip_with_tax_id(self):
        self.client.force_login(self.tenant)

        payload = self.booking_payload.copy()
        payload["is_business_trip"] = True
        payload["tax_id"] = "B12345678"

        response = self.client.post(
            reverse(
                "confirm_booking",
                kwargs={"property_id": self.property.pk},
            ),
            data=json.dumps({
                "start": (
                    date.today() + timedelta(days=5)
                ).isoformat(),
                "end": (
                    date.today() + timedelta(days=7)
                ).isoformat(),
                **payload,
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)

        booking = Booking.objects.get(
            pk=response.json()["booking_id"]
        )

        self.assertTrue(booking.is_business_trip)
        self.assertEqual(booking.tax_id, "B12345678")

    def test_create_booking_saves_guest_snapshot(self):
        self.client.force_login(self.tenant)

        response = self.client.post(
            reverse(
                "confirm_booking",
                kwargs={"property_id": self.property.pk},
            ),
            data=json.dumps({
                "start": (
                    date.today() + timedelta(days=5)
                ).isoformat(),
                "end": (
                    date.today() + timedelta(days=7)
                ).isoformat(),
                **self.booking_payload,
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)

        booking = Booking.objects.get(
            pk=response.json()["booking_id"]
        )

        self.assertEqual(booking.guest_first_name, "Juan")
        self.assertEqual(booking.guest_last_name, "García")
        self.assertEqual(booking.guest_email, "juan@example.com")
        self.assertEqual(booking.guest_phone_number, "+34600111222")
        self.assertEqual(booking.guest_country, "España")
        self.assertEqual(booking.guest_region, "Madrid")
        self.assertEqual(booking.guest_city, "Madrid")
        self.assertEqual(booking.guest_postal_code, "28001")
        self.assertEqual(booking.guest_address, "Calle Mayor 1")
        self.assertTrue(booking.is_for_self)
        self.assertFalse(booking.is_business_trip)
        self.assertEqual(booking.guest_count, 2)
        self.assertEqual(booking.special_requests, "")
        self.assertEqual(booking.arrival_time, time(18, 0))

    def test_create_booking_ignores_client_status(self):
        self.client.force_login(self.tenant)

        arrival_date = date.today() + timedelta(days=5)
        checkout_date = arrival_date + timedelta(days=7)

        payload = {
            "start": arrival_date.isoformat(),
            "end": checkout_date.isoformat(),
            **self.booking_payload,
            "status": "CONFIRMED",
        }

        response = self.client.post(
            reverse(
                "confirm_booking",
                kwargs={"property_id": self.property.pk},
            ),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(
            response.status_code,
            200,
            response.content.decode(),
        )

        booking = Booking.objects.get(
            pk=response.json()["booking_id"]
        )

        self.assertEqual(booking.status, "PENDING")

    def test_create_booking_ignores_client_tenant_and_expiration(self):
        self.client.force_login(self.tenant)

        other_user = User.objects.create_user(
            username="other-user",
            email="other@example.com",
            password="testpass123",
        )

        arrival_date = date.today() + timedelta(days=5)
        checkout_date = arrival_date + timedelta(days=7)

        requested_expires_at = timezone.now() + timedelta(days=365)

        payload = {
            "start": arrival_date.isoformat(),
            "end": checkout_date.isoformat(),
            **self.booking_payload,
            "tenant": other_user.pk,
            "expires_at": requested_expires_at.isoformat(),
        }

        before_request = timezone.now()

        response = self.client.post(
            reverse(
                "confirm_booking",
                kwargs={"property_id": self.property.pk},
            ),
            data=json.dumps(payload),
            content_type="application/json",
        )

        after_request = timezone.now()

        self.assertEqual(
            response.status_code,
            200,
            response.content.decode(),
        )

        booking = Booking.objects.get(
            pk=response.json()["booking_id"]
        )

        self.assertEqual(booking.tenant, self.tenant)

        self.assertNotEqual(
            booking.expires_at,
            requested_expires_at,
        )

        expected_min = (
            before_request
            + timedelta(minutes=PENDING_BOOKING_MINUTES)
        )
        expected_max = (
            after_request
            + timedelta(minutes=PENDING_BOOKING_MINUTES)
        )

        self.assertGreaterEqual(
            booking.expires_at,
            expected_min,
        )
        self.assertLessEqual(
            booking.expires_at,
            expected_max,
        )

    def test_create_booking_rejects_non_string_guest_name(self):
        payload = self.booking_payload.copy()
        payload["guest_first_name"] = 123

        response = self.client.post(
            reverse(
                "confirm_booking",
                kwargs={"property_id": self.property.pk},
            ),
            data=json.dumps({
                "start": (
                    date.today() + timedelta(days=5)
                ).isoformat(),
                "end": (
                    date.today() + timedelta(days=7)
                ).isoformat(),
                **payload,
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

class BookingCancellationViewTestCase(BookingTestBase):

    def test_delete_booking_rejects_non_post_request(self):
        self.client.force_login(self.tenant)

        booking = Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data
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
    
    def test_delete_booking_cancels_confirmed_booking(self):
        self.client.force_login(self.tenant)

        booking = Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            status="CONFIRMED",
            **self.booking_data
        )

        response = self.client.post(
            reverse(
                "delete_booking",
                kwargs={"booking_id": booking.pk},
            )
        )

        self.assertEqual(response.status_code, 302)

        booking.refresh_from_db()

        self.assertEqual(booking.status, "CANCELLED")
        self.assertTrue(
            Booking.objects.filter(pk=booking.pk).exists()
        )

    def test_delete_booking_rejects_booking_from_another_user(self):
        other_tenant = User.objects.create_user(
            username="other-tenant",
            email="other-tenant@test.com",
            password="123",
        )

        booking = Booking.objects.create(
            tenant=other_tenant,
            property=self.property,
            initial_date=date.today() + timedelta(days=5),
            final_date=date.today() + timedelta(days=7),
            status="CONFIRMED",
            **self.booking_data
        )

        self.client.force_login(self.tenant)

        response = self.client.post(
            reverse(
                "delete_booking",
                kwargs={"booking_id": booking.pk},
            )
        )

        self.assertEqual(response.status_code, 403)

        booking.refresh_from_db()

        self.assertEqual(booking.status, "CONFIRMED")

class BookingConcurrencyTestCase(TransactionTestCase):

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
            owner=self.owner,
        )

        self.booking_data = {
            "guest_first_name": "Juan",
            "guest_last_name": "García",
            "guest_email": "juan@example.com",
            "guest_phone_number": "+34600111222",
            "guest_country": "España",
            "guest_region": "Madrid",
            "guest_city": "Madrid",
            "guest_postal_code": "28001",
            "guest_address": "Calle Mayor 1",
            "is_for_self": True,
            "is_business_trip": False,
            "tax_id": "",
            "guest_count": 2,
            "special_requests": "",
            "arrival_time": time(18, 0),
        }

    def test_database_rejects_overlapping_active_booking(self):
        initial_date = date.today() + timedelta(days=5)
        final_date = initial_date + timedelta(days=7)

        booking1 = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=initial_date,
            final_date=final_date,
            status="CONFIRMED",
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data,
        )
        booking1.save_base(force_insert=True)

        booking2 = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=initial_date,
            final_date=final_date,
            status="CONFIRMED",
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data,
        )

        with self.assertRaises(IntegrityError):
            booking2.save_base(force_insert=True)

    def test_database_rejects_pending_and_confirmed_overlap(self):
        initial_date = date.today() + timedelta(days=5)
        final_date = date.today() + timedelta(days=7)

        booking1 = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=initial_date,
            final_date=final_date,
            status="PENDING",
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data,
        )
        booking1.save_base(force_insert=True)

        booking2 = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=initial_date,
            final_date=final_date,
            status="CONFIRMED",
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data,
        )

        with self.assertRaises(IntegrityError):
            booking2.save_base(force_insert=True)

    def test_database_rejects_confirmed_and_pending_overlap(self):
        initial_date = date.today() + timedelta(days=5)
        final_date = date.today() + timedelta(days=7)

        booking1 = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=initial_date,
            final_date=final_date,
            status="CONFIRMED",
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data,
        )
        booking1.save_base(force_insert=True)

        booking2 = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=initial_date,
            final_date=final_date,
            status="PENDING",
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data,
        )

        with self.assertRaises(IntegrityError):
            booking2.save_base(force_insert=True)

    def test_database_allows_overlap_with_cancelled_booking(self):
        initial_date = date.today() + timedelta(days=5)
        final_date = date.today() + timedelta(days=7)

        Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=initial_date,
            final_date=final_date,
            status="CANCELLED",
            **self.booking_data,
        )

        booking = Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=initial_date,
            final_date=final_date,
            status="CONFIRMED",
            **self.booking_data,
        )

        self.assertIsNotNone(booking.pk)

    def test_database_allows_overlap_with_expired_booking(self):
        initial_date = date.today() + timedelta(days=5)
        final_date = date.today() + timedelta(days=7)

        Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=initial_date,
            final_date=final_date,
            status="EXPIRED",
            **self.booking_data,
        )

        booking = Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=initial_date,
            final_date=final_date,
            status="CONFIRMED",
            **self.booking_data,
        )

        self.assertIsNotNone(booking.pk)

    def test_concurrent_booking_creation_allows_only_one_booking(self):
        initial_date = date.today() + timedelta(days=5)
        final_date = initial_date + timedelta(days=7)

        barrier = Barrier(2)

        def create_booking():
            close_old_connections()

            try:
                for attempt in range(5):
                    try:
                        with transaction.atomic():
                            booking = Booking(
                                tenant=self.tenant,
                                property=self.property,
                                initial_date=initial_date,
                                final_date=final_date,
                                status="CONFIRMED",
                                expires_at=timezone.now() + timedelta(minutes=15),
                                **self.booking_data,
                            )

                            if attempt == 0:
                                barrier.wait(timeout=5)

                            booking.save_base(force_insert=True)

                        return "created"

                    except IntegrityError:
                        return "rejected"

                    except OperationalError as exc:
                        cause = exc.__cause__

                        sqlstate = (
                            getattr(cause, "sqlstate", None)
                            or getattr(cause, "pgcode", None)
                        )

                        if sqlstate != "40P01":
                            raise

                        if attempt == 4:
                            raise

                        time_module.sleep(0.1 * (attempt + 1))

                raise AssertionError("Se agotaron los reintentos de creación.")

            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda _: create_booking(),
                    range(2),
                )
            )

        self.assertCountEqual(results, ["created", "rejected"])

        self.assertEqual(
            Booking.objects.filter(
                property=self.property,
                initial_date=initial_date,
                final_date=final_date,
                status="CONFIRMED",
            ).count(),
            1,
        )

    def test_concurrent_pending_booking_creation_allows_only_one_booking(self):
        initial_date = date.today() + timedelta(days=5)
        final_date = initial_date + timedelta(days=7)
        expires_at = timezone.now() + timedelta(minutes=15)

        barrier = Barrier(2)
        original_create_pending = Booking.create_pending

        def synchronized_create_pending(*args, **kwargs):
            barrier.wait(timeout=10)
            return original_create_pending(*args, **kwargs)

        def create_pending_booking():
            close_old_connections()

            try:
                Booking.create_pending(
                    tenant=self.tenant,
                    property=self.property,
                    initial_date=initial_date,
                    final_date=final_date,
                    expires_at=expires_at,
                    **self.booking_data,
                )
                return "created"

            except (IntegrityError, ValidationError):
                return "rejected"

            finally:
                close_old_connections()

        with patch.object(
            Booking,
            "create_pending",
            side_effect=synchronized_create_pending,
        ):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(
                    executor.map(
                        lambda _: create_pending_booking(),
                        range(2),
                    )
                )

        self.assertEqual(results.count("created"), 1)
        self.assertEqual(results.count("rejected"), 1)

        bookings = Booking.objects.filter(
            property=self.property,
            initial_date=initial_date,
            final_date=final_date,
            status="PENDING",
        )

        self.assertEqual(bookings.count(), 1)

        booking = bookings.get()

        expected_nights = (final_date - initial_date).days

        self.assertEqual(
            BookingNight.objects.filter(
                booking=booking,
            ).count(),
            expected_nights,
        )

        self.assertEqual(
            Booking.objects.filter(
                property=self.property,
                initial_date=initial_date,
                final_date=final_date,
            ).count(),
            1,
        )

    def test_create_booking_returns_conflict_when_inventory_is_taken_concurrently(self):
        self.client.force_login(self.tenant)

        with patch(
            "bookings.models.Booking.create_pending",
            side_effect=IntegrityError,
        ):
            response = self.client.post(
                reverse(
                    "confirm_booking",
                    kwargs={"property_id": self.property.pk},
                ),
                data={
                    "start": (
                        date.today() + timedelta(days=5)
                    ).isoformat(),
                    "end": (
                        date.today() + timedelta(days=7)
                    ).isoformat(),
                    **self.booking_data,
                },
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["error"],
            "El alojamiento ya está reservado en esas fechas.",
        )

    def test_database_allows_adjacent_booking_dates(self):
        initial_date = date.today() + timedelta(days=5)
        final_date = initial_date + timedelta(days=7)

        booking1 = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=initial_date,
            final_date=final_date,
            status="CONFIRMED",
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data,
        )
        booking1.save_base(force_insert=True)

        booking2 = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=final_date,
            final_date=final_date + timedelta(days=3),
            status="CONFIRMED",
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data,
        )
        booking2.save_base(force_insert=True)

        self.assertIsNotNone(booking2.pk)

    def test_database_allows_same_dates_on_different_property(self):
        other_property = Property.objects.create(
            title="Otra casa",
            description="Desc",
            location="Madrid",
            default_price_per_night=80,
            image="test.jpg",
            children=2,
            adults=2,
            rooms=2,
            owner=self.owner,
        )

        initial_date = date.today() + timedelta(days=5)
        final_date = initial_date + timedelta(days=7)

        booking1 = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=initial_date,
            final_date=final_date,
            status="CONFIRMED",
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data,
        )
        booking1.save_base(force_insert=True)

        booking2 = Booking(
            tenant=self.tenant,
            property=other_property,
            initial_date=initial_date,
            final_date=final_date,
            status="CONFIRMED",
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data,
        )
        booking2.save_base(force_insert=True)

        self.assertIsNotNone(booking2.pk)

    def test_database_allows_expired_historical_pending_booking(self):
        initial_date = date.today() + timedelta(days=5)
        final_date = initial_date + timedelta(days=7)

        now = timezone.now()

        expired_booking = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=initial_date,
            final_date=final_date,
            created_at=now - timedelta(minutes=20),
            status="PENDING",
            expires_at=now - timedelta(minutes=5),
            **self.booking_data,
        )
        expired_booking.save_base(force_insert=True)

        booking = Booking(
            tenant=self.tenant,
            property=self.property,
            initial_date=initial_date,
            final_date=final_date,
            created_at=now,
            status="CONFIRMED",
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data,
        )
        booking.save_base(force_insert=True)

        self.assertIsNotNone(booking.pk)

    def test_concurrent_confirm_and_cancel_are_serialized(self):
        initial_date = date.today() + timedelta(days=5)
        final_date = initial_date + timedelta(days=7)

        booking = Booking.create_pending(
            tenant=self.tenant,
            property=self.property,
            initial_date=initial_date,
            final_date=final_date,
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data,
        )

        barrier = Barrier(2)

        def confirm_booking():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                return booking.confirm()
            finally:
                close_old_connections()

        def cancel_booking():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                return booking.cancel()
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            confirm_future = executor.submit(confirm_booking)
            cancel_future = executor.submit(cancel_booking)

            confirm_result = confirm_future.result()
            cancel_result = cancel_future.result()

        booking.refresh_from_db()

        self.assertTrue(confirm_result)
        self.assertIn(booking.status, {"CONFIRMED", "CANCELLED"})

        if booking.status == "CONFIRMED":
            self.assertFalse(cancel_result)
        else:
            self.assertTrue(cancel_result)

    def test_concurrent_confirm_calls_allow_only_one_confirmation(self):
        initial_date = date.today() + timedelta(days=5)
        final_date = initial_date + timedelta(days=7)

        booking = Booking.create_pending(
            tenant=self.tenant,
            property=self.property,
            initial_date=initial_date,
            final_date=final_date,
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data,
        )

        barrier = Barrier(2)

        def confirm_booking():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                return booking.confirm()
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda _: confirm_booking(),
                    range(2),
                )
            )

        booking.refresh_from_db()

        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), 1)
        self.assertEqual(booking.status, "CONFIRMED")

    def test_concurrent_change_proposal_creation_allows_only_one_pending_proposal(self):
        initial_date = date.today() + timedelta(days=30)
        final_date = initial_date + timedelta(days=33)

        booking = Booking.objects.create(
            tenant=self.tenant,
            property=self.property,
            initial_date=initial_date,
            final_date=final_date,
            status="CONFIRMED",
            expires_at=None,
            **self.booking_data,
        )

        OwnerProfile.objects.update_or_create(
            user_id=self.owner.pk,
            defaults={"status": "APPROVED"},
        )

        self.assertEqual(booking.property.owner_id, self.owner.pk)

        owner_check = User.objects.select_related("owner_profile").get(
            pk=self.owner.pk
        )
        self.assertTrue(owner_check.is_approved_owner)

        barrier = Barrier(2)

        def create_proposal():
            close_old_connections()

            try:
                client = Client()
                owner = User.objects.select_related("owner_profile").get(
                    pk=self.owner.pk
                )

                client.force_login(owner)

                payload = {
                    "proposed_initial_date": (
                        initial_date + timedelta(days=1)
                    ).isoformat(),
                    "proposed_final_date": (
                        final_date + timedelta(days=1)
                    ).isoformat(),
                    "proposed_guest_count": 2,
                }

                barrier.wait(timeout=10)

                response = client.post(
                    reverse(
                        "propose_booking_change",
                        kwargs={"booking_id": booking.pk},
                    ),
                    data=json.dumps(payload),
                    content_type="application/json",
                )

                return response.status_code

            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(create_proposal)
                for _ in range(2)
            ]
            results = [future.result(timeout=20) for future in futures]

        self.assertCountEqual(results, [201, 409])

        self.assertEqual(
            BookingChangeProposal.objects.filter(
                booking_id=booking.pk,
                status=BookingChangeProposal.Status.PENDING,
            ).count(),
            1,
        )
    
    def test_concurrent_admin_changes_to_same_booking_keep_audits_consistent(self):

        admin = User.objects.create_superuser(
            username="concurrent-admin",
            email="concurrent-admin@example.com",
            password="test-password",
        )

        initial_date = date.today() + timedelta(days=30)
        final_date = initial_date + timedelta(days=3)

        booking = Booking.create_pending(
            tenant=self.tenant,
            property=self.property,
            initial_date=initial_date,
            final_date=final_date,
            expires_at=timezone.now() + timedelta(minutes=15),
            **self.booking_data,
        )
        self.assertTrue(booking.confirm())
        booking.refresh_from_db()

        original_night_count = booking.nights.count()

        payloads = [
            {
                "initial_date": (
                    date.today() + timedelta(days=40)
                ).isoformat(),
                "final_date": (
                    date.today() + timedelta(days=44)
                ).isoformat(),
                "guest_count": 2,
            },
            {
                "initial_date": (
                    date.today() + timedelta(days=50)
                ).isoformat(),
                "final_date": (
                    date.today() + timedelta(days=54)
                ).isoformat(),
                "guest_count": 2,
            },
        ]

        barrier = Barrier(2)
        url = reverse(
            "admin_force_booking_change",
            args=[booking.pk],
        )

        def force_change(payload):
            close_old_connections()
            try:
                client = Client()
                client.force_login(admin)
                barrier.wait(timeout=10)

                response = client.post(url, payload)

                return response.status_code, response.json()
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(force_change, payload)
                for payload in payloads
            ]
            results = [
                future.result(timeout=30)
                for future in futures
            ]

        self.assertEqual(
            [status for status, _ in results],
            [200, 200],
        )

        booking.refresh_from_db()

        audits = list(
            BookingChangeAudit.objects.filter(
                booking=booking,
            ).order_by("changed_at", "pk")
        )

        self.assertEqual(len(audits), 2)

        # Cada auditoría debe reflejar uno de los cambios solicitados.
        requested_ranges = {
            (
                payload["initial_date"],
                payload["final_date"],
            )
            for payload in payloads
        }

        audit_after_ranges = {
            (
                audit.after_values["initial_date"],
                audit.after_values["final_date"],
            )
            for audit in audits
        }

        self.assertEqual(audit_after_ranges, requested_ranges)

        # El estado final de la reserva debe coincidir con una auditoría.
        self.assertIn(
            (
                booking.initial_date.isoformat(),
                booking.final_date.isoformat(),
            ),
            audit_after_ranges,
        )

        # Las noches deben corresponder al intervalo final.
        actual_nights = list(
            booking.nights.order_by("date").values_list("date", flat=True)
        )

        expected_nights = [
            booking.initial_date + timedelta(days=offset)
            for offset in range(
                (booking.final_date - booking.initial_date).days
            )
        ]

        self.assertEqual(actual_nights, expected_nights)
        self.assertNotEqual(len(actual_nights), 0)
        self.assertEqual(original_night_count, 3)

    def test_concurrent_admin_changes_cannot_double_book_inventory(self):
        from datetime import timedelta
        from django.test import Client
        from django.urls import reverse
        from django.utils import timezone

        admin = User.objects.create_superuser(
            username="inventory-admin",
            email="inventory-admin@example.com",
            password="test-password",
        )

        def create_confirmed_booking(start_day):
            start = date.today() + timedelta(days=start_day)

            booking = Booking.create_pending(
                tenant=self.tenant,
                property=self.property,
                initial_date=start,
                final_date=start + timedelta(days=3),
                expires_at=timezone.now() + timedelta(minutes=15),
                **self.booking_data,
            )

            self.assertTrue(booking.confirm())
            booking.refresh_from_db()
            return booking

        booking1 = create_confirmed_booking(30)
        booking2 = create_confirmed_booking(60)

        original_dates = {
            booking1.pk: (
                booking1.initial_date,
                booking1.final_date,
            ),
            booking2.pk: (
                booking2.initial_date,
                booking2.final_date,
            ),
        }

        original_nights = {
            booking.pk: list(
                booking.nights.order_by("date").values_list(
                    "date", "price_per_night"
                )
            )
            for booking in (booking1, booking2)
        }

        proposals = {
            booking.pk: BookingChangeProposal.objects.create(
                booking=booking,
                proposed_initial_date=date.today() + timedelta(days=130),
                proposed_final_date=date.today() + timedelta(days=134),
                proposed_guest_count=2,
            )
            for booking in (booking1, booking2)
        }

        target_start = date.today() + timedelta(days=90)
        target_end = target_start + timedelta(days=4)

        barrier = Barrier(2)

        def force_change(booking_id):
            close_old_connections()
            try:
                client = Client()
                client.force_login(admin)

                payload = {
                    "initial_date": target_start.isoformat(),
                    "final_date": target_end.isoformat(),
                    "guest_count": 2,
                }

                url = reverse(
                    "admin_force_booking_change",
                    args=[booking_id],
                )

                barrier.wait(timeout=10)
                response = client.post(url, payload)

                return booking_id, response.status_code, response.json()
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(force_change, booking1.pk),
                executor.submit(force_change, booking2.pk),
            ]
            results = [
                future.result(timeout=30)
                for future in futures
            ]

        successful = [
            result for result in results
            if result[1] == 200
        ]
        rejected = [
            result for result in results
            if result[1] in (400, 409)
        ]

        self.assertEqual(len(successful), 1)
        self.assertEqual(len(rejected), 1)

        winner_id = successful[0][0]
        loser_id = rejected[0][0]

        winner = Booking.objects.get(pk=winner_id)
        loser = Booking.objects.get(pk=loser_id)

        self.assertEqual(winner.initial_date, target_start)
        self.assertEqual(winner.final_date, target_end)

        # El perdedor debe conservar sus fechas y noches originales.
        self.assertEqual(
            (loser.initial_date, loser.final_date),
            original_dates[loser_id],
        )
        self.assertEqual(
            list(
                loser.nights.order_by("date").values_list(
                    "date", "price_per_night"
                )
            ),
            original_nights[loser_id],
        )

        # Solo el cambio exitoso debe crear una auditoría.
        self.assertEqual(
            BookingChangeAudit.objects.filter(
                booking_id__in=[booking1.pk, booking2.pk],
            ).count(),
            1,
        )

        proposals[winner_id].refresh_from_db()
        proposals[loser_id].refresh_from_db()

        self.assertEqual(proposals[winner_id].status, "EXPIRED")
        self.assertEqual(proposals[loser_id].status, "PENDING")

        # No pueden quedar dos reservas activas ocupando el mismo intervalo.
        overlapping_bookings = Booking.objects.filter(
            property=self.property,
            initial_date__lt=target_end,
            final_date__gt=target_start,
            status__in=Booking.ACTIVE_STATUSES,
        )

        self.assertEqual(overlapping_bookings.count(), 1)
        self.assertEqual(
            overlapping_bookings.get().pk,
            winner_id,
        )

class ExpirePendingBookingsCommandTestCase(TestCase):

    def test_command_reports_zero_when_no_bookings_expire(self):
        output = StringIO()
        call_command("expire_pending_bookings", stdout=output)
        self.assertIn("Reservas expiradas: 0", output.getvalue())

    def test_command_expires_overdue_pending_bookings(self):
        booking = Booking.objects.create(
            tenant=User.objects.create_user(
                username="command_tenant",
                password="password123",
                email="command_tenant@example.com",
            ),
            property=Property.objects.create(
                owner=User.objects.create_user(
                    username="command_owner",
                    password="password123",
                    email="command_owner@example.com",
                ),
                title="Command test property",
                description="Property for expiration command test",
                location="Test location",
                default_price_per_night=Decimal("80.00"),
                image="properties/test.jpg",
                children=0,
                adults=2,
                rooms=1,
            ),
            initial_date=date.today() + timedelta(days=10),
            final_date=date.today() + timedelta(days=12),
            status="PENDING",
            expires_at=timezone.now() + timedelta(minutes=5),
            guest_first_name="Test",
            guest_last_name="Tenant",
            guest_email="guest@example.com",
            guest_phone_number="+34611456789",
            guest_country="Spain",
            guest_city="Madrid",
            guest_address="Test address",
            guest_count=1,
            arrival_time=time(15, 0),
        )

        Booking.objects.filter(pk=booking.pk).update(
            expires_at=timezone.now() - timedelta(minutes=5)
        )

        output = StringIO()
        call_command("expire_pending_bookings", stdout=output)

        booking.refresh_from_db()

        self.assertEqual(booking.status, "EXPIRED")
        self.assertIn("Reservas expiradas: 1", output.getvalue())

    def test_command_is_idempotent(self):
        output_first = StringIO()
        output_second = StringIO()

        call_command("expire_pending_bookings", stdout=output_first)
        call_command("expire_pending_bookings", stdout=output_second)

        self.assertIn("Reservas expiradas: 0", output_first.getvalue())
        self.assertIn("Reservas expiradas: 0", output_second.getvalue())


class BookingChangeProposalModelTestCase(BookingTestBase):

    def create_proposal(self, **overrides):
        
        if not self.booking1.pk:
            self.booking1.save()

        _, token_hash = generate_proposal_access_token()

        data = {
            "booking": self.booking1,
            "proposed_initial_date": self.booking1.initial_date,
            "proposed_final_date": self.booking1.final_date,
            "proposed_guest_count": 2,
            "access_token_hash": token_hash,
        }
        data.update(overrides)

        return BookingChangeProposal.objects.create(**data)

    def test_creates_pending_proposal_with_48_hour_expiration(self):
        proposal = self.create_proposal()

        self.assertEqual(
            proposal.status,
            BookingChangeProposal.Status.PENDING,
        )
        self.assertEqual(
            proposal.expires_at,
            proposal.created_at + timedelta(hours=48),
        )

    def test_rejects_invalid_date_range(self):
        with self.assertRaises(ValidationError):
            self.create_proposal(
                proposed_initial_date=date(2026, 8, 20),
                proposed_final_date=date(2026, 8, 20),
            )

    def test_rejects_guest_count_above_property_capacity(self):
        capacity = self.property.adults + self.property.children

        with self.assertRaises(ValidationError):
            self.create_proposal(
                proposed_guest_count=capacity + 1,
            )

    def test_rejects_zero_guests(self):
        with self.assertRaises(ValidationError):
            self.create_proposal(proposed_guest_count=0)

    def test_only_one_pending_proposal_per_booking(self):
        self.create_proposal()

        with self.assertRaises(ValidationError):
            self.create_proposal()

    def test_allows_new_proposal_after_previous_is_rejected(self):
        first = self.create_proposal()
        first.status = BookingChangeProposal.Status.REJECTED
        first.save()

        second = self.create_proposal()

        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(
            second.status,
            BookingChangeProposal.Status.PENDING,
        )

    def test_proposal_expires_after_48_hours(self):
        proposal = self.create_proposal()

        self.assertFalse(proposal.is_expired())

        future_time = proposal.expires_at + timedelta(seconds=1)

        with patch("bookings.models.timezone.now", return_value=future_time):
            self.assertTrue(proposal.is_expired())

    def test_each_proposal_has_an_access_token_hash(self):
        first = self.create_proposal()

        first.status = BookingChangeProposal.Status.REJECTED
        first.save(update_fields=["status"])

        second = self.create_proposal()

        self.assertTrue(first.access_token_hash)
        self.assertTrue(second.access_token_hash)
        self.assertNotEqual(
            first.access_token_hash,
            second.access_token_hash,
        )

class BookingChangeProposalViewTestCase(BookingTestBase):
    def setUp(self):
        super().setUp()

        OwnerProfile.objects.create(
            user=self.owner,
            status="APPROVED",
        )

        self.booking1.initial_date = date.today() + timedelta(days=30)
        self.booking1.final_date = date.today() + timedelta(days=33)
        self.booking1.expires_at = timezone.now() + timedelta(minutes=15)
        self.booking1.save()

        self.url = reverse(
            "propose_booking_change",
            kwargs={"booking_id": self.booking1.pk},
        )

        self.payload = {
            "proposed_initial_date": (
                self.booking1.initial_date + timedelta(days=1)
            ).isoformat(),
            "proposed_final_date": (
                self.booking1.final_date + timedelta(days=1)
            ).isoformat(),
            "proposed_guest_count": 2,
        }

    def test_approved_owner_can_create_proposal(self):

        # Preparar noches existentes con precios distintos.
        BookingNight.objects.create(
            booking=self.booking1,
            date=self.booking1.initial_date,
            price_per_night=Decimal("80.00"),
        )
        BookingNight.objects.create(
            booking=self.booking1,
            date=self.booking1.initial_date + timedelta(days=1),
            price_per_night=Decimal("95.00"),
        )

        # Guardar el estado original completo que debe permanecer intacto.
        original_initial_date = self.booking1.initial_date
        original_final_date = self.booking1.final_date
        original_guest_count = self.booking1.guest_count
        original_status = self.booking1.status
        original_expires_at = self.booking1.expires_at

        original_nights = list(
            self.booking1.nights.order_by("date").values_list(
                "date", "price_per_night"
            )
        )

        self.client.force_login(self.owner)

        response = self.client.post(
            self.url,
            data=json.dumps(self.payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)

        self.assertEqual(
            BookingChangeProposal.objects.filter(
                booking=self.booking1,
                status=BookingChangeProposal.Status.PENDING,
            ).count(),
            1,
        )

        # La propuesta no debe modificar la reserva original.
        self.booking1.refresh_from_db()

        self.assertEqual(self.booking1.initial_date, original_initial_date)
        self.assertEqual(self.booking1.final_date, original_final_date)
        self.assertEqual(self.booking1.guest_count, original_guest_count)
        self.assertEqual(self.booking1.status, original_status)
        self.assertEqual(self.booking1.expires_at, original_expires_at)

        current_nights = list(
            self.booking1.nights.order_by("date").values_list(
                "date", "price_per_night"
            )
        )
        self.assertEqual(current_nights, original_nights)

        proposal = BookingChangeProposal.objects.get(
            booking=self.booking1,
            status=BookingChangeProposal.Status.PENDING,
        )

        self.assertTrue(proposal.access_token_hash)
        self.assertNotIn(
            proposal.access_token_hash,
            response.content.decode(),
        )

    def test_non_owner_cannot_create_proposal(self):
        self.client.force_login(self.tenant)

        response = self.client.post(
            self.url,
            data=json.dumps(self.payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            BookingChangeProposal.objects.filter(
                booking=self.booking1,
            ).exists()
        )

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.post(
            self.url,
            data=json.dumps(self.payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 302)

    def test_anonymous_booking_can_have_change_proposal(self):

        self.booking1.tenant = None
        self.booking1.save()

        self.client.force_login(self.owner)

        response = self.client.post(
            self.url,
            data=json.dumps(self.payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)

        proposal = BookingChangeProposal.objects.get(
            booking=self.booking1,
            status=BookingChangeProposal.Status.PENDING,
        )

        self.assertIsNotNone(proposal.expires_at)

        self.booking1.refresh_from_db()
        self.assertEqual(
            self.booking1.initial_date,
            date.today() + timedelta(days=30),
        )
        self.assertIsNone(self.booking1.tenant)
        self.assertTrue(proposal.access_token_hash)

    def test_invalid_date_range_is_rejected(self):
        self.client.force_login(self.owner)

        payload = {
            **self.payload,
            "proposed_initial_date": "2030-08-10",
            "proposed_final_date": "2030-08-09",
        }

        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_guest_count_over_capacity_is_rejected(self):
        self.client.force_login(self.owner)

        payload = {
            **self.payload,
            "proposed_guest_count": 5,
        }

        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_duplicate_pending_proposal_returns_conflict(self):
        self.client.force_login(self.owner)

        first_response = self.client.post(
            self.url,
            data=json.dumps(self.payload),
            content_type="application/json",
        )

        second_response = self.client.post(
            self.url,
            data=json.dumps(self.payload),
            content_type="application/json",
        )

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 409)

    def test_new_proposal_can_be_created_after_previous_one_expires(self):

        self.client.force_login(self.owner)

        first_response = self.client.post(
            self.url,
            data=json.dumps(self.payload),
            content_type="application/json",
        )
        self.assertEqual(first_response.status_code, 201)

        first_proposal = BookingChangeProposal.objects.get(
            booking=self.booking1,
            status=BookingChangeProposal.Status.PENDING,
        )

        BookingChangeProposal.objects.filter(
            pk=first_proposal.pk
        ).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )

        second_response = self.client.post(
            self.url,
            data=json.dumps(self.payload),
            content_type="application/json",
        )

        self.assertEqual(second_response.status_code, 201)

        first_proposal.refresh_from_db()

        self.assertEqual(
            first_proposal.status,
            BookingChangeProposal.Status.EXPIRED,
        )

        self.assertEqual(
            BookingChangeProposal.objects.filter(
                booking=self.booking1,
                status=BookingChangeProposal.Status.PENDING,
            ).count(),
            1,
        )

class BookingChangeProposalRejectViewTestCase(BookingTestBase):
    def setUp(self):
        super().setUp()

        self.booking1.initial_date = date.today() + timedelta(days=30)
        self.booking1.final_date = date.today() + timedelta(days=33)
        self.booking1.expires_at = timezone.now() + timedelta(minutes=15)
        self.booking1.save()

        self.url = reverse(
            "reject_booking_change_proposal",
            kwargs={"proposal_id": self._create_proposal().pk},
        )

    def _create_proposal(self):
        return BookingChangeProposal.objects.create(
            booking=self.booking1,
            proposed_initial_date=self.booking1.initial_date + timedelta(days=1),
            proposed_final_date=self.booking1.final_date + timedelta(days=1),
            proposed_guest_count=2,
        )

    def test_guest_can_reject_pending_proposal(self):
        self.client.force_login(self.tenant)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 200)

        proposal = BookingChangeProposal.objects.get(
            booking=self.booking1
        )
        self.assertEqual(
            proposal.status,
            BookingChangeProposal.Status.REJECTED,
        )

    def test_non_guest_cannot_reject_proposal(self):
        self.client.force_login(self.owner)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 403)

        proposal = BookingChangeProposal.objects.get(
            booking=self.booking1
        )
        self.assertEqual(
            proposal.status,
            BookingChangeProposal.Status.PENDING,
        )

    def test_rejecting_proposal_does_not_modify_booking_or_nights(self):
        from decimal import Decimal

        BookingNight.objects.create(
            booking=self.booking1,
            date=self.booking1.initial_date,
            price_per_night=Decimal("80.00"),
        )
        BookingNight.objects.create(
            booking=self.booking1,
            date=self.booking1.initial_date + timedelta(days=1),
            price_per_night=Decimal("95.00"),
        )

        original_initial_date = self.booking1.initial_date
        original_final_date = self.booking1.final_date
        original_status = self.booking1.status
        original_guest_count = self.booking1.guest_count

        original_nights = list(
            self.booking1.nights.order_by("date").values_list(
                "date", "price_per_night"
            )
        )

        self.client.force_login(self.tenant)
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 200)

        self.booking1.refresh_from_db()
        self.assertEqual(self.booking1.initial_date, original_initial_date)
        self.assertEqual(self.booking1.final_date, original_final_date)
        self.assertEqual(self.booking1.status, original_status)
        self.assertEqual(self.booking1.guest_count, original_guest_count)

        current_nights = list(
            self.booking1.nights.order_by("date").values_list(
                "date", "price_per_night"
            )
        )
        self.assertEqual(current_nights, original_nights)

    def test_rejecting_already_rejected_proposal_returns_conflict(self):
        self.client.force_login(self.tenant)

        first_response = self.client.post(self.url)
        self.assertEqual(first_response.status_code, 200)

        second_response = self.client.post(self.url)
        self.assertEqual(second_response.status_code, 409)

    def test_get_request_is_not_allowed(self):
        self.client.force_login(self.tenant)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)

    def test_rejecting_proposal_allows_booking_proposed_dates(self):
        proposal = BookingChangeProposal.objects.get(
            booking=self.booking1
        )
        proposed_start = self.booking1.initial_date + timedelta(days=10)
        proposed_end = self.booking1.final_date + timedelta(days=10)

        proposal.proposed_initial_date = proposed_start
        proposal.proposed_final_date = proposed_end
        proposal.save(
            update_fields=[
                "proposed_initial_date",
                "proposed_final_date",
            ]
        )

        self.client.force_login(self.tenant)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)

        proposal.refresh_from_db()
        self.assertEqual(
            proposal.status,
            BookingChangeProposal.Status.REJECTED,
        )

        payload = {
            "start": proposed_start.isoformat(),
            "end": proposed_end.isoformat(),
            **self.booking_payload,
        }

        response = self.client.post(
            reverse(
                "confirm_booking",
                kwargs={"property_id": self.booking1.property_id},
            ),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(
            response.status_code,
            200,
            response.content.decode(),
        )

class BookingChangeProposalAcceptViewTestCase(BookingTestBase):
    def setUp(self):
        super().setUp()

        from datetime import timedelta
        from decimal import Decimal

        from django.urls import reverse
        from django.utils import timezone

        self.timedelta = timedelta
        self.Decimal = Decimal
        self.reverse = reverse
        self.timezone = timezone

        self.booking1.initial_date = timezone.localdate() + timedelta(days=30)
        self.booking1.final_date = timezone.localdate() + timedelta(days=33)
        self.booking1.status = "CONFIRMED"
        self.booking1.expires_at = None
        self.booking1.save()

        self.initial_status = self.booking1.status
        self.initial_expires_at = self.booking1.expires_at

        self.proposal = BookingChangeProposal.objects.create(
            booking=self.booking1,
            proposed_initial_date=timezone.localdate() + timedelta(days=40),
            proposed_final_date=timezone.localdate() + timedelta(days=44),
            proposed_guest_count=3,
        )

        self.client.force_login(self.tenant)

    def accept_url(self):
        return self.reverse(
            "accept_booking_change_proposal",
            args=[self.proposal.pk],
        )

    def test_guest_can_accept_proposal(self):
        response = self.client.post(self.accept_url())

        self.assertEqual(response.status_code, 200)

        self.proposal.refresh_from_db()
        self.booking1.refresh_from_db()

        self.assertEqual(
            self.proposal.status,
            BookingChangeProposal.Status.ACCEPTED,
        )
        self.assertEqual(
            self.booking1.initial_date,
            self.proposal.proposed_initial_date,
        )
        self.assertEqual(
            self.booking1.final_date,
            self.proposal.proposed_final_date,
        )
        self.assertEqual(
            self.booking1.guest_count,
            self.proposal.proposed_guest_count,
        )
        self.assertEqual(self.booking1.status, self.initial_status)
        self.assertEqual(self.booking1.expires_at, self.initial_expires_at)

        nights = list(
            self.booking1.nights.order_by("date").values_list("date", flat=True)
        )

        expected_nights = [
            self.proposal.proposed_initial_date + self.timedelta(days=offset)
            for offset in range(
                (
                    self.proposal.proposed_final_date
                    - self.proposal.proposed_initial_date
                ).days
            )
        ]

        self.assertEqual(nights, expected_nights)

    def test_acceptance_uses_current_nightly_prices(self):
        from bookings.models import PropertyAvailability

        start_date = self.proposal.proposed_initial_date
        end_date = self.proposal.proposed_final_date

        current_date = start_date
        expected_prices = {}

        while current_date < end_date:
            price = self.Decimal("175.00")
            PropertyAvailability.objects.update_or_create(
                property=self.booking1.property,
                date=current_date,
                defaults={
                    "price_per_night": price,
                    "status": "OPEN",
                    "min_nights": 1,
                },
            )
            expected_prices[current_date] = price
            current_date += self.timedelta(days=1)

        response = self.client.post(self.accept_url())

        self.assertEqual(response.status_code, 200)

        actual_prices = dict(
            self.booking1.nights.values_list("date", "price_per_night")
        )

        self.assertEqual(actual_prices, expected_prices)
        self.assertEqual(
            self.booking1.total_price,
            sum(expected_prices.values(), self.Decimal("0.00")),
        )

    def test_non_guest_cannot_accept_proposal(self):
        self.client.force_login(self.owner)

        response = self.client.post(self.accept_url())

        self.assertEqual(response.status_code, 403)

        self.proposal.refresh_from_db()
        self.booking1.refresh_from_db()

        self.assertEqual(
            self.proposal.status,
            BookingChangeProposal.Status.PENDING,
        )
        self.assertNotEqual(
            self.booking1.initial_date,
            self.proposal.proposed_initial_date,
        )

    def test_get_request_is_not_allowed(self):
        response = self.client.get(self.accept_url())

        self.assertEqual(response.status_code, 405)

    def test_already_rejected_proposal_cannot_be_accepted(self):
        self.proposal.status = BookingChangeProposal.Status.REJECTED
        self.proposal.save(update_fields=["status"])

        response = self.client.post(self.accept_url())

        self.assertEqual(response.status_code, 409)

        self.booking1.refresh_from_db()
        self.assertNotEqual(
            self.booking1.initial_date,
            self.proposal.proposed_initial_date,
        )
        
    def test_expired_proposal_cannot_be_accepted(self):
        BookingChangeProposal.objects.filter(
            pk=self.proposal.pk
        ).update(
            expires_at=self.timezone.now() - self.timedelta(minutes=1)
        )

        response = self.client.post(self.accept_url())

        self.assertEqual(response.status_code, 409)

        self.proposal.refresh_from_db()
        self.booking1.refresh_from_db()

        self.assertEqual(
            self.proposal.status,
            BookingChangeProposal.Status.EXPIRED,
        )
        self.assertEqual(
            self.booking1.initial_date,
            self.timezone.localdate() + self.timedelta(days=30),
        )
        self.assertEqual(
            self.booking1.final_date,
            self.timezone.localdate() + self.timedelta(days=33),
        )

    def test_failed_acceptance_preserves_original_booking_nights(self):
        from bookings.models import PropertyAvailability

        original_initial_date = self.booking1.initial_date
        original_final_date = self.booking1.final_date
        original_guest_count = self.booking1.guest_count

        original_nights = list(
            self.booking1.nights.order_by("date").values_list(
                "date", "price_per_night"
            )
        )

        PropertyAvailability.objects.update_or_create(
            property=self.booking1.property,
            date=self.proposal.proposed_initial_date,
            defaults={
                "status": "CLOSED",
                "min_nights": 1,
                "price_per_night": self.Decimal("80.00"),
            },
        )

        response = self.client.post(self.accept_url())

        self.assertEqual(response.status_code, 409)

        self.booking1.refresh_from_db()
        self.proposal.refresh_from_db()

        self.assertEqual(self.booking1.initial_date, original_initial_date)
        self.assertEqual(self.booking1.final_date, original_final_date)
        self.assertEqual(self.booking1.guest_count, original_guest_count)
        self.assertEqual(
            self.proposal.status,
            BookingChangeProposal.Status.PENDING,
        )
        self.assertEqual(
            list(
                self.booking1.nights.order_by("date").values_list(
                    "date", "price_per_night"
                )
            ),
            original_nights,
        )

    def test_cannot_accept_proposal_when_original_pending_booking_expired(self):

        Booking.objects.filter(pk=self.booking1.pk).update(
            status="PENDING",
            expires_at=self.timezone.now() - self.timedelta(minutes=1),
        )

        response = self.client.post(self.accept_url())

        self.assertEqual(response.status_code, 409)

        self.booking1.refresh_from_db()
        self.proposal.refresh_from_db()

        self.assertEqual(self.booking1.status, "PENDING")
        self.assertLessEqual(
            self.booking1.expires_at,
            self.timezone.now(),
        )
        self.assertEqual(
            self.booking1.initial_date,
            self.timezone.localdate() + self.timedelta(days=30),
        )
        self.assertEqual(
            self.booking1.final_date,
            self.timezone.localdate() + self.timedelta(days=33),
        )
        self.assertEqual(
            self.proposal.status,
            BookingChangeProposal.Status.PENDING,
        )

    def test_failed_night_creation_rolls_back_booking_and_proposal(self):

        original_initial_date = self.booking1.initial_date
        original_final_date = self.booking1.final_date
        original_guest_count = self.booking1.guest_count
        original_status = self.booking1.status
        original_expires_at = self.booking1.expires_at

        original_nights = list(
            self.booking1.nights.order_by("date").values_list(
                "date", "price_per_night"
            )
        )

        with patch(
            "bookings.views.BookingNight.objects.bulk_create",
            side_effect=RuntimeError("Simulated night creation failure"),
        ):
            with self.assertRaises(RuntimeError):
                self.client.post(self.accept_url())

        self.booking1.refresh_from_db()
        self.proposal.refresh_from_db()

        self.assertEqual(self.booking1.initial_date, original_initial_date)
        self.assertEqual(self.booking1.final_date, original_final_date)
        self.assertEqual(self.booking1.guest_count, original_guest_count)
        self.assertEqual(self.booking1.status, original_status)
        self.assertEqual(self.booking1.expires_at, original_expires_at)

        self.assertEqual(
            list(
                self.booking1.nights.order_by("date").values_list(
                    "date", "price_per_night"
                )
            ),
            original_nights,
        )

        self.assertEqual(
            self.proposal.status,
            BookingChangeProposal.Status.PENDING,
        )

    def test_failed_proposal_status_save_rolls_back_acceptance(self):
        original_initial_date = self.booking1.initial_date
        original_final_date = self.booking1.final_date
        original_guest_count = self.booking1.guest_count
        original_nights = list(
            self.booking1.nights.order_by("date").values_list(
                "date", "price_per_night"
            )
        )

        original_proposal_save = BookingChangeProposal.save

        def fail_when_accepting(proposal, *args, **kwargs):
            if (
                proposal.pk == self.proposal.pk
                and proposal.status == BookingChangeProposal.Status.ACCEPTED
            ):
                raise RuntimeError("Simulated proposal status save failure")

            return original_proposal_save(proposal, *args, **kwargs)

        with patch.object(
            BookingChangeProposal,
            "save",
            new=fail_when_accepting,
        ):
            with self.assertRaises(RuntimeError):
                self.client.post(self.accept_url())

        self.booking1.refresh_from_db()
        self.proposal.refresh_from_db()

        self.assertEqual(self.booking1.initial_date, original_initial_date)
        self.assertEqual(self.booking1.final_date, original_final_date)
        self.assertEqual(self.booking1.guest_count, original_guest_count)

        self.assertEqual(
            list(
                self.booking1.nights.order_by("date").values_list(
                    "date", "price_per_night"
                )
            ),
            original_nights,
        )

        self.assertEqual(
            self.proposal.status,
            BookingChangeProposal.Status.PENDING,
        )
    
    def test_failed_booking_save_preserves_original_state(self):
        original_initial_date = self.booking1.initial_date
        original_final_date = self.booking1.final_date
        original_guest_count = self.booking1.guest_count
        original_status = self.booking1.status
        original_expires_at = self.booking1.expires_at

        original_nights = list(
            self.booking1.nights.order_by("date").values_list(
                "date", "price_per_night"
            )
        )

        original_booking_save = Booking.save

        def fail_when_updating_dates(booking, *args, **kwargs):
            update_fields = kwargs.get("update_fields")

            if (
                booking.pk == self.booking1.pk
                and update_fields is not None
                and {
                    "initial_date",
                    "final_date",
                    "guest_count",
                }.issubset(set(update_fields))
            ):
                raise RuntimeError("Simulated booking save failure")

            return original_booking_save(booking, *args, **kwargs)

        with patch.object(
            Booking,
            "save",
            new=fail_when_updating_dates,
        ):
            with self.assertRaises(RuntimeError):
                self.client.post(self.accept_url())

        self.booking1.refresh_from_db()
        self.proposal.refresh_from_db()

        self.assertEqual(self.booking1.initial_date, original_initial_date)
        self.assertEqual(self.booking1.final_date, original_final_date)
        self.assertEqual(self.booking1.guest_count, original_guest_count)
        self.assertEqual(self.booking1.status, original_status)
        self.assertEqual(self.booking1.expires_at, original_expires_at)

        self.assertEqual(
            list(
                self.booking1.nights.order_by("date").values_list(
                    "date", "price_per_night"
                )
            ),
            original_nights,
        )

        self.assertEqual(
            self.proposal.status,
            BookingChangeProposal.Status.PENDING,
        )
    
    def test_pending_proposal_does_not_block_proposed_dates(self):

        competing_booking = Booking(
            tenant=self.tenant,
            property=self.booking1.property,
            initial_date=self.proposal.proposed_initial_date,
            final_date=self.proposal.proposed_final_date,
            status="CONFIRMED",
            expires_at=None,
            guest_first_name="Otra",
            guest_last_name="Reserva",
            guest_email="other@example.com",
            guest_phone_number="+34600111223",
            guest_country="España",
            guest_city="Madrid",
            guest_address="Otra dirección",
            guest_count=2,
            arrival_time=time(18, 0),
        )

        try:
            with transaction.atomic():
                competing_booking.save()
        except (IntegrityError, ValidationError):
            self.fail(
                "Una propuesta pendiente no debe bloquear las fechas propuestas."
            )

    def test_accepting_proposal_releases_original_dates_for_new_booking(self):
        original_start = self.booking1.initial_date
        original_end = self.booking1.final_date
        property_id = self.booking1.property_id

        # Aceptar la propuesta libera la estancia original.
        accept_response = self.client.post(self.accept_url())
        self.assertEqual(accept_response.status_code, 200)

        self.booking1.refresh_from_db()
        self.assertEqual(
            self.booking1.initial_date,
            self.proposal.proposed_initial_date,
        )
        self.assertEqual(
            self.booking1.final_date,
            self.proposal.proposed_final_date,
        )

        # Verificar la disponibilidad mediante el endpoint real.
        payload = {
            "start": original_start.isoformat(),
            "end": original_end.isoformat(),
            **self.booking_payload,
        }

        response = self.client.post(
            self.reverse(
                "confirm_booking",
                kwargs={"property_id": property_id},
            ),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(
            response.status_code,
            200,
            response.content.decode(),
        )

class BookingChangeProposalTokenTestCase(BookingTestBase):

    def setUp(self):
            super().setUp()
    
            from bookings.services import generate_proposal_access_token
    
            self.booking1.initial_date = date.today() + timedelta(days=30)
            self.booking1.final_date = date.today() + timedelta(days=33)
            self.booking1.save()
    
            raw_token, token_hash = generate_proposal_access_token()
            self.raw_token = raw_token
    
            self.proposal = BookingChangeProposal.objects.create(
                booking=self.booking1,
                proposed_initial_date=self.booking1.initial_date + timedelta(days=1),
                proposed_final_date=self.booking1.final_date + timedelta(days=1),
                proposed_guest_count=2,
                access_token_hash=token_hash,
            )
    
            self.url = reverse(
                "view_booking_change_proposal_by_token",
                kwargs={"token": self.raw_token},
            )

    def test_access_token_hash_is_sha256_of_raw_token(self):
        from bookings.services import (
            generate_proposal_access_token,
            hash_proposal_access_token,
        )

        raw_token, token_hash = generate_proposal_access_token()

        self.assertTrue(raw_token)
        self.assertEqual(len(token_hash), 64)
        self.assertEqual(
            token_hash,
            hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(hash_proposal_access_token(raw_token), token_hash)

    def test_different_tokens_produce_different_hashes(self):
        from bookings.services import generate_proposal_access_token

        _, first_hash = generate_proposal_access_token()
        _, second_hash = generate_proposal_access_token()

        self.assertNotEqual(first_hash, second_hash)

    def test_raw_token_is_not_stored_on_proposal(self):
        from bookings.services import generate_proposal_access_token

        self.booking1.save()

        # Evitar conflictos con la restricción de una propuesta pendiente por reserva.
        BookingChangeProposal.objects.filter(
            booking=self.booking1,
            status=BookingChangeProposal.Status.PENDING,
        ).update(status=BookingChangeProposal.Status.REJECTED)

        raw_token, token_hash = generate_proposal_access_token()
        proposal = BookingChangeProposal.objects.create(
            booking=self.booking1,
            proposed_initial_date=self.booking1.initial_date,
            proposed_final_date=self.booking1.final_date,
            proposed_guest_count=2,
            access_token_hash=token_hash,
        )

        proposal.refresh_from_db()
        self.assertEqual(proposal.access_token_hash, token_hash)
        self.assertNotEqual(proposal.access_token_hash, raw_token)

    def test_valid_token_can_view_pending_proposal_without_login(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["proposed_initial_date"],
            self.proposal.proposed_initial_date.isoformat(),
        )
        self.assertEqual(
            response.json()["proposed_final_date"],
            self.proposal.proposed_final_date.isoformat(),
        )

    def test_invalid_token_cannot_access_proposal(self):
        response = self.client.get(
            reverse(
                "view_booking_change_proposal_by_token",
                kwargs={"token": "invalid-token"},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_expired_proposal_cannot_be_viewed(self):
        BookingChangeProposal.objects.filter(
            pk=self.proposal.pk,
        ).update(
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 410)

        self.proposal.refresh_from_db()
        self.assertEqual(
            self.proposal.status,
            BookingChangeProposal.Status.EXPIRED,
        )

    def test_resolved_proposal_cannot_be_viewed(self):
        self.proposal.status = BookingChangeProposal.Status.REJECTED
        self.proposal.save(update_fields=["status"])

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 410)

    def test_get_does_not_modify_booking(self):
        original_dates = (
            self.booking1.initial_date,
            self.booking1.final_date,
            self.booking1.guest_count,
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

        self.booking1.refresh_from_db()
        self.assertEqual(
            (
                self.booking1.initial_date,
                self.booking1.final_date,
                self.booking1.guest_count,
            ),
            original_dates,
        )

class AdminForcedBookingChangeViewTestCase(BookingTestBase):
    def setUp(self):
        super().setUp()

        from datetime import timedelta
        from django.urls import reverse
        from django.utils import timezone

        self.timedelta = timedelta
        self.reverse = reverse
        self.today = timezone.localdate()

        self.booking1.initial_date = self.today + timedelta(days=30)
        self.booking1.final_date = self.today + timedelta(days=33)
        self.booking1.status = "CONFIRMED"
        self.booking1.expires_at = None
        self.booking1.save()

        self.original_initial_date = self.booking1.initial_date
        self.original_final_date = self.booking1.final_date
        self.original_guest_count = self.booking1.guest_count
        self.original_nights = list(
            self.booking1.nights.order_by("date").values_list(
                "date", "price_per_night"
            )
        )

        self.admin_user = User.objects.create_superuser(
            username="forced-change-admin",
            email="forced-change-admin@example.com",
            password="test-password",
        )

        self.url = self.reverse(
            "admin_force_booking_change",
            args=[self.booking1.pk],
        )

        self.payload = {
            "initial_date": (self.today + timedelta(days=40)).isoformat(),
            "final_date": (self.today + timedelta(days=44)).isoformat(),
            "guest_count": 2,
        }

    def test_anonymous_user_cannot_force_booking_change(self):
        response = self.client.post(self.url, self.payload)

        self.assertIn(response.status_code, (302, 401, 403, 404))

        self.booking1.refresh_from_db()
        self.assertEqual(
            self.booking1.initial_date,
            self.original_initial_date,
        )
        self.assertEqual(
            self.booking1.final_date,
            self.original_final_date,
        )

    def test_owner_cannot_force_booking_change(self):
        self.client.force_login(self.owner)

        response = self.client.post(self.url, self.payload)

        self.assertEqual(response.status_code, 403)
        self.booking1.refresh_from_db()
        self.assertEqual(
            self.booking1.initial_date,
            self.original_initial_date,
        )
        self.assertEqual(
            self.booking1.final_date,
            self.original_final_date,
        )

    def test_guest_cannot_force_booking_change(self):
        self.client.force_login(self.tenant)

        response = self.client.post(self.url, self.payload)

        self.assertEqual(response.status_code, 403)
        self.booking1.refresh_from_db()
        self.assertEqual(
            self.booking1.initial_date,
            self.original_initial_date,
        )
        self.assertEqual(
            self.booking1.final_date,
            self.original_final_date,
        )

    def test_get_request_is_not_allowed(self):
        self.client.force_login(self.admin_user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)

    def test_admin_force_change_updates_booking_and_creates_audit(self):

        self.client.force_login(self.admin_user)

        response = self.client.post(self.url, self.payload)

        self.assertEqual(response.status_code, 200)

        self.booking1.refresh_from_db()

        self.assertEqual(
            self.booking1.initial_date,
            self.today + self.timedelta(days=40),
        )
        self.assertEqual(
            self.booking1.final_date,
            self.today + self.timedelta(days=44),
        )
        self.assertEqual(self.booking1.guest_count, 2)
        self.assertEqual(self.booking1.status, "CONFIRMED")

        audit = BookingChangeAudit.objects.get(
            booking=self.booking1,
        )

        self.assertEqual(audit.actor, self.admin_user)

        self.assertEqual(
            audit.before_values["initial_date"],
            self.original_initial_date.isoformat(),
        )
        self.assertEqual(
            audit.before_values["final_date"],
            self.original_final_date.isoformat(),
        )
        self.assertEqual(
            audit.before_values["guest_count"],
            self.original_guest_count,
        )

        self.assertEqual(
            audit.after_values["initial_date"],
            self.booking1.initial_date.isoformat(),
        )
        self.assertEqual(
            audit.after_values["final_date"],
            self.booking1.final_date.isoformat(),
        )
        self.assertEqual(
            audit.after_values["guest_count"],
            2,
        )

        actual_nights = list(
            self.booking1.nights.order_by("date").values_list(
                "date", "price_per_night"
            )
        )

        expected_nights = [
            (
                self.today + self.timedelta(days=40 + offset),
                __import__("decimal").Decimal(str(night["price_per_night"]))
            )
            for offset, night in enumerate(
                audit.after_values["nights"]
            )
        ]

        self.assertEqual(actual_nights, expected_nights)


    def test_audit_failure_rolls_back_booking_and_nights(self):

        self.client.force_login(self.admin_user)

        proposal = BookingChangeProposal.objects.create(
            booking=self.booking1,
            proposed_initial_date=self.today + self.timedelta(days=50),
            proposed_final_date=self.today + self.timedelta(days=54),
            proposed_guest_count=2,
        )

        with patch(
            "bookings.views.BookingChangeAudit.objects.create",
            side_effect=IntegrityError("Simulated audit failure"),
        ):
            response = self.client.post(self.url, self.payload)

        self.assertEqual(response.status_code, 409)

        self.booking1.refresh_from_db()

        self.assertEqual(
            self.booking1.initial_date,
            self.original_initial_date,
        )
        self.assertEqual(
            self.booking1.final_date,
            self.original_final_date,
        )
        self.assertEqual(
            self.booking1.guest_count,
            self.original_guest_count,
        )

        self.assertEqual(
            list(
                self.booking1.nights.order_by("date").values_list(
                    "date", "price_per_night"
                )
            ),
            self.original_nights,
        )

        self.assertFalse(
            BookingChangeAudit.objects.filter(
                booking=self.booking1,
            ).exists()
        )

        proposal.refresh_from_db()
        self.assertEqual(proposal.status, "PENDING")

    def test_admin_force_change_expires_pending_proposals(self):
        from bookings.models import BookingChangeProposal

        proposal = BookingChangeProposal.objects.create(
            booking=self.booking1,
            proposed_initial_date=self.today + self.timedelta(days=50),
            proposed_final_date=self.today + self.timedelta(days=54),
            proposed_guest_count=2,
        )

        self.client.force_login(self.admin_user)

        response = self.client.post(self.url, self.payload)

        self.assertEqual(response.status_code, 200)

        proposal.refresh_from_db()
        self.assertEqual(proposal.status, "EXPIRED")

class PropertySearchTestCase(TestCase):

    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner",
            email="owner@test.com",
            password="123",
        )

        self.tenant = User.objects.create_user(
            username="tenant",
            email="tenant@test.com",
            password="123",
        )

        self.other_owner = User.objects.create_user(
            username="other-owner",
            email="other-owner@test.com",
            password="123",
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
            owner=self.owner,
        )

        self.other_property = Property.objects.create(
            title="Casa Barcelona",
            description="Desc",
            location="Barcelona",
            default_price_per_night=100,
            image="test.jpg",
            children=2,
            adults=2,
            rooms=2,
            owner=self.other_owner,
        )

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

    def test_public_property_search_is_available_to_anonymous_users(self):
        self.client.logout()

        response = self.client.get(
            reverse("properties"),
            {"page": 1},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.property.title)


    def test_public_property_search_preserves_location_filter(self):
        Property.objects.create(
            title="Casa Barcelona",
            description="Desc",
            location="Barcelona",
            default_price_per_night=100,
            image="test.jpg",
            children=2,
            adults=2,
            rooms=2,
            owner=self.owner,
        )

        response = self.client.get(
            reverse("properties"),
            {
                "location": "Madrid",
                "page": 1,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.property.title)
        self.assertNotContains(response, "Casa Barcelona")


    def test_public_property_search_excludes_unavailable_property(self):
        Property.objects.create(
            title="Casa Ocupada",
            description="Desc",
            location="Madrid",
            default_price_per_night=100,
            image="test.jpg",
            children=2,
            adults=2,
            rooms=2,
            owner=self.owner,
        )

        occupied_property = Property.objects.get(title="Casa Ocupada")

        Booking.objects.create(
            tenant=self.tenant,
            property=occupied_property,
            initial_date=date.today(),
            final_date=date.today() + timedelta(days=3),
            status="CONFIRMED",
            guest_first_name="Test",
            guest_last_name="Guest",
            guest_email="test@example.com",
            guest_phone_number="+34600000000",
            guest_country="España",
            guest_city="Madrid",
            guest_address="Calle Test 1",
            guest_count=1,
            arrival_time=time(15, 0),
        )

        response = self.client.get(
            reverse("properties"),
            {
                "initial_date": date.today().isoformat(),
                "final_date": (date.today() + timedelta(days=3)).isoformat(),
                "page": 1,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Casa Ocupada")

    def test_public_property_search_includes_property_owned_by_other_user(self):
        self.client.logout()

        response = self.client.get(
            reverse("properties"),
            {"page": 1},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.other_property.title)

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
            status="CONFIRMED",
            guest_first_name="Test",
            guest_last_name="Guest",
            guest_email="test@example.com",
            guest_phone_number="+34600000000",
            guest_country="España",
            guest_city="Madrid",
            guest_address="Calle Test 1",
            guest_count=1,
            arrival_time=time(15, 0),
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