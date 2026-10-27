from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.http import HttpResponse, HttpResponseRedirect
from django.contrib.auth import authenticate, login, logout
from django.views.decorators.csrf import csrf_exempt
from django.db import IntegrityError
from django.db.models import Exists, F, Q, IntegerField, OuterRef, Subquery, Sum, Value, DecimalField, Prefetch
from django.db.models.functions import Coalesce, Lower, Trim
from .models import User, OwnerProfile, Property, Booking, BookingChangeProposal, BookingAttachment, BookingChangeAudit, BookingNight, BookingCancellationRequest, PropertyAvailability, BookingHold, can_manage_properties
from django import forms
from django.forms import ModelForm
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.forms import AuthenticationForm
from django.http import JsonResponse, FileResponse, Http404
from datetime import date, time, timedelta
from django.utils import timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.contrib.auth.decorators import login_required
import json
from django.core.exceptions import ValidationError
from django.core.exceptions import PermissionDenied
from django.db import transaction
from .services import generate_proposal_access_token, hash_proposal_access_token, OwnerRequestError, request_owner_status
import logging
from django.contrib import messages
import secrets
import os
from django.core import signing
from django.views.decorators.http import require_POST
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from .emails import (
    send_booking_change_proposal_email,
    send_booking_change_proposal_status_email,
    send_forced_booking_change_email,
    send_booking_cancellation_request_email,
    send_forced_booking_cancellation_email,
    send_booking_cancellation_proposal_status_email,
    send_booking_confirmation_emails,
    send_owner_request_notification_email,
    send_owner_request_result_email,
    send_owner_permissions_update_email
)

# Create your views here.
class SearchForm(forms.Form):
    NUM_CHOICES = [(i, str(i)) for i in range(1, 11)]
    CHOICES_WITH_ZERO = [(i, str(i)) for i in range(0, 11)]

    location = forms.ChoiceField(
        label="Lugar",
        choices=[("", "¿A dónde vas?")],
        required=False,
    )

    initial_date = forms.DateField(
        label="Entrada",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    final_date = forms.DateField(
        label="Salida",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    adults = forms.ChoiceField(
        label="Adultos",
        choices=NUM_CHOICES,
        required=False,
        initial=1,
    )

    children = forms.ChoiceField(
        label="Niños",
        choices=CHOICES_WITH_ZERO,
        required=False,
        initial=0,
    )

    rooms = forms.ChoiceField(
        label="Habitaciones",
        choices=NUM_CHOICES,
        required=False,
        initial=1,
    )

    pets = forms.BooleanField(
        required=False,
        label="Mascotas",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        locations = (
            Property.objects
            .filter(owner__owner_profile__status="APPROVED")
            .exclude(location__isnull=True)
            .exclude(location__exact="")
            .annotate(
                normalized_location=Trim("location"),
                location_key=Lower(Trim("location")),
            )
            .exclude(normalized_location="")
            .values("location_key", "normalized_location")
            .distinct()
            .order_by("location_key")
        )

        unique_locations = {}
        for item in locations:
            key = item["location_key"]
            if key not in unique_locations:
                unique_locations[key] = item["normalized_location"]

        self.fields["location"].choices = [
            ("", "¿A dónde vas?"),
            *((location, location) for location in unique_locations.values()),
        ]

def index(request):
    return render(request, "bookings/index.html", {
        "form": SearchForm()
    })

def get_available_property(property_id):
    return get_object_or_404(
        Property.objects.filter(owner__owner_profile__status="APPROVED"),
        id=property_id,
    )
    
def get_available_properties():
    return Property.objects.filter(
        owner__owner_profile__status="APPROVED"
    )
    
def property(request, property_id):

    property = get_available_property(property_id)

    today = date.today()

    # Caducar las reservas pendientes cuyo plazo haya vencido.
    expired_bookings = property.bookings.filter(
        status="PENDING",
        expires_at__lte=timezone.now(),
    )

    for booking in expired_bookings:
        booking.expire()

    active_bookings = property.bookings.filter(
        final_date__gte=today,
        status__in=Booking.ACTIVE_STATUSES,
    ).order_by("initial_date")

    min_booking_date = today + timedelta(days=property.notice_period_days)
    availability_end_date = min_booking_date + timedelta(days=365)
    availability_start_date = min_booking_date - timedelta(days=1)

    availability = PropertyAvailability.get_for_range(
        property,
        availability_start_date,
        availability_end_date,
    )

    bookings = Booking.objects.filter(
        property=property,
        initial_date__lt=availability_end_date,
        final_date__gt=availability_start_date,
        status__in=Booking.ACTIVE_STATUSES,
    ).order_by("initial_date")

    booked_dates = set()

    # Fechas ocupadas por reservas existentes.
    for booking in bookings:
        current_date = max(
            booking.initial_date,
            availability_start_date,
        )
        booking_end = min(
            booking.final_date,
            availability_end_date,
        )

        while current_date < booking_end:
            booked_dates.add(current_date.isoformat())
            current_date += timedelta(days=1)

    # Fechas ocupadas temporalmente por retenciones vigentes.
    now = timezone.now()

    holds = BookingHold.objects.filter(
        property=property,
        initial_date__lt=availability_end_date,
        final_date__gt=availability_start_date,
        expires_at__gt=now,
    )

    for hold in holds:
        current_date = max(
            hold.initial_date,
            availability_start_date,
        )
        hold_end = min(
            hold.final_date,
            availability_end_date,
        )

        while current_date < hold_end:
            booked_dates.add(current_date.isoformat())
            current_date += timedelta(days=1)

    availability_data = [
        {
            "date": item["date"].isoformat(),
            "price_per_night": str(item["price_per_night"]),
            "status": item["status"],
            "min_nights": item["min_nights"],
        }
        for item in availability
    ]

    return render(request, "bookings/property.html", {
        "property": property,
        "active_bookings": active_bookings,
        "availability_data": availability_data,
        "booked_dates": sorted(booked_dates),
    })

@login_required
def my_properties(request):
    if not can_manage_properties(request.user):
        raise PermissionDenied
    
    properties = Property.objects.filter(owner=request.user).order_by("id")
    
    properties = properties.order_by("id")
    paginator = Paginator(properties, 6)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, "bookings/my_properties.html", {
        "properties": properties,
        "page_obj": page_obj
    })

@login_required
def my_bookings(request):
    # Marcar como expiradas las reservas pendientes cuyo plazo ha vencido.
    pending_bookings = Booking.objects.filter(
        tenant=request.user,
        status="PENDING",
    )

    current_time = timezone.now()

    for booking in pending_bookings:
        if booking.is_expired():
            booking.expire()

    # Estados disponibles para el filtro.
    valid_statuses = {
        "PENDING",
        "CONFIRMED",
        "EXPIRED",
        "CANCELLED",
    }

    selected_status = request.GET.get("status", "ALL").upper()

    if selected_status not in valid_statuses | {"ALL"}:
        selected_status = "ALL"

    # Calcular el precio a partir de las noches guardadas.
    bookings = Booking.objects.filter(
        tenant=request.user,
    ).annotate(
        calculated_total=Coalesce(
            Sum("nights__price_per_night"),
            Value(Decimal("0.00")),
            output_field=DecimalField(
                max_digits=10,
                decimal_places=2,
            ),
        )
    )

    # Aplicar el filtro seleccionado.
    if selected_status != "ALL":
        bookings = bookings.filter(status=selected_status)

    bookings = bookings.order_by("-id")
    
    proposals = BookingChangeProposal.objects.filter(
        booking__tenant=request.user,
    ).order_by("-created_at")

    cancellation_requests = BookingCancellationRequest.objects.filter(
        booking__tenant=request.user,
    ).order_by("-created_at")

    bookings = bookings.prefetch_related(
        Prefetch(
            "change_proposals",
            queryset=proposals,
            to_attr="prefetched_change_proposals",
        ),
        Prefetch(
            "cancellation_requests",
            queryset=cancellation_requests,
            to_attr="prefetched_cancellation_requests",
        ),
    )

    paginator = Paginator(bookings, 6)
    page_obj = paginator.get_page(request.GET.get("page"))

    for booking in page_obj.object_list:
        booking.active_change_proposals = [
            proposal
            for proposal in booking.prefetched_change_proposals
            if (
                proposal.status == BookingChangeProposal.Status.PENDING
                and proposal.expires_at is not None
                and proposal.expires_at > current_time
            )
        ]
        booking.active_cancellation_requests = [
            cancellation
            for cancellation in booking.prefetched_cancellation_requests
            if (
                cancellation.status == BookingCancellationRequest.Status.PENDING
                and cancellation.request_type in {
                    BookingCancellationRequest.RequestType.OWNER_REQUEST,
                    BookingCancellationRequest.RequestType.ADMIN_PROPOSAL,
                }
                and (
                    cancellation.expires_at is None
                    or cancellation.expires_at > current_time
                )
            )
        ]

        booking.active_requests_count = (
            len(booking.active_change_proposals)
            + len(booking.active_cancellation_requests)
        )

    return render(
        request,
        "bookings/my_bookings.html",
        {
            "bookings": page_obj.object_list,
            "page_obj": page_obj,
            "selected_status": selected_status,
            "current_time": current_time,
        },
    )

class PropertyForm(ModelForm):
    class Meta:
        model = Property
        fields = ("title", "description", "location", "image", "notice_period_days", "default_price_per_night", "default_min_nights", "children", "adults", "rooms", "allow_pets")

@login_required
def manage_property(request, property_id=None):
    if not can_manage_properties(request.user):
        raise PermissionDenied

    if property_id is None:
        property = None
        form = PropertyForm()
    else :
        property = get_object_or_404(Property, pk=property_id)
        if property.owner != request.user and not request.user.is_staff:
            raise PermissionDenied
        form = PropertyForm(instance=property)

    if request.method == "POST":
        delete = request.POST.get('delete')
        if property is not None and delete is not None:
            property.delete()
            return HttpResponseRedirect(reverse("index"))
        else:
            form = PropertyForm(request.POST, request.FILES, instance=property)
            if form.is_valid():
                # Create the object instance without saving to the database yet
                property = form.save(commit=False)
                if not property.pk:
                    property.owner = request.user
                # Now we can save it
                property.save()
                
                return HttpResponseRedirect(reverse("index"))
            else:
                return render(request, "bookings/propertyForm.html", {
                    "property": property,
                    "form": form
                })
    else:
        return render(request, "bookings/propertyForm.html", {
            "property": property,
            "form": form
        })

@login_required
def property_availability(request, property_id):
    if not can_manage_properties(request.user):
        raise PermissionDenied

    property = get_object_or_404(Property, pk=property_id)

    if property.owner != request.user and not request.user.is_staff:
        raise PermissionDenied

    return render(request, "bookings/property_availability.html", {
        "property": property,
        "default_price_per_night": property.default_price_per_night,
        "default_min_nights": property.default_min_nights,
    })

@login_required
def property_availability_reset(request, property_id):
    if not can_manage_properties(request.user):
        raise PermissionDenied
    
    property = get_object_or_404(Property, pk=property_id)

    if property.owner != request.user and not request.user.is_staff:
        raise PermissionDenied

    if request.method != "POST":
        return JsonResponse(
            {"error": "Method not allowed"},
            status=405,
        )

    start_date = request.POST.get("start_date")
    end_date = request.POST.get("end_date")

    if not start_date or not end_date:
        return JsonResponse(
            {"error": "Start and end dates are required"},
            status=400,
        )

    try:
        start_date = date.fromisoformat(start_date)
        end_date = date.fromisoformat(end_date)
    except ValueError:
        return JsonResponse(
            {"error": "Invalid date format"},
            status=400,
        )

    if start_date > end_date:
        return JsonResponse(
            {"error": "Start date must be before or equal to end date"},
            status=400,
        )
    
    with transaction.atomic():
        Property.objects.select_for_update().get(pk=property.pk)

        has_bookings = Booking.objects.filter(
            property=property,
            initial_date__lte=end_date,
            final_date__gt=start_date,
            status__in=Booking.ACTIVE_STATUSES,
        ).exists()

        if has_bookings:
            return JsonResponse(
                {"error": "No se pueden restaurar días que tienen reservas."},
                status=400,
            )

        deleted_count, _ = PropertyAvailability.objects.filter(
            property=property,
            date__range=[start_date, end_date],
        ).delete()

    return JsonResponse({
        "deleted_count": deleted_count,
    })

@login_required
def property_availability_data(request, property_id):
    
    if not can_manage_properties(request.user):
        raise PermissionDenied

    property = get_object_or_404(Property, pk=property_id)
    
    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")
    
    if property.owner != request.user and not request.user.is_staff:
        raise PermissionDenied

    if not start_date or not end_date:
        return JsonResponse(
            {"error": "Start and end dates are required"},
            status=400,
        )

    try:
        start_date = date.fromisoformat(start_date)
        end_date = date.fromisoformat(end_date)
    except ValueError:
        return JsonResponse(
            {"error": "Invalid date format"},
            status=400,
        )

    if start_date > end_date:
        return JsonResponse(
            {"error": "Start date must be before or equal to end date"},
            status=400,
        )

    availability = PropertyAvailability.get_for_range(
        property,
        start_date,
        end_date + timedelta(days=1),
    )

    bookings = Booking.objects.filter(
        property=property,
        initial_date__lte=end_date,
        final_date__gt=start_date,
        status__in=Booking.ACTIVE_STATUSES,
    ).order_by("initial_date")

    booked_dates = set()

    for booking in bookings:
        current_date = max(
            booking.initial_date,
            start_date,
        )

        booking_end = min(
            booking.final_date,
            end_date + timedelta(days=1),
        )

        while current_date < booking_end:
            booked_dates.add(current_date.isoformat())
            current_date += timedelta(days=1)

    return JsonResponse({
        "availability": [
            {
                "date": item["date"].isoformat(),
                "price_per_night": str(item["price_per_night"]),
                "status": item["status"],
                "min_nights": item["min_nights"],
                "has_override": PropertyAvailability.objects.filter(
                    property=property,
                    date=item["date"],
                ).exists(),
            }
            for item in availability
        ],
        "booked_dates": sorted(booked_dates),
    })

@login_required
def property_availability_save(request, property_id):
    if not can_manage_properties(request.user):
        raise PermissionDenied

    property = get_object_or_404(Property, pk=property_id)

    if property.owner != request.user and not request.user.is_staff:
        raise PermissionDenied

    if request.method != "POST":
        return JsonResponse(
            {"error": "Method not allowed"},
            status=405,
        )

    start_date = request.POST.get("start_date")
    end_date = request.POST.get("end_date")
    status = request.POST.get("status")
    min_nights = request.POST.get("min_nights")
    price_per_night = request.POST.get("price_per_night")

    if not all([
        start_date,
        end_date,
        status,
        min_nights,
        price_per_night,
    ]):
        return JsonResponse(
            {"error": "All fields are required"},
            status=400,
        )

    if status not in {"OPEN", "CLOSED"}:
        return JsonResponse(
            {"error": "Invalid status"},
            status=400,
        )

    try:
        start_date = date.fromisoformat(start_date)
        end_date = date.fromisoformat(end_date)
    except ValueError:
        return JsonResponse(
            {"error": "Invalid date format"},
            status=400,
        )

    if start_date < date.today():
        return JsonResponse(
            {"error": "Cannot modify availability for past dates"},
            status=400,
        )

    if start_date > end_date:
        return JsonResponse(
            {"error": "Start date must be before or equal to end date"},
            status=400,
        )
    
    with transaction.atomic():
        Property.objects.select_for_update().get(pk=property.pk)

        has_bookings = Booking.objects.filter(
            property=property,
            initial_date__lte=end_date,
            final_date__gt=start_date,
            status__in=Booking.ACTIVE_STATUSES,
        ).exists()

        if has_bookings:
            return JsonResponse(
                {"error": "No se pueden modificar días que tienen reservas."},
                status=400,
            )

        updated_count = 0
        current_date = start_date

        try:
            while current_date <= end_date:
                PropertyAvailability.objects.update_or_create(
                    property=property,
                    date=current_date,
                    defaults={
                        "status": status,
                        "min_nights": min_nights,
                        "price_per_night": price_per_night,
                    },
                )

                updated_count += 1
                current_date += timedelta(days=1)

        except ValidationError as exc:
            error_message = "Invalid availability"

            if "min_nights" in exc.message_dict:
                error_message = "Invalid minimum nights"
            elif "price_per_night" in exc.message_dict:
                error_message = "Invalid price"

            transaction.set_rollback(True)

            return JsonResponse(
                {"error": error_message},
                status=400,
            )

    return JsonResponse({
        "updated_count": updated_count,
    })

@login_required
def property_bookings(request, property_id):
    if not can_manage_properties(request.user):
        raise PermissionDenied

    property = get_object_or_404(Property, pk=property_id)

    if property.owner != request.user and not request.user.is_staff:
        raise PermissionDenied

    # Mantener actualizado el estado de las reservas pendientes vencidas.
    pending_bookings = Booking.objects.filter(
        property=property,
        status="PENDING",
    )

    for booking in pending_bookings:
        if booking.is_expired():
            booking.expire()

    # Calcular el total igual que en my_bookings.
    all_bookings = Booking.objects.filter(
        property=property,
    ).annotate(
        calculated_total=Coalesce(
            Sum("nights__price_per_night"),
            Value(Decimal("0.00")),
            output_field=DecimalField(
                max_digits=10,
                decimal_places=2,
            ),
        )
    ).select_related("tenant").order_by("-id")

    # Filtro predeterminado: reservas activas.
    valid_filters = {"ALL", "ACTIVE", "CANCELLED", "EXPIRED"}
    selected_status = request.GET.get("status", "ACTIVE").upper()

    if selected_status not in valid_filters:
        selected_status = "ACTIVE"

    # Contadores de todos los filtros.
    filter_counts = {
        "ALL": all_bookings.count(),
        "ACTIVE": all_bookings.filter(
            status__in=["PENDING", "CONFIRMED"]
        ).count(),
        "CANCELLED": all_bookings.filter(
            status="CANCELLED"
        ).count(),
        "EXPIRED": all_bookings.filter(
            status="EXPIRED"
        ).count(),
    }

    # Filtrar antes de paginar.
    if selected_status == "ACTIVE":
        bookings = all_bookings.filter(
            status__in=["PENDING", "CONFIRMED"]
        )
    elif selected_status == "CANCELLED":
        bookings = all_bookings.filter(status="CANCELLED")
    elif selected_status == "EXPIRED":
        bookings = all_bookings.filter(status="EXPIRED")
    else:
        bookings = all_bookings

    paginator = Paginator(bookings, 6)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "bookings/property_bookings.html",
        {
            "property": property,
            "bookings": page_obj.object_list,
            "page_obj": page_obj,
            "selected_status": selected_status,
            "filter_counts": filter_counts,
        },
    )

@login_required
def cancel_booking(request, booking_id):
    if request.method != "POST":
        return JsonResponse(
            {"error": "Método no permitido."},
            status=405,
        )

    with transaction.atomic():
        booking = get_object_or_404(
            Booking.objects.select_for_update(),
            pk=booking_id,
        )

        # El cliente solo puede cancelar sus propias reservas.
        if booking.tenant_id != request.user.pk:
            return JsonResponse(
                {
                    "error": (
                        "No tienes permiso para cancelar esta reserva."
                    )
                },
                status=403,
            )

        # Solo se pueden cancelar reservas activas.
        if booking.status not in Booking.ACTIVE_STATUSES:
            return redirect("my_bookings")

        # Si la reserva pendiente ha caducado, no se cancela.
        if booking.status == "PENDING" and booking.is_expired():
            booking.expire()
            return redirect("my_bookings")

        # Si había solicitudes de cancelación pendientes del propietario
        # o del administrador, dejan de tener efecto.
        BookingCancellationRequest.objects.filter(
            booking=booking,
            status=BookingCancellationRequest.Status.PENDING,
        ).update(
            status=BookingCancellationRequest.Status.CANCELLED,
        )

        # Registrar la cancelación voluntaria.
        # Este texto es interno: no se solicita al cliente.
        BookingCancellationRequest.objects.create(
            booking=booking,
            requested_by=request.user,
            request_type=(
                BookingCancellationRequest.RequestType.CUSTOMER_REQUEST
            ),
            status=BookingCancellationRequest.Status.EXECUTED,
            reason="Cancelación voluntaria iniciada por el cliente.",
        )

        # Cancelar la reserva dentro de la misma transacción.
        booking.cancel()

    return redirect("my_bookings")

@require_POST
def delete_booking(request, booking_id):
    if not request.user.is_authenticated or not request.user.is_staff:
        raise PermissionDenied

    with transaction.atomic():
        booking = get_object_or_404(
            Booking.objects.select_for_update(),
            pk=booking_id,
        )

        # 1. Obtener las solicitudes de cancelación.
        cancellation_requests = BookingCancellationRequest.objects.filter(
            booking=booking
        )

        # 2. Eliminar los archivos adjuntos de esas solicitudes.
        BookingAttachment.objects.filter(
            cancellation_request__in=cancellation_requests
        ).delete()

        # 3. Eliminar las solicitudes de cancelación.
        cancellation_requests.delete()

        # 4. Eliminar el historial de cambios de la reserva.
        BookingChangeAudit.objects.filter(
            booking=booking
        ).delete()

        # 5. Eliminar definitivamente la reserva.
        booking.delete()

    return redirect('index')

@staff_member_required(login_url="login")
def manage_owner_requests(request):
    owner_requests = (
        OwnerProfile.objects
        .filter(status="PENDING")
        .select_related("user")
        .order_by("created_at")
    )

    return render(
        request,
        "bookings/manage_owner_requests.html",
        {
            "owner_requests": owner_requests,
        },
    )

@staff_member_required(login_url="login")
@require_POST
@transaction.atomic
def review_owner_request(request, profile_id, action):
    owner_profile = get_object_or_404(
        OwnerProfile.objects.select_for_update(),
        pk=profile_id,
    )

    if action not in {"approve", "reject"}:
        raise Http404

    if owner_profile.status != "PENDING":
        messages.warning(
            request,
            "Esta solicitud ya no está pendiente de revisión.",
        )
        return redirect("manage_owner_requests")

    if action == "approve":
        owner_profile.status = "APPROVED"
        message = (
            f"Se han concedido permisos de propietario a "
            f"{owner_profile.user.username}."
        )
    else:
        owner_profile.status = "REJECTED"
        message = (
            f"Se ha rechazado la solicitud de "
            f"{owner_profile.user.username}."
        )

    owner_profile.reviewed_at = timezone.now()
    owner_profile.save(update_fields=["status", "reviewed_at"])
    
    transaction.on_commit(
        lambda user=owner_profile.user, approved=(action == "approve"):
            send_owner_request_result_email(user, approved)
    )

    messages.success(request, message)
    return redirect("manage_owner_requests")

@staff_member_required(login_url="login")
@require_POST
@transaction.atomic
def manage_owner_permissions(request, user_id, action):
    if action not in {"grant", "revoke"}:
        raise Http404

    User = get_user_model()
    target_user = get_object_or_404(
        User.objects.select_for_update(),
        pk=user_id,
    )

    owner_profile = (
        OwnerProfile.objects.select_for_update()
        .filter(user=target_user)
        .first()
    )

    permissions_changed = False

    if action == "grant":
        if owner_profile is None:
            OwnerProfile.objects.create(
                user=target_user,
                status="APPROVED",
                reviewed_at=timezone.now(),
            )
            permissions_changed = True

        elif owner_profile.status != "APPROVED":
            owner_profile.status = "APPROVED"
            owner_profile.reviewed_at = timezone.now()
            owner_profile.save(
                update_fields=["status", "reviewed_at"],
            )
            permissions_changed = True

        messages.success(
            request,
            f"Se han concedido permisos de propietario a "
            f"{target_user.username}.",
        )

    else:
        if owner_profile is None or owner_profile.status != "APPROVED":
            messages.warning(
                request,
                "El usuario no tiene permisos de propietario activos.",
            )
        else:
            owner_profile.status = "REVOKED"
            owner_profile.reviewed_at = timezone.now()
            owner_profile.save(
                update_fields=["status", "reviewed_at"],
            )
            permissions_changed = True

            messages.success(
                request,
                f"Se han revocado los permisos de propietario de "
                f"{target_user.username}.",
            )

    if permissions_changed:
        transaction.on_commit(
            lambda user=target_user, granted=(action == "grant"):
                send_owner_permissions_update_email(user, granted)
        )

    return redirect("manage_users")

@staff_member_required(login_url="login")
def manage_users(request):
    User = get_user_model()

    valid_filters = {
        "ALL",
        "GUESTS",
        "PENDING",
        "APPROVED",
        "INACTIVE",
    }

    selected_status = request.GET.get("status", "ALL").upper()

    if selected_status not in valid_filters:
        selected_status = "ALL"

    search_query = request.GET.get("q", "").strip()

    all_users = User.objects.select_related(
        "owner_profile"
    ).order_by("-date_joined", "-id")

    # Búsqueda por nombre, apellidos, usuario, correo o teléfono.
    if search_query:
        all_users = all_users.filter(
            Q(username__icontains=search_query)
            | Q(first_name__icontains=search_query)
            | Q(last_name__icontains=search_query)
            | Q(email__icontains=search_query)
            | Q(phone_number__icontains=search_query)
        )

    # Recuento de usuarios por categoría.
    filter_counts = {
        "ALL": User.objects.count(),
        "GUESTS": User.objects.filter(
            owner_profile__isnull=True
        ).count(),
        "PENDING": User.objects.filter(
            owner_profile__status="PENDING"
        ).count(),
        "APPROVED": User.objects.filter(
            owner_profile__status="APPROVED"
        ).count(),
        "INACTIVE": User.objects.filter(
            owner_profile__status__in=["REJECTED", "REVOKED"]
        ).count(),
    }

    # Aplicar el filtro seleccionado.
    if selected_status == "GUESTS":
        users = all_users.filter(owner_profile__isnull=True)

    elif selected_status == "INACTIVE":
        users = all_users.filter(
            owner_profile__status__in=["REJECTED", "REVOKED"]
        )

    elif selected_status in {"PENDING", "APPROVED"}:
        users = all_users.filter(owner_profile__status=selected_status)

    else:
        users = all_users

    paginator = Paginator(users, 6)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "bookings/manage_users.html",
        {
            "users": page_obj.object_list,
            "page_obj": page_obj,
            "selected_status": selected_status,
            "filter_counts": filter_counts,
            "search_query": search_query,
        },
    )

