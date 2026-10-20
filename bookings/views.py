from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.http import HttpResponse, HttpResponseRedirect
from django.contrib.auth import authenticate, login, logout
from django.views.decorators.csrf import csrf_exempt
from django.db import IntegrityError
from django.db.models import Exists, F, Q, IntegerField, OuterRef, Subquery, Sum, Value, DecimalField, Prefetch
from django.db.models.functions import Coalesce
from .models import User, OwnerProfile, Property, Booking, BookingChangeProposal, BookingAttachment, BookingChangeAudit, BookingNight, PropertyAvailability, BookingHold, can_manage_properties
from django import forms
from django.forms import ModelForm
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.forms import AuthenticationForm
from django.http import JsonResponse, FileResponse, Http404
from datetime import date, time, timedelta
from django.utils import timezone
from decimal import Decimal, InvalidOperation
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.contrib.auth.decorators import login_required
import json
from django.core.exceptions import ValidationError
from django.core.exceptions import PermissionDenied
from django.db import transaction
from .services import generate_proposal_access_token, hash_proposal_access_token
import logging
from django.contrib import messages
import secrets
import os
from django.core import signing
from .emails import (
    send_booking_change_proposal_email,
    send_booking_change_proposal_status_email,
    send_forced_booking_change_email,
)


# Create your views here.
class SearchForm(forms.Form):
    DESTINATION = [
        ('', '¿A dónde vas?'),
        ('Palos de la Frontera', 'Palos de la Frontera'),
        ('Mazagón', 'Mazagón')
    ]
    NUM_CHOICES = [(i, str(i)) for i in range(1, 11)]
    CHOICES_WITH_ZERO = [(i, str(i)) for i in range(0, 11)]

    location = forms.ChoiceField(label="Lugar", choices=DESTINATION)
    initial_date = forms.DateField(
        label="Entrada",
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'})
    )
    final_date = forms.DateField(
        label="Salida",
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'})
    )
    adults = forms.ChoiceField(label="Adultos", choices=NUM_CHOICES, required=False, initial=1)
    children = forms.ChoiceField(label="Niños", choices=CHOICES_WITH_ZERO, required=False, initial=0)
    rooms = forms.ChoiceField(label="Habitaciones", choices=NUM_CHOICES, required=False, initial=1)
    pets = forms.BooleanField(required=False, label="Mascotas")

def index(request):
    return render(request, "bookings/index.html", {
        "form": SearchForm()
    })

def property(request, property_id):

    property = get_object_or_404(Property, pk=property_id)

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

    bookings = bookings.prefetch_related(
        Prefetch(
            "change_proposals",
            queryset=proposals,
            to_attr="prefetched_change_proposals",
        )
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

def property_availability_data(request, property_id):
    
    property = get_object_or_404(Property, pk=property_id)

    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")

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
            {"error": "Method not allowed"},
            status=405,
        )

    with transaction.atomic():
        
        booking = get_object_or_404(
            Booking.objects.select_for_update(),
            pk=booking_id,
        )

        if booking.tenant_id != request.user.pk:
            return JsonResponse(
                {"error": "No tienes permiso para cancelar esta reserva."},
                status=403,
            )
            
        # Solo se pueden cancelar reservas pendientes o confirmadas.
        if booking.status not in ("PENDING", "CONFIRMED"):
            return redirect("my_bookings")

        # Si la reserva pendiente ya caducó, no se cancela:
        # se marca como caducada.
        if booking.status == "PENDING" and booking.is_expired():
            booking.expire()
            return redirect("my_bookings")

        booking.cancel()

    return redirect("my_bookings")

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

    properties = Property.objects.all()

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
    property = get_object_or_404(Property, pk=property_id)

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
        return render(
            request,
            "bookings/booking_change_proposal_error.html",
            {
                "error": "El enlace de la propuesta no es válido.",
            },
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

    return render(
        request,
        "bookings/booking_change_proposal_detail.html",
        context,
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

def download_forced_booking_attachment(request, attachment_id, token):
    try:
        data = signing.loads(
            token,
            salt="forced-booking-attachment",
            max_age=7 * 24 * 60 * 60,
        )
    except signing.BadSignature:
        raise Http404

    if data.get("attachment_id") != attachment_id:
        raise Http404

    try:
        attachment = BookingAttachment.objects.get(
            pk=attachment_id,
            change_audit_id=data.get("audit_id"),
        )
    except BookingAttachment.DoesNotExist:
        raise Http404

    return FileResponse(
        attachment.file.open("rb"),
        as_attachment=True,
        filename=(
            attachment.original_filename
            or attachment.file.name.split("/")[-1]
        ),
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

    reason = (data.get("reason") or "").strip()

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

def redirect_after_booking_change(request, raw_token):
    if raw_token:
        return redirect(
            "view_booking_change_proposal_by_token",
            token=raw_token,
        )

    return redirect("my_bookings")

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
            property_obj = Property.objects.select_for_update().get(
                pk=property_id
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
    property_obj = get_object_or_404(Property, pk=property_id)

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

    return render(
        request,
        "bookings/booking_details.html",
        {
            "property": property_obj,
            "initial_date": initial_date,
            "final_date": final_date,
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

    property = get_object_or_404(
        Property,
        pk=property_id,
    )
    
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
            ("customer", "Cliente"),
            ("owner", "Propietario"),
        ],
        widget=forms.RadioSelect,
        initial="customer",
    )
    
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("first_name","last_name","username", "email", "phone_number")
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Delete help texts
        self.fields['username'].help_text = ""
        self.fields['password1'].help_text = ""
        self.fields['password2'].help_text = ""

class UserForm(ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "username", "email", "phone_number")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Delete help texts
        self.fields['username'].help_text = ""


def manage_profile(request):
    # If an authenticated user tries to access the registration URL, redirect them to edit profile
    if request.user.is_authenticated and request.resolver_match.url_name == "register":
        return HttpResponseRedirect(reverse("edit_profile"))

    # If an unauthenticated user tries to access the edit profile URL, redirect them to login
    if not request.user.is_authenticated and request.resolver_match.url_name == "edit_profile":
        return HttpResponseRedirect(reverse("login"))

    if request.user.is_authenticated:
        form = UserForm(instance=request.user)
    else:
        form = RegisterForm()

    if request.method == "POST":
        if request.user.is_authenticated:
            form = UserForm(request.POST, instance=request.user)
        else:
            form = RegisterForm(request.POST)

        if form.is_valid():
            user = form.save()

            if not request.user.is_authenticated:
                if form.cleaned_data["account_type"] == "owner":
                    OwnerProfile.objects.create(
                        user=user,
                        status="PENDING",
                    )

                login(request, user)

            return HttpResponseRedirect(reverse("index"))
        else:
            return render(request, "bookings/userForm.html", {
                "form": form
            })
    else:
        return render(request, "bookings/userForm.html", {
            "form": form
        })