@login_required
def manage_properties(request):
    if not request.user.is_staff:
        raise PermissionDenied

    properties = Property.objects.all().order_by("id")

    paginator = Paginator(properties, 6)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(request, "bookings/manage_properties.html", {
        "properties": properties,
        "page_obj": page_obj,
    })

@login_required
def manage_bookings(request):
    
    if not request.user.is_staff:
        raise PermissionDenied

    # Actualiza las reservas pendientes que hayan caducado.
    pending_bookings = Booking.objects.filter(status="PENDING")

    for booking in pending_bookings:
        if booking.is_expired():
            booking.expire()

    all_bookings = Booking.objects.annotate(
        calculated_total=Coalesce(
            Sum("nights__price_per_night"),
            Value(Decimal("0.00")),
            output_field=DecimalField(
                max_digits=10,
                decimal_places=2,
            ),
        )
    ).select_related(
        "tenant",
        "property",
    ).order_by("-id")

    valid_filters = {
        "ALL",
        "ACTIVE",
        "PENDING",
        "CONFIRMED",
        "CANCELLED",
        "EXPIRED",
    }

    selected_status = request.GET.get("status", "ALL").upper()

    if selected_status not in valid_filters:
        selected_status = "ACTIVE"

    filter_counts = {
        "ALL": all_bookings.count(),
        "ACTIVE": all_bookings.filter(
            status__in=["PENDING", "CONFIRMED"]
        ).count(),
        "PENDING": all_bookings.filter(
            status="PENDING"
        ).count(),
        "CONFIRMED": all_bookings.filter(
            status="CONFIRMED"
        ).count(),
        "CANCELLED": all_bookings.filter(
            status="CANCELLED"
        ).count(),
        "EXPIRED": all_bookings.filter(
            status="EXPIRED"
        ).count(),
    }

    if selected_status == "ACTIVE":
        bookings = all_bookings.filter(
            status__in=["PENDING", "CONFIRMED"]
        )
    elif selected_status == "PENDING":
        bookings = all_bookings.filter(status="PENDING")
    elif selected_status == "CONFIRMED":
        bookings = all_bookings.filter(status="CONFIRMED")
    elif selected_status == "CANCELLED":
        bookings = all_bookings.filter(status="CANCELLED")
    elif selected_status == "EXPIRED":
        bookings = all_bookings.filter(status="EXPIRED")
    else:
        bookings = all_bookings

    paginator = Paginator(bookings, 6)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "bookings/manage_bookings.html",
        {
            "bookings": page_obj.object_list,
            "page_obj": page_obj,
            "selected_status": selected_status,
            "filter_counts": filter_counts,
        },
    )

def properties(request):
    if request.method != "GET":
        return JsonResponse({"error": "Petición GET necesaria."}, status=400)

    location = request.GET.get('location')
    initial_date = request.GET.get('initial_date')
    final_date = request.GET.get('final_date')
    adults = request.GET.get('adults')
    children = request.GET.get('children')
    rooms = request.GET.get('rooms')
    pets = request.GET.get('pets')

    properties = get_available_properties()

    if request.user.is_authenticated:
        properties = properties.exclude(owner=request.user)

    if location:
        properties = properties.filter(location=location)
    
    if adults:
        try:
            adults = int(adults)
            if adults < 1:
                return JsonResponse({"error": "El número de adultos tiene que ser mayor que 0."}, status=400)
            properties = properties.filter(adults__gte=adults)
        except ValueError:
            return JsonResponse({"error": "Introduce un número válido para indicar el número de adultos."}, status=400)

    if children:
        try:
            children = int(children)
            if children < 0:
                return JsonResponse({"error": "El número de niños tiene que ser mayor o igual a 0."}, status=400)
            properties = properties.filter(children__gte=children)
        except ValueError:
            return JsonResponse({"error": "Introduce un número válido para indicar el número de niños."}, status=400)

    if rooms:
        try:
            rooms = int(rooms)
            if rooms < 1:
                return JsonResponse({"error": "El número de habitaciones tiene que ser mayor que 0."}, status=400)
            properties = properties.filter(rooms__gte=rooms)
        except ValueError:
            return JsonResponse({"error": "Introduce un número válido para indicar el número de habitaciones."}, status=400)
    
    if pets:
        properties = properties.filter(allow_pets=True)

    if initial_date or final_date:
        if not initial_date or not final_date:
            return JsonResponse({"error": "Both dates are required"}, status=400)

        try:
            initial_date = date.fromisoformat(initial_date)
            final_date = date.fromisoformat(final_date)
        except ValueError:
            return JsonResponse({"error": "Invalid date format"}, status=400)

        if initial_date >= final_date:
            return JsonResponse({"error": "Invalid date range"}, status=400)

        if initial_date < date.today():
            return JsonResponse(
                {
                    "error": (
                        "La fecha de entrada no puede ser anterior "
                        "al día de hoy."
                    )
                },
                status=400
            )

        closed_availability = PropertyAvailability.objects.filter(
            property=OuterRef("pk"),
            date__gte=initial_date,
            date__lt=final_date,
            status="CLOSED",
        )

        overlapping_bookings = Booking.objects.filter(
            property=OuterRef("pk"),
            initial_date__lt=final_date,
            final_date__gt=initial_date,
            status__in=Booking.ACTIVE_STATUSES,
        )

        arrival_availability = PropertyAvailability.objects.filter(
            property=OuterRef("pk"),
            date=initial_date,
        ).values("min_nights")[:1]

        arrival_price = PropertyAvailability.objects.filter(
            property=OuterRef("pk"),
            date=initial_date,
        ).values("price_per_night")[:1]

        total_nights = (final_date - initial_date).days

        properties = properties.annotate(
            has_closed_availability=Exists(
                closed_availability
            ),
            has_overlapping_booking=Exists(
                overlapping_bookings
            ),
            arrival_min_nights=Subquery(
                arrival_availability,
                output_field=IntegerField(),
            ),
            arrival_price=Subquery(
                arrival_price,
            ),
        ).annotate(
            effective_min_nights=Coalesce(
                F("arrival_min_nights"),
                F("default_min_nights"),
                output_field=IntegerField(),
            )
        ).filter(
            has_closed_availability=False,
            has_overlapping_booking=False,
            effective_min_nights__lte=total_nights,
        )

    properties = properties.order_by("id")
    paginator = Paginator(properties, 6)
    page_number = request.GET.get("page")

    try:
        page_properties = paginator.page(page_number)

        properties = [
            {
                "id": property.id,
                "title": property.title,
                "description": property.description,
                "location": property.location,
                "image": property.image.name if property.image else "",
                "price_per_night": str(
                    property.arrival_price
                    if property.arrival_price is not None
                    else property.default_price_per_night
                )
                if initial_date
                else str(property.default_price_per_night),
                "adults": property.adults,
                "children": property.children,
                "rooms": property.rooms,
                "allow_pets": property.allow_pets,
            }
            for property in page_properties.object_list
        ]

    except (PageNotAnInteger, EmptyPage):
        # If page doesn`t exist, return empty list
        properties = []

    return JsonResponse(properties, safe=False)

def booking(request, property_id):
    property = get_available_property(property_id)

    initial_date = request.GET.get('start')
    final_date = request.GET.get('end')

    if not initial_date or not final_date:
        return JsonResponse({"error": "Ambas fechas deben ser seleccionadas."}, status=400)

    try:
        # Convert dates from String into actual dates
        initial_date = date.fromisoformat(initial_date)
        final_date = date.fromisoformat(final_date)

        if initial_date >= final_date:
            return JsonResponse(
                {
                    "error": "La fecha de salida debe ser posterior a la fecha de entrada."
                },
                status=400,
            )
        elif initial_date < date.today():
            return JsonResponse({"error": "La fecha de entrada no puede ser anterior al día de hoy."}, status=400)
        else:
            availability = PropertyAvailability.get_for_range(
                property,
                initial_date,
                final_date,
            )

            closed_dates = [
                day["date"]
                for day in availability
                if day["status"] == "CLOSED"
            ]

            if closed_dates:
                return JsonResponse(
                    {
                        "error": "El alojamiento no está disponible en todas las fechas seleccionadas."
                    },
                    status=400,
                )

            arrival_availability = PropertyAvailability.get_for_date(
                property,
                initial_date,
            )

            total_nights = (final_date - initial_date).days

            if total_nights < arrival_availability["min_nights"]:
                return JsonResponse(
                    {
                        "error": (
                            f"La estancia debe ser de al menos "
                            f"{arrival_availability['min_nights']} noches."
                        )
                    },
                    status=400,
                )

            # Check for any overlapping bookings in the database
            is_occupied = Booking.objects.filter(
                property_id=property_id,
                initial_date__lt=final_date,
                final_date__gt=initial_date,
                status__in=Booking.ACTIVE_STATUSES,
            ).exists()

            if is_occupied:
                return JsonResponse(
                    {"error": "El alojamiento ya está reservado en esas fechas."},
                    status=400,
                )

            return JsonResponse({"available": True})

    except ValueError:
        return JsonResponse({"error": "Formato de fecha inválido."}, status=400)

def view_booking_change_proposal_by_token(request, token):
    if request.method != "GET":
        return JsonResponse(
            {"error": "Método no permitido."},
            status=405,
        )

    token_hash = hash_proposal_access_token(token)

    proposal_reference = (
        BookingChangeProposal.objects
        .filter(access_token_hash=token_hash)
        .values("pk", "booking_id")
        .first()
    )

    if proposal_reference is None:
        return JsonResponse(
            {"error": "El enlace de la propuesta no es válido."},
            status=404,
        )

    with transaction.atomic():
        # Bloquear primero la reserva y después la propuesta.
        booking = get_object_or_404(
            Booking.objects.select_for_update().select_related(
                "property",
                "property__owner",
            ),
            pk=proposal_reference["booking_id"],
        )

        proposal = get_object_or_404(
            BookingChangeProposal.objects.select_for_update(),
            pk=proposal_reference["pk"],
            booking=booking,
            access_token_hash=token_hash,
        )

        # Caducar únicamente si sigue pendiente y ha vencido.
        if (
            proposal.status == BookingChangeProposal.Status.PENDING
            and proposal.is_expired()
        ):
            proposal.status = BookingChangeProposal.Status.EXPIRED
            proposal.save(update_fields=["status"])

            transaction.on_commit(
                lambda booking=booking, proposal=proposal:
                    send_booking_change_proposal_status_email(
                        booking, proposal, "expired"
                    )
            )

    # Cargar la propuesta y las relaciones necesarias para la plantilla.
    proposal = (
        BookingChangeProposal.objects
        .select_related("booking", "booking__property")
        .prefetch_related("attachments")
        .get(pk=proposal.pk)
    )

    booking = proposal.booking

    can_respond = proposal.status == BookingChangeProposal.Status.PENDING

    # Recuperar la fotografía de la reserva original.
    original_booking = proposal.original_booking_snapshot or {}

    if original_booking.get("initial_date"):
        original_booking["initial_date"] = date.fromisoformat(
            original_booking["initial_date"]
        )

    if original_booking.get("final_date"):
        original_booking["final_date"] = date.fromisoformat(
            original_booking["final_date"]
        )

    context = {
        "invalid_link": False,
        "property": booking.property,
        "booking": booking,
        "proposal": proposal,
        "original_booking": original_booking,
        "expires_at_local": (
            timezone.localtime(proposal.expires_at)
            if proposal.expires_at else None
        ),
        "can_respond": can_respond,
        "access_token": token,
        "status_message": (
            "Esta propuesta ha caducado o ya ha sido resuelta."
            if not can_respond else ""
        ),
    }

    response_status = 200 if can_respond else 410

    return render(
        request,
        "bookings/booking_change_proposal_detail.html",
        context,
        status=response_status,
    )

def booking_change_proposal_detail(request, token):
    token_hash = hash_proposal_access_token(token)

    with transaction.atomic():
        proposal_reference = (
            BookingChangeProposal.objects
            .filter(access_token_hash=token_hash)
            .values("pk", "booking_id")
            .first()
        )

        if proposal_reference is None:
            return render(
                request,
                "bookings/booking_change_proposal_detail.html",
                {"invalid_link": True},
                status=404,
            )

        booking = get_object_or_404(
            Booking.objects.select_for_update().select_related(
                "property",
                "property__owner",
            ),
            pk=proposal_reference["booking_id"],
        )

        proposal = get_object_or_404(
            BookingChangeProposal.objects.select_for_update().prefetch_related(
                "attachments"
            ),
            pk=proposal_reference["pk"],
            booking=booking,
            access_token_hash=token_hash,
        )

        if (
            proposal.status == BookingChangeProposal.Status.PENDING
            and proposal.is_expired()
        ):
            proposal.status = BookingChangeProposal.Status.EXPIRED
            proposal.save(update_fields=["status"])

            transaction.on_commit(
                lambda booking=booking, proposal=proposal:
                    send_booking_change_proposal_status_email(
                        booking, proposal, "expired"
                    )
            )

    can_respond = proposal.status == BookingChangeProposal.Status.PENDING

    original_booking = proposal.original_booking_snapshot or {}

    if original_booking.get("initial_date"):
        original_booking["initial_date"] = date.fromisoformat(
            original_booking["initial_date"]
        )

    if original_booking.get("final_date"):
        original_booking["final_date"] = date.fromisoformat(
            original_booking["final_date"]
        )

    context = {
        "invalid_link": False,
        "property": booking.property,
        "booking": booking,
        "proposal": proposal,
        "original_booking": original_booking,
        "expires_at_local": timezone.localtime(proposal.expires_at)
        if proposal.expires_at else None,
        "can_respond": can_respond,
        "access_token": token,
        "status_message": (
            "Esta propuesta ha caducado o ya ha sido resuelta."
            if not can_respond else ""
        ),
    }

    return render(
        request,
        "bookings/booking_change_proposal_detail.html",
        context,
    )

def booking_cancellation_request_detail(request, token):
    token_hash = hash_proposal_access_token(token)

    with transaction.atomic():
        cancellation_reference = (
            BookingCancellationRequest.objects
            .filter(access_token_hash=token_hash)
            .values("pk", "booking_id")
            .first()
        )

        if cancellation_reference is None:
            return render(
                request,
                "bookings/booking_cancellation_request_detail.html",
                {"invalid_link": True},
                status=404,
            )

        booking = get_object_or_404(
            Booking.objects.select_for_update().select_related(
                "property",
                "property__owner",
            ),
            pk=cancellation_reference["booking_id"],
        )

        cancellation = get_object_or_404(
            BookingCancellationRequest.objects.select_for_update(),
            pk=cancellation_reference["pk"],
            booking=booking,
            access_token_hash=token_hash,
        )

        now = timezone.now()

        if (
            cancellation.status
            == BookingCancellationRequest.Status.PENDING
            and cancellation.expires_at is not None
            and cancellation.expires_at <= now
        ):
            cancellation.status = (
                BookingCancellationRequest.Status.EXPIRED
            )
            cancellation.save(update_fields=["status"])

            transaction.on_commit(
                lambda booking=booking, cancellation=cancellation:
                    send_booking_cancellation_proposal_status_email(
                        booking,
                        cancellation,
                        "expired",
                    )
            )

    can_respond = (
        cancellation.status == BookingCancellationRequest.Status.PENDING
        and (
            cancellation.expires_at is None
            or cancellation.expires_at > timezone.now()
        )
        and booking.status in Booking.ACTIVE_STATUSES
        and booking.final_date >= timezone.localdate()
    )

    status_messages = {
        BookingCancellationRequest.Status.EXPIRED:
            "Esta solicitud de cancelación ha caducado.",
        BookingCancellationRequest.Status.ACCEPTED:
            "Has aceptado esta solicitud de cancelación.",
        BookingCancellationRequest.Status.REJECTED:
            "Esta solicitud de cancelación ha sido rechazada.",
        BookingCancellationRequest.Status.CANCELLED:
            "Esta solicitud de cancelación ya no está activa.",
        BookingCancellationRequest.Status.EXECUTED:
            "La cancelación se ha ejecutado.",
    }

    status_message = status_messages.get(
        cancellation.status,
        "" if can_respond else "Ya no se puede responder a esta solicitud.",
    )
    
    attachments = BookingAttachment.objects.filter(
        cancellation_request=cancellation
    ).order_by("id")

    return render(
        request,
        "bookings/booking_cancellation_request_detail.html",
        {
            "invalid_link": False,
            "cancellation": cancellation,
            "booking": booking,
            "property": booking.property,
            "can_respond": can_respond,
            "status_message": status_message,
            "expires_at_local": (
                timezone.localtime(cancellation.expires_at)
                if cancellation.expires_at
                else None
            ),
            "access_token": token,
            "attachments": attachments,
        },
    )
        
@login_required
def booking_change_form(request, booking_id):
    if not can_manage_properties(request.user):
        raise PermissionDenied

    booking = get_object_or_404(
        Booking.objects.select_related("property", "property__owner"),
        pk=booking_id,
    )

    if (
        booking.property.owner != request.user
        and not request.user.is_staff
    ):
        raise PermissionDenied

    if booking.status not in ("PENDING", "CONFIRMED"):
        raise PermissionDenied(
            "Esta reserva no admite propuestas de cambio."
        )

    property = booking.property
    today = date.today()

    min_booking_date = today + timedelta(
        days=property.notice_period_days
    )
    availability_end_date = min_booking_date + timedelta(days=365)
    availability_start_date = min_booking_date - timedelta(days=1)

    availability = PropertyAvailability.get_for_range(
        property,
        availability_start_date,
        availability_end_date,
    )

    bookings = Booking.objects.filter(
        property=property,
        initial_date__lt=availability_end_date,
        final_date__gt=availability_start_date,
        status__in=Booking.ACTIVE_STATUSES,
    ).exclude(
        pk=booking.pk
    )

    booked_dates = set()

    for existing_booking in bookings:
        current_date = max(
            existing_booking.initial_date,
            availability_start_date,
        )
        booking_end = min(
            existing_booking.final_date,
            availability_end_date,
        )

        while current_date < booking_end:
            booked_dates.add(current_date.isoformat())
            current_date += timedelta(days=1)

    now = timezone.now()

    holds = BookingHold.objects.filter(
        property=property,
        initial_date__lt=availability_end_date,
        final_date__gt=availability_start_date,
        expires_at__gt=now,
    )

    for hold in holds:
        current_date = max(
            hold.initial_date,
            availability_start_date,
        )
        hold_end = min(
            hold.final_date,
            availability_end_date,
        )

        while current_date < hold_end:
            booked_dates.add(current_date.isoformat())
            current_date += timedelta(days=1)

    availability_data = [
        {
            "date": item["date"].isoformat(),
            "price_per_night": str(item["price_per_night"]),
            "status": item["status"],
            "min_nights": item["min_nights"],
        }
        for item in availability
    ]

    return render(
        request,
        "bookings/booking_change_form.html",
        {
            "booking": booking,
            "property": property,
            "availability_data": availability_data,
            "booked_dates": sorted(booked_dates),
        },
    )
    
@login_required
def booking_cancellation_form(request, booking_id):
    if not can_manage_properties(request.user):
        raise PermissionDenied

    booking = get_object_or_404(
        Booking.objects.select_related(
            "property",
            "property__owner",
        ),
        pk=booking_id,
    )

    # Mismos permisos que en el formulario de cambio.
    if (
        booking.property.owner_id != request.user.pk
        and not request.user.is_staff
    ):
        raise PermissionDenied

    if booking.status not in Booking.ACTIVE_STATUSES:
        raise PermissionDenied(
            "Esta reserva no admite solicitudes de cancelación."
        )

    return render(
        request,
        "bookings/booking_cancellation_form.html",
        {
            "booking": booking,
            "property": booking.property,
        },
    )
    
logger = logging.getLogger(__name__)
def cleanup_booking_attachment_files(attachments):
    for attachment in attachments:
        name = attachment.file.name

        if not name or not name.startswith("booking_attachments/"):
            continue

        try:
            storage = attachment.file.storage
            if storage.exists(name):
                storage.delete(name)
        except Exception:
            # La limpieza no debe ocultar el error original.
            logger.exception(
                "No se pudo limpiar el archivo adjunto %s",
                name,
            )
            
@login_required
def download_booking_attachment(request, attachment_id):
    """
    Descarga un adjunto privado si el usuario está autorizado
    para acceder a la reserva asociada.
    """
    attachment = get_object_or_404(
        BookingAttachment.objects.select_related(
            "change_proposal__booking__property__owner",
            "change_audit__booking__property__owner",
            "cancellation_request__booking__property__owner",
        ),
        pk=attachment_id,
    )

    # Resolver la reserva según el tipo de acción al que pertenece.
    if attachment.change_proposal_id is not None:
        proposal = attachment.change_proposal
        booking = proposal.booking

    elif attachment.change_audit_id is not None:
        audit = attachment.change_audit
        booking = audit.booking
        proposal = None

    elif attachment.cancellation_request_id is not None:
        cancellation_request = attachment.cancellation_request
        booking = cancellation_request.booking
        proposal = None

    else:
        # Protección adicional ante datos inconsistentes.
        raise Http404

    user = request.user

    # Solo las partes de la reserva y el personal autorizado pueden
    # descargar archivos de las acciones de la reserva.
    is_staff = user.is_staff
    is_tenant = booking.tenant_id == user.pk
    is_owner = booking.property.owner_id == user.pk

    authorized = is_staff or is_tenant or is_owner

    # El token solo concede acceso a los archivos de su propuesta.
    # No concede acceso a auditorías ni a solicitudes de cancelación.
    if not authorized and proposal is not None:
        raw_token = request.GET.get("token", "")
        stored_hash = proposal.access_token_hash or ""

        if raw_token and stored_hash:
            provided_hash = hash_proposal_access_token(raw_token)

            authorized = secrets.compare_digest(
                stored_hash,
                provided_hash,
            )

    if not authorized:
        raise Http404

    if not attachment.file:
        raise Http404

    try:
        file_handle = attachment.file.open("rb")
    except (FileNotFoundError, OSError, ValueError):
        raise Http404

    response = FileResponse(
        file_handle,
        as_attachment=True,
        filename=attachment.original_filename or "adjunto",
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"

    return response

def download_booking_proposal_attachment(request, attachment_id):
    raw_token = request.GET.get("token", "")

    if not raw_token:
        raise Http404

    token_hash = hash_proposal_access_token(raw_token)

    attachment = get_object_or_404(
        BookingAttachment.objects.select_related(
            "change_proposal__booking"
        ),
        pk=attachment_id,
        change_proposal__isnull=False,
        change_proposal__access_token_hash=token_hash,
    )

    proposal = attachment.change_proposal

    if proposal.status != BookingChangeProposal.Status.PENDING:
        raise Http404

    if proposal.is_expired():
        raise Http404

    if not attachment.file:
        raise Http404

    try:
        file_handle = attachment.file.open("rb")
    except (FileNotFoundError, OSError, ValueError):
        raise Http404

    response = FileResponse(
        file_handle,
        as_attachment=True,
        filename=attachment.original_filename or "adjunto",
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"

    return response

def download_booking_cancellation_attachment(request, attachment_id):
    """
    Permite descargar un adjunto de cancelación mediante el token
    privado de la solicitud, sin exigir inicio de sesión.
    """
    raw_token = request.GET.get("token", "").strip()

    if not raw_token:
        raise Http404("Enlace de descarga no válido.")

    token_hash = hash_proposal_access_token(raw_token)

    attachment = get_object_or_404(
        BookingAttachment.objects.select_related("cancellation_request"),
        pk=attachment_id,
        cancellation_request__access_token_hash=token_hash,
    )

    cancellation = attachment.cancellation_request

    # No permitir descargas una vez vencida la solicitud.
    if (
        cancellation.expires_at is not None
        and cancellation.expires_at <= timezone.now()
    ):
        raise Http404("El enlace de descarga ha caducado.")

    if not attachment.file:
        raise Http404("El archivo no está disponible.")

    return FileResponse(
        attachment.file.open("rb"),
        as_attachment=True,
        filename=(
            attachment.original_filename
            or attachment.file.name.split("/")[-1]
        ),
    )

def download_forced_booking_attachment(request, attachment_id, token):
    try:
        data = signing.loads(
            token,
            salt="forced-booking-attachment",
            max_age=7 * 24 * 60 * 60,
        )
    except signing.BadSignature:
        raise Http404

    if not isinstance(data, dict):
        raise Http404

    token_attachment_id = data.get("attachment_id")
    audit_id = data.get("audit_id")

    if (
        not isinstance(token_attachment_id, int)
        or isinstance(token_attachment_id, bool)
        or token_attachment_id != attachment_id
        or not isinstance(audit_id, int)
        or isinstance(audit_id, bool)
        or audit_id <= 0
    ):
        raise Http404

    try:
        attachment = BookingAttachment.objects.get(
            pk=attachment_id,
            change_audit_id=audit_id,
        )
    except BookingAttachment.DoesNotExist:
        raise Http404

    if not attachment.file:
        raise Http404

    try:
        file_handle = attachment.file.open("rb")
    except (FileNotFoundError, ValueError):
        raise Http404

    filename = (
        attachment.original_filename
        or attachment.file.name.rsplit("/", 1)[-1]
    )

    return FileResponse(
        file_handle,
        as_attachment=True,
        filename=filename,
    )
    
@login_required
def propose_booking_change(request, booking_id):
    if request.method != "POST":
        return JsonResponse(
            {"error": "Método no permitido."},
            status=405,
        )

    if not can_manage_properties(request.user):
        raise PermissionDenied

    booking = get_object_or_404(
        Booking.objects.select_related("property", "property__owner"),
        pk=booking_id,
    )

    # Solo el propietario de la vivienda o un administrador.
    if (
        booking.property.owner != request.user
        and not request.user.is_staff
    ):
        raise PermissionDenied

    if booking.status not in ("PENDING", "CONFIRMED"):
        return JsonResponse(
            {"error": "No se pueden proponer cambios para esta reserva."},
            status=400,
        )
        
    uploaded_files = []

    if request.content_type == "application/json":
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse(
                {"error": "El JSON enviado no es válido."},
                status=400,
            )

        if not isinstance(data, dict):
            return JsonResponse(
                {"error": "El cuerpo JSON debe ser un objeto."},
                status=400,
            )

    else:
        data = request.POST
        uploaded_files = request.FILES.getlist("attachments")
        
    if len(uploaded_files) > 5:
        return JsonResponse(
            {
                "error": "Solo puedes adjuntar un máximo de 5 archivos."
            },
            status=400,
        )

    reason_raw = data.get("reason")

    if not isinstance(reason_raw, str):
        return JsonResponse(
            {"error": "The reason must be a string."},
            status=400,
        )

    reason = reason_raw.strip()

    if not reason:
        return JsonResponse(
            {"error": "The reason is required."},
            status=400,
        )

    if not reason:
        return JsonResponse(
            {"error": "El motivo de la propuesta es obligatorio."},
            status=400,
        )

    if len(reason) > 1000:
        return JsonResponse(
            {"error": "El motivo no puede superar los 1000 caracteres."},
            status=400,
        )

    initial_date_raw = data.get("proposed_initial_date")
    final_date_raw = data.get("proposed_final_date")
    guest_count_raw = data.get("proposed_guest_count")
    
    if (
        not initial_date_raw
        or not final_date_raw
        or guest_count_raw is None
    ):
        return JsonResponse(
            {
                "error": "Debes indicar las fechas propuestas y el número de huéspedes.",
                "fields": [
                    "proposed_initial_date",
                    "proposed_final_date",
                    "proposed_guest_count",
                ],
            },
            status=400,
        )

    try:
        proposed_initial_date = date.fromisoformat(initial_date_raw)
        proposed_final_date = date.fromisoformat(final_date_raw)
    except (TypeError, ValueError):
        return JsonResponse(
            {"error": "Formato de fecha inválido. Usa YYYY-MM-DD."},
            status=400,
        )

    if isinstance(guest_count_raw, bool):
        return JsonResponse(
            {"error": "El número de huéspedes debe ser un entero."},
            status=400,
        )

    try:
        proposed_guest_count = int(guest_count_raw)
    except (TypeError, ValueError):
        return JsonResponse(
            {"error": "El número de huéspedes debe ser un entero."},
            status=400,
        )

    if isinstance(guest_count_raw, float) and not guest_count_raw.is_integer():
        return JsonResponse(
            {"error": "El número de huéspedes debe ser un entero."},
            status=400,
        )

    if isinstance(guest_count_raw, str) and str(proposed_guest_count) != guest_count_raw.strip():
        return JsonResponse(
            {"error": "El número de huéspedes debe ser un entero."},
            status=400,
        )
    
    if (
        proposed_initial_date == booking.initial_date
        and proposed_final_date == booking.final_date
        and proposed_guest_count == booking.guest_count
    ):
        return JsonResponse(
            {
                "success": False,
                "error": (
                    "No has cambiado ninguna condición de la reserva. "
                    "Modifica las fechas o el número de huéspedes."
                ),
            },
            status=400,
        )
        
    attachments_to_save = []

    try:
        with transaction.atomic():
            # Serializar las creaciones y modificaciones de propuestas
            # asociadas a esta reserva.
            booking = Booking.objects.select_for_update().get(
                pk=booking_id
            )

            # Comprobar de nuevo que la reserva sigue admitiendo cambios.
            if booking.status not in Booking.ACTIVE_STATUSES:
                return JsonResponse(
                    {"error": "No se pueden proponer cambios para esta reserva."},
                    status=409,
                )
            
            # Obtener la hora una sola vez para mantener coherentes los estados y la expiración.
            now = timezone.now()
            
            # Caducar propuestas vencidas individualmente para poder
            # notificar solo las que realmente cambian de estado.
            expired_proposals = list(
                BookingChangeProposal.objects
                .select_for_update()
                .filter(
                    booking=booking,
                    status=BookingChangeProposal.Status.PENDING,
                    expires_at__isnull=False,
                    expires_at__lte=now,
                )
            )

            for expired_proposal in expired_proposals:
                expired_proposal.status = BookingChangeProposal.Status.EXPIRED
                expired_proposal.save(update_fields=["status"])

                transaction.on_commit(
                    lambda booking=booking, proposal=expired_proposal:
                        send_booking_change_proposal_status_email(
                            booking, proposal, "expired"
                        )
                )

            # Reutilizar la propuesta pendiente, si existe.    
            proposal = (
                BookingChangeProposal.objects.select_for_update()
                .filter(
                    booking=booking,
                    status=BookingChangeProposal.Status.PENDING,
                )
                .first()
            )

            if proposal is not None:
                return JsonResponse(
                    {
                        "error": "Ya existe una propuesta pendiente para esta reserva."
                    },
                    status=409,
                )

            raw_token, token_hash = generate_proposal_access_token()

            if proposal is None:
                proposal = BookingChangeProposal(
                    booking=booking,
                    original_booking_snapshot={
                        "initial_date": booking.initial_date.isoformat(),
                        "final_date": booking.final_date.isoformat(),
                        "guest_count": booking.guest_count,
                        "total_price": str(booking.total_price),
                    },
                )

            proposal.proposed_initial_date = proposed_initial_date
            proposal.proposed_final_date = proposed_final_date
            proposal.proposed_guest_count = proposed_guest_count
            
            proposal.reason = reason

            # Renovar la propuesta y su plazo de expiración de 48 horas.
            proposal.created_at = now
            proposal.expires_at = now + timedelta(hours=48)

            # Sustituir el token anterior por uno nuevo.
            proposal.access_token_hash = token_hash

            nightly_prices, total_price = proposal.calculate_price_snapshot()
            proposal.proposed_nightly_prices = nightly_prices
            proposal.proposed_total_price = total_price

            proposal.save()
            
            for uploaded_file in uploaded_files:
                attachment = BookingAttachment(
                    change_proposal=proposal,
                    uploaded_by=request.user,
                    file=uploaded_file,
                    original_filename=os.path.basename(uploaded_file.name)[:255],
                    size=uploaded_file.size,
                )

                # Guardarlo antes de save() permite limpiar el archivo si
                # falla la validación o la escritura en la base de datos.
                attachments_to_save.append(attachment)
                attachment.save()

    except ValidationError as exc:
        cleanup_booking_attachment_files(attachments_to_save)
        return JsonResponse(
            {"error": exc.messages},
            status=400,
        )
    except IntegrityError:
        cleanup_booking_attachment_files(attachments_to_save)
        return JsonResponse(
            {"error": "Ya existe una propuesta pendiente para esta reserva."},
            status=409,
        )
    except Exception:
        cleanup_booking_attachment_files(attachments_to_save)
        raise
    
    try:
        # El bloque transaction.atomic() ya ha terminado.
        # La propuesta está guardada antes de intentar enviar el correo.
        notification_sent = send_booking_change_proposal_email(
            request=request,
            booking=booking,
            proposal=proposal,
            raw_token=raw_token,
        )
    except Exception:
        notification_sent = False

    response_data = {
        "id": proposal.pk,
        "booking_id": booking.pk,
        "status": proposal.status,
        "proposed_initial_date": proposal.proposed_initial_date.isoformat(),
        "proposed_final_date": proposal.proposed_final_date.isoformat(),
        "proposed_guest_count": proposal.proposed_guest_count,
        "proposed_total_price": str(proposal.proposed_total_price),
        "proposed_nightly_prices": proposal.proposed_nightly_prices,
        "expires_at": proposal.expires_at.isoformat(),
        "notification_sent": notification_sent,
    }

    if not notification_sent:
        response_data["notification_warning"] = (
            "La propuesta se creó correctamente, pero no se pudo "
            "enviar el correo de notificación."
        )

    response_data["success"] = True
    response_data["message"] = (
        "La propuesta de cambio se ha enviado correctamente."
    )

    return JsonResponse(response_data, status=201)

@login_required
def propose_booking_cancellation(request, booking_id):
    if request.method != "POST":
        return JsonResponse(
            {"error": "Método no permitido."},
            status=405,
        )

    if not can_manage_properties(request.user):
        raise PermissionDenied

    uploaded_files = request.FILES.getlist("attachments")
    reason = (request.POST.get("reason") or "").strip()

    if not reason:
        return JsonResponse(
            {"error": "El motivo de la cancelación es obligatorio."},
            status=400,
        )

    if len(reason) > 1000:
        return JsonResponse(
            {"error": "El motivo no puede superar los 1000 caracteres."},
            status=400,
        )

    if len(uploaded_files) > 5:
        return JsonResponse(
            {
                "error": (
                    "Solo puedes adjuntar un máximo de 5 archivos."
                )
            },
            status=400,
        )

    attachments_to_save = []
    cancellation = None
    raw_token = None

    try:
        with transaction.atomic():
            booking = get_object_or_404(
                Booking.objects.select_for_update().select_related(
                    "property",
                    "property__owner",
                ),
                pk=booking_id,
            )

            if booking.property.owner_id != request.user.pk:
                raise PermissionDenied

            if booking.status not in Booking.ACTIVE_STATUSES:
                return JsonResponse(
                    {
                        "error": (
                            "No se pueden solicitar cancelaciones "
                            "para esta reserva."
                        )
                    },
                    status=409,
                )

            now = timezone.now()

            expired_requests = list(
                BookingCancellationRequest.objects
                .select_for_update()
                .filter(
                    booking=booking,
                    status=BookingCancellationRequest.Status.PENDING,
                    expires_at__isnull=False,
                    expires_at__lte=now,
                )
            )

            for expired_request in expired_requests:
                expired_request.status = (
                    BookingCancellationRequest.Status.EXPIRED
                )
                expired_request.save(update_fields=["status"])

                transaction.on_commit(
                    lambda booking=booking, cancellation=expired_request:
                        send_booking_cancellation_proposal_status_email(
                            booking,
                            cancellation,
                            "expired",
                        )
                )

            pending_request = (
                BookingCancellationRequest.objects
                .select_for_update()
                .filter(
                    booking=booking,
                    status=BookingCancellationRequest.Status.PENDING,
                )
                .first()
            )

            if pending_request is not None:
                return JsonResponse(
                    {
                        "error": (
                            "Ya existe una solicitud de cancelación "
                            "pendiente para esta reserva."
                        )
                    },
                    status=409,
                )

            # Generar el token privado y guardar solamente su hash.
            raw_token, token_hash = generate_proposal_access_token()

            cancellation = BookingCancellationRequest.objects.create(
                booking=booking,
                requested_by=request.user,
                request_type=(
                    BookingCancellationRequest.RequestType.OWNER_REQUEST
                ),
                status=BookingCancellationRequest.Status.PENDING,
                reason=reason,
                created_at=now,
                expires_at=now + timedelta(hours=48),
                access_token_hash=token_hash,
            )

            # Guardar los archivos asociados a la solicitud.
            for uploaded_file in uploaded_files:
                attachment = BookingAttachment(
                    cancellation_request=cancellation,
                    uploaded_by=request.user,
                    file=uploaded_file,
                    original_filename=os.path.basename(
                        uploaded_file.name
                    )[:255],
                    size=uploaded_file.size,
                )

                attachments_to_save.append(attachment)
                attachment.save()

    except ValidationError as exc:
        cleanup_booking_attachment_files(attachments_to_save)
        return JsonResponse(
            {"error": exc.messages},
            status=400,
        )

    except IntegrityError:
        cleanup_booking_attachment_files(attachments_to_save)
        return JsonResponse(
            {
                "error": (
                    "Ya existe una solicitud de cancelación "
                    "pendiente para esta reserva."
                )
            },
            status=409,
        )

    except Exception:
        cleanup_booking_attachment_files(attachments_to_save)
        raise

    # Enviar el correo después de confirmar la transacción.
    notification_sent = send_booking_cancellation_request_email(
        request,
        booking,
        cancellation,
        raw_token,
    )

    if not notification_sent:
        logger.error(
            "No se pudo enviar el correo de cancelación. "
            "Solicitud=%s, reserva=%s, destinatario=%s",
            cancellation.pk,
            booking.pk,
            booking.guest_email,
        )
    else:
        logger.info(
            "Correo de cancelación enviado correctamente. "
            "Solicitud=%s, reserva=%s, destinatario=%s",
            cancellation.pk,
            booking.pk,
            booking.guest_email,
        )
        
    return JsonResponse(
        {
            "success": True,
            "message": (
                "La solicitud de cancelación se ha creado correctamente."
            ),
            "cancellation_request": {
                "id": cancellation.pk,
                "booking_id": booking.pk,
                "request_type": cancellation.request_type,
                "status": cancellation.status,
                "reason": cancellation.reason,
                "created_at": cancellation.created_at.isoformat(),
                "expires_at": (
                    cancellation.expires_at.isoformat()
                    if cancellation.expires_at
                    else None
                ),
                "attachments_count": len(attachments_to_save),
            },
            "booking_status": booking.status,
            "notification_sent": notification_sent,
        },
        status=201,
    )

@login_required
def force_booking_change(request, booking_id):
    if request.method != "POST":
        return JsonResponse(
            {"success": False, "error": "Método no permitido."},
            status=405,
        )
        
    if not request.user.is_staff:
        raise PermissionDenied
    
    uploaded_files = request.FILES.getlist("attachments")

    if len(uploaded_files) > 5:
        return JsonResponse(
            {
                "success": False,
                "error": "Puedes adjuntar un máximo de 5 archivos por acción.",
            },
            status=400,
        )

    attachments_to_save = []

    reason = (request.POST.get("force_reason") or "").strip()
    confirmation = request.POST.get("force_confirmation") == "on"
    
    if len(reason) > 1000:
        return JsonResponse(
            {
                "success": False,
                "error": "El motivo no puede superar los 1000 caracteres.",
            },
            status=400,
        )

    if not reason:
        return JsonResponse(
            {"success": False, "error": "El motivo del cambio forzado es obligatorio."},
            status=400,
        )

    if not confirmation:
        return JsonResponse(
            {"success": False, "error": "Debes confirmar expresamente el cambio."},
            status=400,
        )

    try:
        initial_date = date.fromisoformat(
            request.POST.get("proposed_initial_date", "")
        )
        final_date = date.fromisoformat(
            request.POST.get("proposed_final_date", "")
        )
        guest_count_raw = request.POST.get("proposed_guest_count", "")
        guest_count = int(guest_count_raw)

        if str(guest_count) != guest_count_raw.strip():
            raise ValueError
    except (TypeError, ValueError):
        return JsonResponse(
            {"success": False, "error": "Las fechas o el número de huéspedes no son válidos."},
            status=400,
        )

    if initial_date >= final_date or guest_count < 1:
        return JsonResponse(
            {"success": False, "error": "El intervalo de fechas o los huéspedes no son válidos."},
            status=400,
        )

    try:
        with transaction.atomic():
            booking = get_object_or_404(
                Booking.objects.select_for_update().select_related(
                    "property",
                    "property__owner",
                ),
                pk=booking_id,
            )

            if booking.status not in Booking.ACTIVE_STATUSES:
                return JsonResponse(
                    {"success": False, "error": "La reserva ya no admite cambios."},
                    status=409,
                )

            if (
                booking.status == "PENDING"
                and booking.expires_at is not None
                and booking.expires_at <= timezone.now()
            ):
                return JsonResponse(
                    {"success": False, "error": "La reserva pendiente ha caducado."},
                    status=409,
                )

            property = Property.objects.select_for_update().get(
                pk=booking.property_id
            )

            if guest_count > property.adults + property.children:
                return JsonResponse(
                    {"success": False, "error": "La capacidad de la vivienda es insuficiente."},
                    status=400,
                )

            availability = PropertyAvailability.get_for_range(
                property,
                initial_date,
                final_date,
            )
            
            expected_dates = [
                initial_date + timedelta(days=offset)
                for offset in range((final_date - initial_date).days)
            ]
            actual_dates = [item["date"] for item in availability]

            if actual_dates != expected_dates:
                return JsonResponse(
                    {
                        "success": False,
                        "error": (
                            "No se ha podido verificar la disponibilidad "
                            "de todas las noches."
                        ),
                    },
                    status=409,
                )

            if not availability or any(
                item["status"] != "OPEN"
                for item in availability
            ):
                return JsonResponse(
                    {
                        "success": False,
                        "error": "Las fechas seleccionadas no están disponibles.",
                    },
                    status=409,
                )

            number_of_nights = (final_date - initial_date).days
            minimum_nights = availability[0]["min_nights"]

            if number_of_nights < minimum_nights:
                return JsonResponse(
                    {
                        "success": False,
                        "error": "La estancia es inferior al mínimo requerido.",
                    },
                    status=400,
                )

            if (
                initial_date == booking.initial_date
                and final_date == booking.final_date
                and guest_count == booking.guest_count
            ):
                return JsonResponse(
                    {"success": False, "error": "No has cambiado ninguna condición de la reserva."},
                    status=400,
                )

            new_nightly_prices = [
                {
                    "date": item["date"].isoformat(),
                    "price_per_night": (
                        f'{Decimal(str(item["price_per_night"])):.2f}'
                    ),
                }
                for item in availability
            ]

            new_total = sum(
                (
                    Decimal(item["price_per_night"])
                    for item in new_nightly_prices
                ),
                Decimal("0.00"),
            )

            old_total = sum(
                (
                    night.price_per_night
                    for night in booking.nights.all()
                ),
                Decimal("0.00"),
            )

            before_values = {
                "initial_date": booking.initial_date.isoformat(),
                "final_date": booking.final_date.isoformat(),
                "guest_count": booking.guest_count,
                "total_price": str(old_total),
            }

            booking.initial_date = initial_date
            booking.final_date = final_date
            booking.guest_count = guest_count

            booking.save(
                update_fields=[
                    "initial_date",
                    "final_date",
                    "guest_count",
                ]
            )

            booking.nights.all().delete()

            BookingNight.objects.bulk_create([
                BookingNight(
                    booking=booking,
                    date=date.fromisoformat(item["date"]),
                    price_per_night=Decimal(item["price_per_night"]),
                )
                for item in new_nightly_prices
            ])

            after_values = {
                "initial_date": initial_date.isoformat(),
                "final_date": final_date.isoformat(),
                "guest_count": guest_count,
                "total_price": str(new_total),
                "reason": reason,
                "change_mode": "forced",
                "nights": new_nightly_prices,
            }

            audit = BookingChangeAudit.objects.create(
                booking=booking,
                actor=request.user,
                reason=reason,
                before_values=before_values,
                after_values=after_values,
            )

            for uploaded_file in uploaded_files:
                attachment = BookingAttachment(
                    change_audit=audit,
                    uploaded_by=request.user,
                    file=uploaded_file,
                    original_filename=os.path.basename(uploaded_file.name)[:255],
                    size=uploaded_file.size,
                )

                attachments_to_save.append(attachment)
                attachment.save()

            pending_proposals = list(
                BookingChangeProposal.objects.select_for_update().filter(
                    booking=booking,
                    status=BookingChangeProposal.Status.PENDING,
                )
            )

            for proposal in pending_proposals:
                proposal.status = BookingChangeProposal.Status.REJECTED
                proposal.save(update_fields=["status"])

                transaction.on_commit(
                    lambda b=booking, p=proposal:
                        send_booking_change_proposal_status_email(
                            b, p, "rejected"
                        )
                )
                
            transaction.on_commit(
                lambda b=booking,
                    before=before_values.copy(),
                    after=after_values.copy(),
                    a=audit,
                    req=request:
                    send_forced_booking_change_email(
                        b,
                        before,
                        after,
                        audit=a,
                        request=req,
                    )
            )

    except ValidationError as exc:
        cleanup_booking_attachment_files(attachments_to_save)
        return JsonResponse(
            {
                "success": False,
                "error": "La reserva no supera las validaciones.",
                "details": (
                    exc.message_dict
                    if hasattr(exc, "message_dict")
                    else exc.messages
                ),
            },
            status=400,
        )
    except IntegrityError:
        cleanup_booking_attachment_files(attachments_to_save)
        return JsonResponse(
            {
                "success": False,
                "error": "El cambio entra en conflicto con la disponibilidad.",
            },
            status=409,
        )
    except Exception:
        cleanup_booking_attachment_files(attachments_to_save)
        raise

    return JsonResponse(
        {
            "success": True,
            "message": "La reserva se ha modificado correctamente.",
            "booking_id": booking.pk,
            "old_total_price": str(old_total),
            "new_total_price": str(new_total),
            "price_difference": str(new_total - old_total),
        },
        status=200,
    )

def notify_forced_cancellation(booking, before, after, cancellation, request):
    try:
        sent = send_forced_booking_cancellation_email(
            booking,
            before,
            after,
            cancellation=cancellation,
            request=request,
        )
        if not sent:
            logger.error(
                "No se pudo enviar el correo de cancelación forzada. "
                "Solicitud=%s, reserva=%s",
                cancellation.pk,
                booking.pk,
            )
    except Exception:
        logger.exception(
            "Error al enviar el correo de cancelación forzada. "
            "Solicitud=%s, reserva=%s",
            cancellation.pk,
            booking.pk,
        )
            
@login_required
def force_booking_cancellation(request, booking_id):
    if request.method != "POST":
        return JsonResponse(
            {
                "success": False,
                "error": "Método no permitido.",
            },
            status=405,
        )

    if not request.user.is_staff:
        raise PermissionDenied

    # Validar la confirmación explícita del administrador.
    if request.POST.get("force_confirmation") != "on":
        return JsonResponse(
            {
                "success": False,
                "error": (
                    "Debes confirmar expresamente que deseas "
                    "forzar la cancelación de la reserva."
                ),
            },
            status=400,
        )

    reason, uploaded_files, error_response = (
        _validate_cancellation_request_input(request)
    )

    if error_response:
        return JsonResponse(
            {
                "success": False,
                "error": error_response.content.decode("utf-8"),
            },
            status=error_response.status_code,
        )

    attachments_to_save = []
    cancellation = None
    before_values = None
    after_values = None
    old_total = Decimal("0.00")

    try:
        with transaction.atomic():
            booking = get_object_or_404(
                Booking.objects.select_for_update().select_related(
                    "property",
                    "property__owner",
                ),
                pk=booking_id,
            )

            # Solo se pueden cancelar reservas activas.
            if booking.status not in Booking.ACTIVE_STATUSES:
                return JsonResponse(
                    {
                        "success": False,
                        "error": (
                            "Solo se pueden cancelar reservas "
                            "pendientes o confirmadas."
                        ),
                    },
                    status=409,
                )

            # Comprobar si una reserva pendiente ya ha caducado.
            if (
                booking.status == "PENDING"
                and booking.expires_at is not None
                and booking.expires_at <= timezone.now()
            ):
                booking.expire()

                return JsonResponse(
                    {
                        "success": False,
                        "error": (
                            "La reserva pendiente ha caducado "
                            "y se ha marcado como caducada."
                        ),
                    },
                    status=409,
                )

            now = timezone.now()

            # Capturar los datos originales antes de cancelar.
            old_total = sum(
                (
                    night.price_per_night
                    for night in booking.nights.all()
                ),
                Decimal("0.00"),
            )

            before_values = {
                "initial_date": booking.initial_date.isoformat(),
                "final_date": booking.final_date.isoformat(),
                "guest_count": booking.guest_count,
                "total_price": str(old_total),
            }

            # Cerrar las solicitudes de cancelación pendientes anteriores.
            pending_cancellations = list(
                BookingCancellationRequest.objects.select_for_update().filter(
                    booking=booking,
                    status=BookingCancellationRequest.Status.PENDING,
                )
            )

            for pending_cancellation in pending_cancellations:
                pending_cancellation.status = (
                    BookingCancellationRequest.Status.CANCELLED
                )
                pending_cancellation.save(update_fields=["status"])

                transaction.on_commit(
                    lambda b=booking, c=pending_cancellation:
                        send_booking_cancellation_proposal_status_email(
                            b,
                            c,
                            "cancelled",
                        )
                )

            # Cerrar las propuestas de cambio pendientes.
            pending_proposals = list(
                BookingChangeProposal.objects.select_for_update().filter(
                    booking=booking,
                    status=BookingChangeProposal.Status.PENDING,
                )
            )

            for proposal in pending_proposals:
                proposal.status = BookingChangeProposal.Status.CANCELLED
                proposal.save(update_fields=["status"])

                transaction.on_commit(
                    lambda b=booking, p=proposal:
                        send_booking_change_proposal_status_email(
                            b, p, "cancelled"
                        )
                )

            # Registrar la cancelación como ejecutada.
            cancellation = BookingCancellationRequest.objects.create(
                booking=booking,
                requested_by=request.user,
                request_type=(
                    BookingCancellationRequest.RequestType.ADMIN_FORCED
                ),
                status=BookingCancellationRequest.Status.EXECUTED,
                reason=reason,
                created_at=now,
                responded_at=now,
            )

            # Guardar los archivos adjuntos.
            for uploaded_file in uploaded_files:
                attachment = BookingAttachment(
                    cancellation_request=cancellation,
                    uploaded_by=request.user,
                    file=uploaded_file,
                    original_filename=os.path.basename(
                        uploaded_file.name
                    )[:255],
                    size=uploaded_file.size,
                )
                attachments_to_save.append(attachment)
                attachment.save()

            # Ejecutar la cancelación real de la reserva.
            if not booking.cancel():
                raise IntegrityError(
                    "No se ha podido ejecutar la cancelación."
                )

            # Preparar los datos de la notificación.
            after_values = {
                **before_values,
                "reason": reason,
                "change_mode": "forced_cancellation",
            }

            # Enviar el correo solo después de confirmar la transacción.
            transaction.on_commit(
                lambda b=booking,
                    before=before_values.copy(),
                    after=after_values.copy(),
                    c=cancellation,
                    req=request:
                    notify_forced_cancellation(
                        b, before, after, c, req
                    )
            )

    except ValidationError as exc:
        cleanup_booking_attachment_files(attachments_to_save)

        return JsonResponse(
            {
                "success": False,
                "error": "La cancelación no supera las validaciones.",
                "details": (
                    exc.message_dict
                    if hasattr(exc, "message_dict")
                    else exc.messages
                ),
            },
            status=400,
        )

    except IntegrityError:
        cleanup_booking_attachment_files(attachments_to_save)

        return JsonResponse(
            {
                "success": False,
                "error": (
                    "No se ha podido registrar la cancelación "
                    "por un conflicto con otra operación."
                ),
            },
            status=409,
        )

    except Exception:
        cleanup_booking_attachment_files(attachments_to_save)
        raise

    return JsonResponse(
        {
            "success": True,
            "message": (
                "La reserva se ha cancelado por decisión administrativa."
            ),
            "booking_id": booking.pk,
            "cancellation_request": {
                "id": cancellation.pk,
                "booking_id": booking.pk,
                "request_type": cancellation.request_type,
                "status": cancellation.status,
                "reason": cancellation.reason,
                "created_at": cancellation.created_at.isoformat(),
                "responded_at": cancellation.responded_at.isoformat(),
                "attachments_count": len(attachments_to_save),
            },
            "booking_status": booking.status,
            "notification_sent": "scheduled",
        },
        status=200,
    )
            
def authorize_booking_change_proposal(request, booking, proposal, raw_token=""):
    """
    Autoriza al huésped mediante su sesión o mediante el token
    secreto enviado en el correo electrónico.
    """
    # El huésped autenticado con la cuenta correcta puede responder.
    if (
        request.user.is_authenticated
        and booking.tenant_id == request.user.pk
    ):
        return

    # Para cualquier otro caso, se exige un token válido.
    if not raw_token:
        raise PermissionDenied

    stored_hash = proposal.access_token_hash or ""

    # No aceptar propuestas sin un hash de token almacenado.
    if not stored_hash:
        raise PermissionDenied

    provided_hash = hash_proposal_access_token(raw_token)

    if not secrets.compare_digest(stored_hash, provided_hash):
        raise PermissionDenied

def authorize_booking_cancellation(request, booking, cancellation, raw_token=""):
    # Si ha iniciado sesión, solo el huésped propietario de la reserva
    # puede responder desde su cuenta.
    if request.user.is_authenticated:
        if booking.tenant_id == request.user.pk:
            return

        # No revelar que existe una solicitud perteneciente a otro huésped.
        raise Http404

    # Para usuarios no autenticados, permitir el acceso mediante token.
    if not raw_token:
        raise PermissionDenied

    stored_hash = cancellation.access_token_hash or ""

    if not stored_hash:
        raise PermissionDenied

    provided_hash = hash_proposal_access_token(raw_token)

    if not secrets.compare_digest(stored_hash, provided_hash):
        raise PermissionDenied
    
def _validate_cancellation_request_input(request):
    uploaded_files = request.FILES.getlist("attachments")
    reason = (request.POST.get("reason") or "").strip()

    if not reason:
        return None, None, JsonResponse(
            {"error": "El motivo de la cancelación es obligatorio."},
            status=400,
        )

    if len(reason) > 1000:
        return None, None, JsonResponse(
            {"error": "El motivo no puede superar los 1000 caracteres."},
            status=400,
        )

    if len(uploaded_files) > 5:
        return None, None, JsonResponse(
            {
                "error": "Solo puedes adjuntar un máximo de 5 archivos."
            },
            status=400,
        )

    return reason, uploaded_files, None

def redirect_after_booking_change(request, raw_token):
    if raw_token:
        return redirect(
            "view_booking_change_proposal_by_token",
            token=raw_token,
        )

    return redirect("my_bookings")

def redirect_after_booking_cancellation(request, raw_token):
    if raw_token:
        return redirect(
            "booking_cancellation_request_detail",
            token=raw_token,
        )

    return redirect("my_bookings")

def _respond_to_booking_cancellation(request, cancellation_request_id, accept):
    accept_header = request.headers.get("Accept", "")
    is_html_form = (
        "text/html" in accept_header
        and "application/json" not in accept_header
        and request.content_type != "application/json"
    )

    # El token se envía en el formulario HTML.
    raw_token = request.POST.get("token", "")

    # Primera comprobación de autorización.
    cancellation = get_object_or_404(
        BookingCancellationRequest.objects.select_related("booking"),
        pk=cancellation_request_id,
    )

    authorize_booking_cancellation(
        request,
        cancellation.booking,
        cancellation,
        raw_token,
    )

    try:
        with transaction.atomic():
            # Mantener un orden de bloqueo consistente:
            # primero la reserva y después la solicitud.
            booking = get_object_or_404(
                Booking.objects.select_for_update(),
                pk=cancellation.booking_id,
            )

            cancellation = get_object_or_404(
                BookingCancellationRequest.objects.select_for_update(),
                pk=cancellation_request_id,
                booking=booking,
            )

            # Revalidar la autorización con las filas bloqueadas.
            authorize_booking_cancellation(
                request,
                booking,
                cancellation,
                raw_token,
            )

            allowed_types = {
                BookingCancellationRequest.RequestType.OWNER_REQUEST,
                BookingCancellationRequest.RequestType.ADMIN_PROPOSAL,
            }

            if cancellation.request_type not in allowed_types:
                error = "Esta solicitud no admite respuesta."

                if is_html_form:
                    messages.error(request, error)
                    return redirect_after_booking_cancellation(
                        request, raw_token
                    )

                return JsonResponse({"error": error}, status=409)

            if (
                cancellation.status
                != BookingCancellationRequest.Status.PENDING
            ):
                error = "La solicitud ya no está pendiente."

                if is_html_form:
                    messages.error(request, error)
                    return redirect_after_booking_cancellation(
                        request, raw_token
                    )

                return JsonResponse({"error": error}, status=409)

            now = timezone.now()

            if (
                cancellation.expires_at is not None
                and cancellation.expires_at <= now
            ):
                cancellation.status = (
                    BookingCancellationRequest.Status.EXPIRED
                )
                cancellation.save(update_fields=["status"])

                transaction.on_commit(
                    lambda booking=booking, cancellation=cancellation:
                        send_booking_cancellation_proposal_status_email(
                            booking,
                            cancellation,
                            "expired",
                        )
                )

                error = "La solicitud de cancelación ha caducado."

                if is_html_form:
                    messages.error(request, error)
                    return redirect_after_booking_cancellation(
                        request, raw_token
                    )

                return JsonResponse({"error": error}, status=409)

            if booking.status not in Booking.ACTIVE_STATUSES:
                error = "La reserva ya no admite cancelaciones."

                if is_html_form:
                    messages.error(request, error)
                    return redirect_after_booking_cancellation(
                        request, raw_token
                    )

                return JsonResponse({"error": error}, status=409)

            if (
                booking.status == "PENDING"
                and booking.expires_at is not None
                and booking.expires_at <= now
            ):
                booking.expire()

                error = "La reserva pendiente ha caducado."

                if is_html_form:
                    messages.error(request, error)
                    return redirect_after_booking_cancellation(
                        request, raw_token
                    )

                return JsonResponse({"error": error}, status=409)
            
            if accept:
                if not booking.cancel():
                    error = "No se ha podido cancelar la reserva."

                    if is_html_form:
                        messages.error(request, error)
                        return redirect_after_booking_cancellation(
                            request, raw_token
                        )

                    return JsonResponse({"error": error}, status=409)

                # Cancelar las propuestas de cambio pendientes y notificar.
                pending_proposals = list(
                    BookingChangeProposal.objects.select_for_update().filter(
                        booking=booking,
                        status=BookingChangeProposal.Status.PENDING,
                    )
                )

                for proposal in pending_proposals:
                    proposal.status = BookingChangeProposal.Status.CANCELLED
                    proposal.save(update_fields=["status"])

                    transaction.on_commit(
                        lambda b=booking, p=proposal:
                            send_booking_change_proposal_status_email(
                                b, p, "cancelled"
                            )
                    )

                # Cerrar las demás solicitudes de cancelación pendientes y notificar.
                pending_cancellations = list(
                    BookingCancellationRequest.objects.select_for_update().filter(
                        booking=booking,
                        status=BookingCancellationRequest.Status.PENDING,
                    ).exclude(
                        pk=cancellation.pk,
                    )
                )

                for other_cancellation in pending_cancellations:
                    other_cancellation.status = (
                        BookingCancellationRequest.Status.CANCELLED
                    )
                    other_cancellation.save(update_fields=["status"])

                    transaction.on_commit(
                        lambda b=booking, c=other_cancellation:
                            send_booking_cancellation_proposal_status_email(
                                b, c, "cancelled"
                            )
                    )

                # Marcar como aceptada la solicitud actual.
                cancellation.status = (
                    BookingCancellationRequest.Status.ACCEPTED
                )
                cancellation.responded_at = now
                cancellation.save(
                    update_fields=["status", "responded_at"]
                )

            else:
                cancellation.status = (
                    BookingCancellationRequest.Status.REJECTED
                )
                cancellation.responded_at = now
                cancellation.save(
                    update_fields=["status", "responded_at"]
                )

    except IntegrityError:
        error = "No se ha podido procesar la respuesta."

        if is_html_form:
            messages.error(request, error)
            return redirect_after_booking_cancellation(
                request, raw_token
            )

        return JsonResponse({"error": error}, status=409)
    
    # Notificar al propietario únicamente después de confirmar la transacción en la base de datos.
    email_status = "accepted" if accept else "rejected"

    transaction.on_commit(
        lambda booking=booking, cancellation=cancellation,
               status=email_status:
            send_booking_cancellation_proposal_status_email(
                booking,
                cancellation,
                status,
            )
    )
    
    if accept:
        message = (
            "La solicitud de cancelación ha sido aceptada "
            "y la reserva se ha cancelado correctamente."
        )
    else:
        message = "La solicitud de cancelación ha sido rechazada correctamente."

    if is_html_form:
        messages.success(request, message)
        return redirect_after_booking_cancellation(request, raw_token)

    return JsonResponse({
        "id": cancellation.pk,
        "status": cancellation.status,
        "message": message,
    })
    
@require_POST
def accept_booking_cancellation(request, cancellation_request_id):
    return _respond_to_booking_cancellation(
        request,
        cancellation_request_id,
        accept=True,
    )

@require_POST
def reject_booking_cancellation(request, cancellation_request_id):
    return _respond_to_booking_cancellation(
        request,
        cancellation_request_id,
        accept=False,
    )

@require_POST
def accept_booking_change_proposal(request, proposal_id):
    if request.method != "POST":
        return JsonResponse(
            {"error": "Método no permitido."},
            status=405,
        )
    
    accept_header = request.headers.get("Accept", "")

    is_html_form = (
        "text/html" in accept_header
        and "application/json" not in accept_header
        and request.content_type != "application/json"
    )
    
    raw_token = request.POST.get("token", "")

    # Comprobación inicial de autorización.
    proposal = get_object_or_404(
        BookingChangeProposal.objects.select_related(
            "booking",
            "booking__property",
        ),
        pk=proposal_id,
    )

    authorize_booking_change_proposal(
        request,
        proposal.booking,
        proposal,
        raw_token,
    )

    try:
        with transaction.atomic():
            # Bloquear primero la reserva y después la propuesta.
            booking = get_object_or_404(
                Booking.objects.select_for_update().select_related(
                    "property",
                    "property__owner",
                ),
                pk=proposal.booking_id,
            )

            proposal = get_object_or_404(
                BookingChangeProposal.objects.select_for_update(),
                pk=proposal_id,
                booking=booking,
            )

            # Repetir la autorización con la reserva y la propuesta bloqueadas.
            authorize_booking_change_proposal(
                request,
                booking,
                proposal,
                raw_token,
            )

            if proposal.status != BookingChangeProposal.Status.PENDING:
                if is_html_form:
                    messages.error(request, "La propuesta ya no está pendiente.")
                    return redirect_after_booking_change(request, raw_token)

                return JsonResponse(
                    {"error": "La propuesta ya no está pendiente."},
                    status=409,
                )

            if proposal.is_expired():
                proposal.status = BookingChangeProposal.Status.EXPIRED
                proposal.save(update_fields=["status"])
                
                transaction.on_commit(
                    lambda booking=booking, proposal=proposal:
                        send_booking_change_proposal_status_email(
                            booking, proposal, "expired"
                        )
                )

                if is_html_form:
                    messages.error(request, "La propuesta ha caducado.")
                    return redirect_after_booking_change(request, raw_token)

                return JsonResponse(
                    {"error": "La propuesta ha caducado."},
                    status=409,
                )

            if booking.status not in Booking.ACTIVE_STATUSES:
                if is_html_form:
                    messages.error(request, "La reserva ya no admite cambios.")
                    return redirect_after_booking_change(request, raw_token)

                return JsonResponse(
                    {"error": "La reserva ya no admite cambios."},
                    status=409,
                )

            if (
                booking.status == "PENDING"
                and booking.expires_at is not None
                and booking.expires_at <= timezone.now()
            ):
                if is_html_form:
                    messages.error(request, "La reserva pendiente ha caducado.")
                    return redirect_after_booking_change(request, raw_token)

                return JsonResponse(
                    {"error": "La reserva pendiente ha caducado."},
                    status=409,
                )

            property = Property.objects.select_for_update().get(
                pk=booking.property_id
            )

            initial_date = proposal.proposed_initial_date
            final_date = proposal.proposed_final_date
            guest_count = proposal.proposed_guest_count

            if initial_date >= final_date:
                if is_html_form:
                    messages.error(request, "El intervalo de fechas no es válido.")
                    return redirect_after_booking_change(request, raw_token)

                return JsonResponse(
                    {"error": "El intervalo de fechas no es válido."},
                    status=400,
                )

            if guest_count < 1:
                if is_html_form:
                    messages.error(request, "El número de huéspedes no es válido.")
                    return redirect_after_booking_change(request, raw_token)

                return JsonResponse(
                    {"error": "El número de huéspedes no es válido."},
                    status=400,
                )

            if guest_count > property.adults + property.children:
                if is_html_form:
                    messages.error(request, "La capacidad de la vivienda es insuficiente.")
                    return redirect_after_booking_change(request, raw_token)

                return JsonResponse(
                    {"error": "La capacidad de la vivienda es insuficiente."},
                    status=400,
                )

            # Consultar las tarifas actuales usando la lógica existente.
            availability = PropertyAvailability.get_for_range(
                property,
                initial_date,
                final_date,
            )
            
            expected_dates = [
                initial_date + timedelta(days=offset)
                for offset in range((final_date - initial_date).days)
            ]
            actual_dates = [item["date"] for item in availability]

            if actual_dates != expected_dates:
                error = (
                    "No se ha podido verificar la disponibilidad "
                    "de todas las noches."
                )

                if is_html_form:
                    messages.error(request, error)
                    return redirect_after_booking_change(request, raw_token)

                return JsonResponse(
                    {"error": error},
                    status=409,
                )

            if not availability:
                if is_html_form:
                    messages.error(
                        request,
                        "El intervalo de fechas no es válido.",
                    )
                    return redirect_after_booking_change(request, raw_token)

                return JsonResponse(
                    {"error": "El intervalo de fechas no es válido."},
                    status=400,
                )

            if any(
                item["status"] != "OPEN"
                for item in availability
            ):
                if is_html_form:
                    messages.error(request, "Hay noches que ya no están disponibles.")
                    return redirect_after_booking_change(request, raw_token)

                return JsonResponse(
                    {"error": "Hay noches que ya no están disponibles."},
                    status=409,
                )

            minimum_nights = availability[0]["min_nights"]
            number_of_nights = (final_date - initial_date).days

            if number_of_nights < minimum_nights:
                if is_html_form:
                    messages.error(request, "La estancia es inferior al mínimo requerido.")
                    return redirect_after_booking_change(request, raw_token)

                return JsonResponse(
                    {"error": "La estancia es inferior al mínimo requerido."},
                    status=400,
                )

            # Comprobar que la propuesta tiene un snapshot válido.
            if (
                not proposal.proposed_nightly_prices
                or proposal.proposed_total_price is None
            ):
                if is_html_form:
                    messages.error(
                        request,
                        "La propuesta no tiene un precio guardado válido. "
                        "Debe crearse una nueva propuesta.",
                    )
                    return redirect_after_booking_change(request, raw_token)

                return JsonResponse(
                    {
                        "error": (
                            "La propuesta no tiene un precio guardado válido. "
                            "Debe crearse una nueva propuesta."
                        )
                    },
                    status=409,
                )

            # Construir el desglose actual usando formato decimal estable.
            current_nightly_prices = [
                {
                    "date": item["date"].isoformat(),
                    "price_per_night": f'{Decimal(str(item["price_per_night"])):.2f}',
                }
                for item in availability
            ]

            current_total_price = sum(
                (
                    Decimal(str(item["price_per_night"]))
                    for item in availability
                ),
                Decimal("0.00"),
            )

            proposed_nightly_prices = [
                {
                    "date": item["date"],
                    "price_per_night": f'{Decimal(str(item["price_per_night"])):.2f}',
                }
                for item in proposal.proposed_nightly_prices
            ]

            proposed_total_price = Decimal(str(proposal.proposed_total_price))

            if (
                current_nightly_prices != proposed_nightly_prices
                or current_total_price != proposed_total_price
            ):
                if is_html_form:
                    messages.error(
                        request,
                        "El precio de la propuesta ha cambiado. "
                        "Debe crearse una nueva propuesta.",
                    )
                    return redirect_after_booking_change(request, raw_token)

                return JsonResponse(
                    {
                        "error": (
                            "El precio de la propuesta ha cambiado. "
                            "Debe crearse una nueva propuesta."
                        ),
                        "proposed_total_price": str(proposed_total_price),
                        "current_total_price": str(current_total_price),
                    },
                    status=409,
                )
                
            old_total = sum(
                (
                    night.price_per_night
                    for night in booking.nights.all()
                ),
                Decimal("0.00"),
            )

            before_values = {
                "initial_date": booking.initial_date.isoformat(),
                "final_date": booking.final_date.isoformat(),
                "guest_count": booking.guest_count,
                "total_price": str(old_total),
            }

            # Preparar las noches con los precios aceptados,
            # no recalcular sus importes al guardar la reserva.
            new_nights = [
                BookingNight(
                    booking=booking,
                    date=date.fromisoformat(item["date"]),
                    price_per_night=Decimal(
                        str(item["price_per_night"])
                    ),
                )
                for item in proposed_nightly_prices
            ]

            # Actualizar la reserva conservando estado y caducidad.
            booking.initial_date = initial_date
            booking.final_date = final_date
            booking.guest_count = guest_count

            booking.save(
                update_fields=[
                    "initial_date",
                    "final_date",
                    "guest_count",
                ]
            )

            # Reemplazar las noches dentro de la transacción.
            booking.nights.all().delete()
            BookingNight.objects.bulk_create(new_nights)

            # Marcar la propuesta como aceptada.
            proposal.status = BookingChangeProposal.Status.ACCEPTED
            proposal.save(update_fields=["status"])
            
            after_values = {
                "initial_date": booking.initial_date.isoformat(),
                "final_date": booking.final_date.isoformat(),
                "guest_count": booking.guest_count,
                "total_price": str(proposed_total_price),
                "reason": proposal.reason,
                "change_mode": "proposal",
                "actor_type": (
                    "user" if request.user.is_authenticated else "guest"
                ),
            }

            BookingChangeAudit.objects.create(
                booking=booking,
                actor=request.user if request.user.is_authenticated else None,
                reason=proposal.reason,
                before_values=before_values,
                after_values=after_values,
            )
            
            transaction.on_commit(
                lambda booking=booking, proposal=proposal:
                    send_booking_change_proposal_status_email(
                        booking, proposal, "accepted"
                    )
            )

    except ValidationError as exc:
        if is_html_form:
            messages.error(
                request,
                "La reserva no supera las validaciones.",
            )
            return redirect_after_booking_change(request, raw_token)

        return JsonResponse(
            {
                "error": "La reserva no supera las validaciones.",
                "details": (
                    exc.message_dict
                    if hasattr(exc, "message_dict")
                    else exc.messages
                ),
            },
            status=400,
        )

    except IntegrityError:
        if is_html_form:
            messages.error(
                request,
                "No se puede aceptar la propuesta porque existe "
                "un conflicto con la disponibilidad.",
            )
            return redirect_after_booking_change(request, raw_token)

        return JsonResponse(
            {
                "error": (
                    "No se puede aceptar la propuesta porque "
                    "existe un conflicto con la disponibilidad."
                )
            },
            status=409,
        )

    if is_html_form:
        messages.success(
            request,
            "Has aceptado la propuesta de cambio de reserva.",
        )
        return redirect_after_booking_change(request, raw_token)

    return JsonResponse(
        {
            "id": proposal.pk,
            "status": proposal.status,
        },
        status=200,
    )

@require_POST
def reject_booking_change_proposal(request, proposal_id):
    if request.method != "POST":
        return JsonResponse(
            {"error": "Método no permitido."},
            status=405,
        )

    accept_header = request.headers.get("Accept", "")
    is_html_form = (
        "text/html" in accept_header
        and "application/json" not in accept_header
        and request.content_type != "application/json"
    )
    
    raw_token = request.POST.get("token", "")

    proposal = get_object_or_404(
        BookingChangeProposal.objects.select_related("booking"),
        pk=proposal_id,
    )
    
    authorize_booking_change_proposal(
        request,
        proposal.booking,
        proposal,
        raw_token,
    )

    with transaction.atomic():
        # Bloquear primero la reserva, igual que en la aceptación.
        booking = get_object_or_404(
            Booking.objects.select_for_update(),
            pk=proposal.booking_id,
        )

        proposal = get_object_or_404(
            BookingChangeProposal.objects.select_for_update(),
            pk=proposal_id,
            booking=booking,
        )

        # Repetir la autorización con la reserva y la propuesta bloqueadas.
        authorize_booking_change_proposal(
            request,
            booking,
            proposal,
            raw_token,
        )

        if proposal.status != BookingChangeProposal.Status.PENDING:
            if is_html_form:
                messages.error(request, "La propuesta ya no está pendiente.")
                return redirect_after_booking_change(request, raw_token)

            return JsonResponse(
                {"error": "La propuesta ya no está pendiente."},
                status=409,
            )

        if proposal.is_expired():
            proposal.status = BookingChangeProposal.Status.EXPIRED
            proposal.save(update_fields=["status"])
            
            transaction.on_commit(
                lambda booking=booking, proposal=proposal:
                    send_booking_change_proposal_status_email(
                        booking, proposal, "expired"
                    )
            )

            if is_html_form:
                messages.error(request, "La propuesta ha caducado.")
                return redirect_after_booking_change(request, raw_token)

            return JsonResponse(
                {"error": "La propuesta ha caducado."},
                status=409,
            )

        proposal.status = BookingChangeProposal.Status.REJECTED
        proposal.save(update_fields=["status"])
        
        transaction.on_commit(
            lambda booking=booking, proposal=proposal:
                send_booking_change_proposal_status_email(
                    booking, proposal, "rejected"
                )
        )

        if is_html_form:
            messages.success(request, "Has rechazado la propuesta de cambio.")
            return redirect_after_booking_change(request, raw_token)

        return JsonResponse(
            {
                "id": proposal.pk,
                "status": proposal.status,
            },
            status=200,
        )

def create_booking_hold(request, property_id):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body)
        initial_date = date.fromisoformat(data.get("start", ""))
        final_date = date.fromisoformat(data.get("end", ""))
    except (json.JSONDecodeError, TypeError, ValueError):
        return JsonResponse({"error": "Fechas inválidas."}, status=400)

    if initial_date >= final_date:
        return JsonResponse(
            {"error": "La fecha de salida debe ser posterior a la entrada."},
            status=400,
        )

    if initial_date < timezone.localdate():
        return JsonResponse(
            {"error": "La fecha de entrada no puede ser anterior a hoy."},
            status=400,
        )

    try:
        with transaction.atomic():
            property_obj = get_object_or_404(
                Property.objects.select_for_update().filter(
                    owner__owner_profile__status="APPROVED"
                ),
                pk=property_id,
            )

            now = timezone.now()

            if (
                request.user.is_authenticated
                and request.user == property_obj.owner
            ):
                return JsonResponse(
                    {"error": "No puedes reservar tu propia vivienda."},
                    status=400,
                )

            availability = PropertyAvailability.get_for_range(
                property_obj, initial_date, final_date
            )

            if any(day["status"] == "CLOSED" for day in availability):
                return JsonResponse(
                    {"error": "El alojamiento no está disponible en esas fechas."},
                    status=409,
                )

            arrival = PropertyAvailability.get_for_date(
                property_obj, initial_date
            )

            if (final_date - initial_date).days < arrival["min_nights"]:
                return JsonResponse(
                    {
                        "error": (
                            f"La estancia debe ser de al menos "
                            f"{arrival['min_nights']} noches."
                        )
                    },
                    status=400,
                )

            if initial_date < (
                timezone.localdate()
                + timedelta(days=property_obj.notice_period_days)
            ):
                return JsonResponse(
                    {"error": "La fecha de entrada no cumple la antelación mínima."},
                    status=400,
                )

            existing_booking = Booking.objects.filter(
                property=property_obj,
                initial_date__lt=final_date,
                final_date__gt=initial_date,
            ).filter(
                Q(status="CONFIRMED")
                | Q(status="PENDING", expires_at__gt=now)
            ).exists()

            existing_hold = BookingHold.objects.filter(
                property=property_obj,
                initial_date__lt=final_date,
                final_date__gt=initial_date,
                expires_at__gt=now,
            ).exists()

            if existing_booking or existing_hold:
                return JsonResponse(
                    {"error": "El alojamiento ya está reservado o retenido en esas fechas."},
                    status=409,
                )

            hold = BookingHold.objects.create(
                property=property_obj,
                initial_date=initial_date,
                final_date=final_date,
                expires_at=now + timedelta(minutes=BOOKING_HOLD_MINUTES),
            )

            return JsonResponse(
                {
                    "success": True,
                    "token": str(hold.token),
                    "expires_at": hold.expires_at.isoformat(),
                }
            )

    except Property.DoesNotExist:
        return JsonResponse({"error": "Alojamiento no encontrado."}, status=404)
    except IntegrityError:
        return JsonResponse(
            {"error": "No se pudieron retener esas fechas. Inténtalo de nuevo."},
            status=409,
        )

def release_booking_hold(request, property_id):
    if request.method != "POST":
        return JsonResponse(
            {"error": "Method not allowed"},
            status=405,
        )

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return JsonResponse(
            {"error": "JSON inválido."},
            status=400,
        )

    if not isinstance(data, dict):
        return JsonResponse(
            {"error": "JSON inválido."},
            status=400,
        )

    token = data.get("hold_token")

    if not isinstance(token, str) or not token:
        return JsonResponse(
            {"error": "Falta el token de la retención."},
            status=400,
        )

    try:
        with transaction.atomic():
            # Usamos el mismo orden de bloqueo que al crear la reserva:
            # primero el alojamiento y después la retención.
            property_obj = Property.objects.select_for_update().get(
                pk=property_id
            )

            hold = BookingHold.objects.select_for_update().filter(
                token=token,
                property=property_obj,
            ).first()

            if hold is not None:
                hold.delete()

        return JsonResponse({"success": True})

    except Property.DoesNotExist:
        return JsonResponse(
            {"error": "Alojamiento no encontrado."},
            status=404,
        )

def mock_payment(request, booking_id):
    if request.method not in ("GET", "POST"):
        return JsonResponse(
            {"error": "Method not allowed"},
            status=405,
        )

    booking = get_object_or_404(Booking, pk=booking_id)

    # Si el huésped ha iniciado sesión, solo puede acceder
    # a sus propias reservas.
    if request.user.is_authenticated:
        if booking.tenant_id != request.user.pk:
            return HttpResponse(
                "No tienes permiso para acceder a esta reserva.",
                status=403,
            )
    else:
        # Para huéspedes anónimos, el acceso se limita a las reservas
        # registradas en la sesión que creó la reserva.
        anonymous_booking_ids = request.session.get(
            "anonymous_booking_ids",
            [],
        )

        if booking.tenant_id is not None or booking.pk not in anonymous_booking_ids:
            return HttpResponse(
                "No tienes permiso para acceder a esta reserva.",
                status=403,
            )

    error_message = ""

    if request.method == "POST":
        if booking.status == "CONFIRMED":
            # Evita confirmar de nuevo una reserva ya confirmada.
            pass
        elif booking.status != "PENDING":
            error_message = (
                "Esta reserva ya no está pendiente y no se puede confirmar."
            )
        elif booking.is_expired():
            booking.expire()
            error_message = (
                "La reserva ha caducado. Selecciona las fechas de nuevo."
            )
        else:
            # Simulación de pago: no se procesa ningún cobro.
            if booking.confirm():
                transaction.on_commit(
                    lambda booking_id=booking.pk: send_booking_confirmation_emails(
                        Booking.objects.select_related(
                            "property",
                            "property__owner",
                        ).get(pk=booking_id)
                    )
                )

                if request.user.is_authenticated:
                    return redirect("my_bookings")

                return render(
                    request,
                    "bookings/mock_payment.html",
                    {
                        "booking": booking,
                        "payment_complete": True,
                        "error_message": "",
                    },
                )

            booking.refresh_from_db()

            if booking.status == "EXPIRED":
                error_message = (
                    "La reserva ha caducado. Selecciona las fechas de nuevo."
                )
            elif booking.status == "CONFIRMED":
                pass
            else:
                error_message = (
                    "No se ha podido confirmar la reserva."
                )

    return render(
        request,
        "bookings/mock_payment.html",
        {
            "booking": booking,
            "payment_complete": booking.status == "CONFIRMED",
            "error_message": error_message,
        },
    )

def booking_details(request, property_id):
    property_obj = get_available_property(property_id)

    initial_date = request.GET.get("initial_date", "").strip()
    final_date = request.GET.get("final_date", "").strip()
    token = request.GET.get("hold_token", "").strip()

    if not initial_date or not final_date or not token:
        return redirect("property", property_id=property_id)

    try:
        start = date.fromisoformat(initial_date)
        end = date.fromisoformat(final_date)
    except ValueError:
        return redirect("property", property_id=property_id)

    hold = BookingHold.objects.filter(
        token=token,
        property=property_obj,
        initial_date=start,
        final_date=end,
        expires_at__gt=timezone.now(),
    ).first()

    if hold is None:
        return redirect("property", property_id=property_id)

    total_nights = (end - start).days
    availability = PropertyAvailability.get_for_range(property_obj, start, end)
    total_price = sum(
        (day["price_per_night"] for day in availability), Decimal("0.00")
    )
    included_vat = (total_price * Decimal("0.10")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    max_guests = property_obj.adults + property_obj.children

    return render(
        request,
        "bookings/booking_details.html",
        {
            "property": property_obj,
            "initial_date": initial_date,
            "final_date": final_date,
            "start_date": start,
            "end_date": end,
            "total_nights": total_nights,
            "total_price": total_price,
            "included_vat": included_vat,
            "max_guests": max_guests,
            "hold_token": str(hold.token),
        },
    )

BOOKING_HOLD_MINUTES = 10
PENDING_BOOKING_MINUTES = 10

def create_booking(request, property_id):
    if request.method != "POST":
        return JsonResponse(
            {"error": "Method not allowed"},
            status=405,
        )

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(
            {"error": "JSON inválido"},
            status=400,
        )

    if not isinstance(data, dict):
        return JsonResponse(
            {"error": "JSON inválido"},
            status=400,
        )

    initial_date_raw = data.get("start")
    final_date_raw = data.get("end")

    if not initial_date_raw or not final_date_raw:
        return JsonResponse(
            {"error": "Ambas fechas deben ser seleccionadas."},
            status=400,
        )

    try:
        initial_date = date.fromisoformat(initial_date_raw)
        final_date = date.fromisoformat(final_date_raw)
    except (TypeError, ValueError):
        return JsonResponse(
            {"error": "Formato de fecha inválido."},
            status=400,
        )

    property = get_available_property(property_id)
    
    hold_token = data.get("hold_token")
    
    if not isinstance(hold_token, str) or not hold_token:
        return JsonResponse(
            {"error": "Falta la retención temporal de las fechas."},
            status=400,
        )

    text_fields = (
        "guest_first_name",
        "guest_last_name",
        "guest_email",
        "guest_phone_number",
        "guest_country",
        "guest_region",
        "guest_city",
        "guest_postal_code",
        "guest_address",
        "tax_id",
        "special_requests",
    )

    invalid_fields = [
        field
        for field in text_fields
        if field in data and not isinstance(data[field], str)
    ]

    if invalid_fields:
        return JsonResponse(
            {
                "error": "Los campos de texto deben ser cadenas.",
                "fields": invalid_fields,
            },
            status=400,
        )

    guest_first_name = data.get("guest_first_name", "").strip()
    guest_last_name = data.get("guest_last_name", "").strip()
    guest_email = data.get("guest_email", "").strip()
    guest_phone_number = data.get("guest_phone_number", "").strip()

    guest_country = data.get("guest_country", "").strip()
    guest_region = data.get("guest_region", "").strip()
    guest_city = data.get("guest_city", "").strip()
    guest_postal_code = data.get("guest_postal_code", "").strip()
    guest_address = data.get("guest_address", "").strip()

    is_for_self = data.get("is_for_self", True)
    is_business_trip = data.get("is_business_trip", False)

    if not isinstance(is_for_self, bool):
        return JsonResponse(
            {"error": "is_for_self debe ser booleano."},
            status=400,
        )

    if not isinstance(is_business_trip, bool):
        return JsonResponse(
            {"error": "is_business_trip debe ser booleano."},
            status=400,
        )

    tax_id = data.get("tax_id", "").strip()
    special_requests = data.get("special_requests", "").strip()

    raw_guest_count = data.get("guest_count")
    raw_arrival_time = data.get("arrival_time")

    required_fields = {
        "guest_first_name": guest_first_name,
        "guest_last_name": guest_last_name,
        "guest_email": guest_email,
        "guest_phone_number": guest_phone_number,
        "guest_country": guest_country,
        "guest_city": guest_city,
        "guest_address": guest_address,
        "guest_count": raw_guest_count,
        "arrival_time": raw_arrival_time,
    }

    missing_fields = [
        field
        for field, value in required_fields.items()
        if value is None or value == ""
    ]

    if missing_fields:
        return JsonResponse(
            {
                "error": "Faltan campos obligatorios.",
                "fields": missing_fields,
            },
            status=400,
        )

    try:
        guest_count = int(raw_guest_count)
    except (TypeError, ValueError):
        return JsonResponse(
            {
                "error": (
                    "El número de huéspedes debe ser "
                    "un número entero."
                )
            },
            status=400,
        )

    try:
        arrival_time = time.fromisoformat(raw_arrival_time)
    except (TypeError, ValueError):
        return JsonResponse(
            {
                "error": "Formato de hora de llegada inválido."
            },
            status=400,
        )

    tenant = (
        request.user
        if request.user.is_authenticated
        else None
    )

    try:
        with transaction.atomic():
            locked_property = Property.objects.select_for_update().get(
                pk=property_id
            )

            hold = BookingHold.objects.select_for_update().filter(
                token=hold_token,
                property=locked_property,
                initial_date=initial_date,
                final_date=final_date,
                expires_at__gt=timezone.now(),
            ).first()

            if hold is None:
                return JsonResponse(
                    {
                        "error": (
                            "La retención ha vencido o ya no es válida. "
                            "Selecciona las fechas de nuevo."
                        )
                    },
                    status=409,
                )

            expires_at = hold.expires_at

            booking = Booking.create_pending(
                tenant=tenant,
                property=locked_property,
                initial_date=initial_date,
                final_date=final_date,
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
                hold_token=hold.token,
            )

            hold.delete()

    except IntegrityError:
        return JsonResponse(
            {
                "error": "El alojamiento ya está reservado en esas fechas."
            },
            status=409,
        )

    except ValidationError as e:
        return JsonResponse(
            {
                "error": (
                    e.message_dict
                    if hasattr(e, "message_dict")
                    else str(e)
                )
            },
            status=400,
        )
    
    
    # Si el huésped no ha iniciado sesión, guardamos en su sesión el identificador de la reserva que acaba de crear.
    if not request.user.is_authenticated:
        anonymous_booking_ids = request.session.get(
            "anonymous_booking_ids",
            [],
        )

        anonymous_booking_ids.append(booking.pk)

        request.session["anonymous_booking_ids"] = anonymous_booking_ids

    return JsonResponse(
        {
            "success": True,
            "message": "Reserva pendiente.",
            "booking_id": booking.pk,
            "payment_url": reverse(
                "mock_payment",
                args=[booking.pk],
            ),
        }
    )

class LoginForm(AuthenticationForm):
    error_messages = {
        'invalid_login': "Usuario o contraseña incorrectos. Inténtalo de nuevo.",
    }

def login_view(request):
    if request.method == "POST":
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            
            if user is not None:
                login(request, user)
                return HttpResponseRedirect(reverse("index"))
        
        return render(request, "bookings/login.html", {
            "form": form
        })
    else:
        return render(request, "bookings/login.html", {
            "form": LoginForm()
        })

def logout_view(request):
    if request.method != "POST":
        return JsonResponse(
            {"error": "Method not allowed"},
            status=405,
        )

    logout(request)
    return HttpResponseRedirect(reverse("index"))

class RegisterForm(UserCreationForm):
    account_type = forms.ChoiceField(
        label="Tipo de cuenta",
        choices=[
            ("customer", "Huésped"),
            ("owner", "Propietario"),
        ],
        widget=forms.RadioSelect,
        initial="customer",
        error_messages={
            "required": "Selecciona un tipo de cuenta.",
            "invalid_choice": "Selecciona un tipo de cuenta válida.",
        },
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = (
            "first_name",
            "last_name",
            "username",
            "email",
            "phone_number",
        )

        labels = {
            "first_name": "Nombre",
            "last_name": "Apellidos",
            "username": "Nombre de usuario",
            "email": "Correo electrónico",
            "phone_number": "Número de teléfono",
        }

        error_messages = {
            "first_name": {
                "required": "Introduce tu nombre.",
                "blank": "El nombre no puede estar vacío.",
            },
            "last_name": {
                "required": "Introduce tus apellidos.",
                "blank": "Los apellidos no pueden estar vacíos.",
            },
            "username": {
                "required": "Introduce un nombre de usuario.",
                "blank": "El nombre de usuario no puede estar vacío.",
                "unique": "Este nombre de usuario ya está en uso. Elige otro.",
                "invalid": "El nombre de usuario contiene caracteres no permitidos.",
            },
            "email": {
                "required": "Introduce tu correo electrónico.",
                "blank": "El correo electrónico no puede estar vacío.",
                "invalid": "Introduce una dirección de correo electrónico válida.",
                "unique": "Ya existe una cuenta con este correo electrónico.",
            },
            "phone_number": {
                "required": "Introduce tu número de teléfono.",
                "blank": "El número de teléfono no puede estar vacío.",
                "unique": "Ya existe una cuenta con este número de teléfono.",
                "invalid": "Introduce un número de teléfono válido.",
            },
            "password2": {
                "password_mismatch": "Las contraseñas no coinciden.",
            },
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Eliminar textos de ayuda
        self.fields["username"].help_text = ""
        self.fields["password1"].help_text = ""
        self.fields["password2"].help_text = ""

        self.fields["phone_number"].required = True

        # Mensajes de validación de los campos del formulario
        self.fields["username"].error_messages.update({
            "required": "Introduce un nombre de usuario.",
            "unique": "Este nombre de usuario ya está en uso. Elige otro.",
            "invalid": "El nombre de usuario contiene caracteres no permitidos.",
        })

        self.fields["email"].error_messages.update({
            "required": "Introduce tu correo electrónico.",
            "invalid": "Introduce una dirección de correo electrónico válida.",
        })

        self.fields["phone_number"].error_messages.update({
            "required": "Introduce tu número de teléfono.",
            "invalid": "Introduce un número de teléfono válido.",
        })

        self.fields["password1"].error_messages.update({
            "required": "Introduce una contraseña.",
        })

        self.fields["password2"].error_messages.update({
            "required": "Confirma tu contraseña.",
            "password_mismatch": "Las contraseñas no coinciden.",
        })

class UserForm(ModelForm):
    class Meta:
        model = User
        fields = (
            "first_name",
            "last_name",
            "username",
            "email",
            "phone_number",
        )
        labels = {
            "first_name": "Nombre",
            "last_name": "Apellidos",
            "username": "Nombre de usuario",
            "email": "Correo electrónico",
            "phone_number": "Número de teléfono",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Eliminar textos de ayuda
        self.fields["username"].help_text = ""
        
        self.fields["phone_number"].required = True
        
def manage_profile(request, user_id=None):
    User = get_user_model()
    url_name = request.resolver_match.url_name

    # Un usuario autenticado no debe acceder al registro.
    if request.user.is_authenticated and url_name == "register":
        return redirect("edit_profile")

    # Solo usuarios autenticados pueden editar perfiles.
    if not request.user.is_authenticated and url_name != "register":
        return redirect("login")

    is_registration = url_name == "register"
    is_admin_edit = False

    if is_registration:
        form_class = RegisterForm
        instance = None

    else:
        # Si se proporciona un ID, se intenta editar ese usuario.
        if user_id is not None:
            target_user = get_object_or_404(User, pk=user_id)

            # Cada usuario puede editar su propio perfil.
            # Solo el personal puede editar perfiles ajenos.
            if (
                request.user.pk != target_user.pk
                and not request.user.is_staff
            ):
                raise PermissionDenied

            is_admin_edit = request.user.pk != target_user.pk
            instance = target_user

        else:
            # Edición del perfil propio.
            instance = request.user

        form_class = UserForm

    if request.method == "POST":
        form = form_class(
            request.POST,
            instance=instance,
        )

        if form.is_valid():
            with transaction.atomic():
                user = form.save()

                if (
                    is_registration
                    and form.cleaned_data.get("account_type") == "owner"
                ):
                    OwnerProfile.objects.create(
                        user=user,
                        status="PENDING",
                    )

            if is_registration:
                login(request, user)

                if form.cleaned_data.get("account_type") == "owner":
                    messages.success(
                        request,
                        "Tu cuenta se ha creado correctamente. "
                        "Tu solicitud de propietario está pendiente "
                        "de aprobación."
                    )
                else:
                    messages.success(
                        request,
                        "Tu cuenta se ha creado correctamente."
                    )

                return redirect("index")

            if is_admin_edit:
                return redirect("manage_users")

            messages.success(
                request,
                "Tu perfil se ha actualizado correctamente."
            )
            return redirect("index")

    else:
        form = form_class(instance=instance)
        
    owner_profile = None

    if request.user.is_authenticated and not is_admin_edit:
        owner_profile = getattr(request.user, "owner_profile", None)

    return render(
        request,
        "bookings/userForm.html",
        {
            "form": form,
            "editing_other_user": is_admin_edit,
            "profile_user": instance,
            "owner_profile": owner_profile,
        },
    )
    
@login_required
@require_POST
def request_owner_status_view(request):
    try:
        request_owner_status(request.user)
    except OwnerRequestError as exc:
        messages.info(request, str(exc))
    else:
        messages.success(
            request,
            "Tu solicitud se ha enviado correctamente. "
            "El administrador debe aprobarla antes de que puedas "
            "gestionar propiedades."
        )

        send_owner_request_notification_email(request.user)

    return redirect("edit_profile")