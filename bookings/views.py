from django.shortcuts import render
from django.urls import reverse
from django.http import HttpResponse, HttpResponseRedirect
from django.contrib.auth import authenticate, login, logout
from django.views.decorators.csrf import csrf_exempt
from django.db import IntegrityError
from django.db.models import Exists, F, IntegerField, OuterRef, Subquery
from django.db.models.functions import Coalesce
from .models import User, OwnerProfile, Property, Booking, BookingChangeProposal, BookingChangeAudit, BookingNight, PropertyAvailability, can_manage_properties
from django import forms
from django.forms import ModelForm
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.forms import AuthenticationForm
from django.http import JsonResponse
from datetime import date, time, timedelta
from django.utils import timezone
from decimal import Decimal, InvalidOperation
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.contrib.auth.decorators import login_required
import json
from django.core.exceptions import ValidationError
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.db import transaction
from .services import generate_proposal_access_token, hash_proposal_access_token

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

    active_bookings = property.bookings.filter(
        final_date__gte=today,
        status__in=Booking.ACTIVE_STATUSES,
    ).order_by("initial_date")

    min_booking_date = today + timedelta(days=property.notice_period_days)
    availability_end_date = min_booking_date + timedelta(days=365)

    availability_start_date = (
        min_booking_date - timedelta(days=1)
    )

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

    for booking in bookings:
        current_date = max(booking.initial_date, availability_start_date)
        booking_end = min(booking.final_date, availability_end_date)

        while current_date < booking_end:
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
    bookings = Booking.objects.filter(tenant=request.user)

    paginator = Paginator(bookings, 6)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, "bookings/my_bookings.html", {
        "bookings": bookings,
        "page_obj": page_obj
    })

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
def delete_booking(request, booking_id):
    booking = get_object_or_404(Booking, pk=booking_id)

    if request.method != "POST":
        return JsonResponse(
            {"error": "Method not allowed"},
            status=405,
        )

    if booking.tenant != request.user:
        raise PermissionDenied

    booking.cancel()
    return HttpResponseRedirect(reverse("my_bookings"))

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

@login_required
def admin_force_booking_change(request, booking_id):
    if request.method != "POST":
        return JsonResponse(
            {"error": "Method not allowed."},
            status=405,
        )

    if not request.user.is_staff:
        return JsonResponse(
            {"error": "Only administrators can force booking changes."},
            status=403,
        )

    from django.utils.dateparse import parse_date

    initial_date = parse_date(request.POST.get("initial_date", ""))
    final_date = parse_date(request.POST.get("final_date", ""))

    try:
        guest_count = int(request.POST.get("guest_count", ""))
    except (TypeError, ValueError):
        return JsonResponse(
            {"error": "Invalid guest count."},
            status=400,
        )

    if initial_date is None or final_date is None:
        return JsonResponse(
            {"error": "Invalid booking dates."},
            status=400,
        )

    try:
        with transaction.atomic():
            booking = (
                Booking.objects.select_for_update()
                .get(pk=booking_id)
            )

            property_obj = (
                Property.objects.select_for_update()
                .get(pk=booking.property_id)
            )

            booking.refresh_from_db()

            if booking.status not in Booking.ACTIVE_STATUSES:
                return JsonResponse(
                    {"error": "This booking cannot be changed."},
                    status=409,
                )

            if booking.is_expired():
                return JsonResponse(
                    {"error": "This booking has expired."},
                    status=409,
                )

            if initial_date >= final_date:
                return JsonResponse(
                    {
                        "error": (
                            "The final date must be after "
                            "the initial date."
                        )
                    },
                    status=400,
                )

            if guest_count < 1:
                return JsonResponse(
                    {"error": "Guest count must be at least 1."},
                    status=400,
                )

            capacity = property_obj.adults + property_obj.children

            if guest_count > capacity:
                return JsonResponse(
                    {"error": "Guest count exceeds property capacity."},
                    status=400,
                )

            availability = list(
                PropertyAvailability.get_for_range(
                    property_obj,
                    initial_date,
                    final_date,
                )
            )

            expected_nights = (final_date - initial_date).days

            if len(availability) != expected_nights:
                return JsonResponse(
                    {
                        "error": (
                            "Availability is incomplete for "
                            "the selected dates."
                        )
                    },
                    status=409,
                )

            if any(
                item["status"] != "OPEN"
                for item in availability
            ):
                return JsonResponse(
                    {
                        "error": (
                            "The property is unavailable for "
                            "the selected dates."
                        )
                    },
                    status=409,
                )

            if expected_nights < availability[0]["min_nights"]:
                return JsonResponse(
                    {
                        "error": (
                            "The stay does not meet the minimum "
                            "number of nights."
                        )
                    },
                    status=400,
                )

            before_values = {
                "initial_date": booking.initial_date.isoformat(),
                "final_date": booking.final_date.isoformat(),
                "guest_count": booking.guest_count,
                "status": booking.status,
                "nights": [
                    {
                        "date": night.date.isoformat(),
                        "price_per_night": str(night.price_per_night),
                    }
                    for night in booking.nights.order_by("date")
                ],
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

            BookingNight.objects.bulk_create(
                [
                    BookingNight(
                        booking=booking,
                        date=item["date"],
                        price_per_night=item["price_per_night"],
                    )
                    for item in availability
                ]
            )

            after_values = {
                "initial_date": booking.initial_date.isoformat(),
                "final_date": booking.final_date.isoformat(),
                "guest_count": booking.guest_count,
                "status": booking.status,
                "nights": [
                    {
                        "date": item["date"].isoformat(),
                        "price_per_night": str(item["price_per_night"]),
                    }
                    for item in availability
                ],
            }

            BookingChangeAudit.objects.create(
                booking=booking,
                actor=request.user,
                before_values=before_values,
                after_values=after_values,
            )

            pending_proposals = (
                BookingChangeProposal.objects.select_for_update()
                .filter(
                    booking=booking,
                    status="PENDING",
                )
            )
            pending_proposals.update(status="EXPIRED")

        return JsonResponse(
            {
                "success": True,
                "booking_id": booking.pk,
                "initial_date": booking.initial_date.isoformat(),
                "final_date": booking.final_date.isoformat(),
                "guest_count": booking.guest_count,
            },
            status=200,
        )

    except Booking.DoesNotExist:
        return JsonResponse(
            {"error": "Booking not found."},
            status=404,
        )
    except Property.DoesNotExist:
        return JsonResponse(
            {"error": "Property not found."},
            status=404,
        )
    except ValidationError as exc:
        return JsonResponse(
            {"error": exc.messages},
            status=400,
        )
    except IntegrityError:
        return JsonResponse(
            {
                "error": (
                    "The requested change conflicts with "
                    "existing bookings."
                )
            },
            status=409,
        )

def view_booking_change_proposal_by_token(request, token):
    if request.method != "GET":
        return JsonResponse(
            {"error": "Método no permitido."},
            status=405,
        )

    token_hash = hash_proposal_access_token(token)

    proposal = BookingChangeProposal.objects.select_related(
        "booking",
        "booking__property",
    ).filter(
        access_token_hash=token_hash,
    ).first()

    if proposal is None:
        return JsonResponse(
            {"error": "El enlace no es válido."},
            status=404,
        )

    if proposal.status != BookingChangeProposal.Status.PENDING:
        return JsonResponse(
            {"error": "Esta propuesta ya no está disponible."},
            status=410,
        )

    if proposal.is_expired():
        proposal.status = BookingChangeProposal.Status.EXPIRED
        proposal.save(update_fields=["status"])

        return JsonResponse(
            {"error": "Esta propuesta ha caducado."},
            status=410,
        )

    return JsonResponse({
        "booking_id": proposal.booking_id,
        "property_title": proposal.booking.property.title,
        "proposed_initial_date": proposal.proposed_initial_date.isoformat(),
        "proposed_final_date": proposal.proposed_final_date.isoformat(),
        "proposed_guest_count": proposal.proposed_guest_count,
        "expires_at": proposal.expires_at.isoformat(),
        "status": proposal.status,
    })

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

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            {"error": "JSON inválido."},
            status=400,
        )

    if not isinstance(data, dict):
        return JsonResponse(
            {"error": "El cuerpo debe ser un objeto JSON."},
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

            # Caducar propuestas anteriores vencidas antes de crear otra.
            BookingChangeProposal.objects.filter(
                booking=booking,
                status=BookingChangeProposal.Status.PENDING,
                expires_at__isnull=False,
                expires_at__lte=timezone.now(),
            ).update(status=BookingChangeProposal.Status.EXPIRED)

            # Una propuesta pendiente y vigente impide crear otra.
            if BookingChangeProposal.objects.filter(
                booking=booking,
                status=BookingChangeProposal.Status.PENDING,
                expires_at__gt=timezone.now(),
            ).exists():
                return JsonResponse(
                    {"error": "Ya existe una propuesta pendiente para esta reserva."},
                    status=409,
                )

            raw_token, token_hash = generate_proposal_access_token()

            proposal = BookingChangeProposal(
                booking=booking,
                proposed_initial_date=proposed_initial_date,
                proposed_final_date=proposed_final_date,
                proposed_guest_count=proposed_guest_count,
                access_token_hash=token_hash,
            )

            nightly_prices, total_price = proposal.calculate_price_snapshot()

            proposal.proposed_nightly_prices = nightly_prices
            proposal.proposed_total_price = total_price
            proposal.save()

    except ValidationError as exc:
        return JsonResponse(
            {"error": exc.messages},
            status=400,
        )
    except IntegrityError:
        return JsonResponse(
            {"error": "Ya existe una propuesta pendiente para esta reserva."},
            status=409,
        )

    return JsonResponse(
        {
            "id": proposal.pk,
            "booking_id": booking.pk,
            "status": proposal.status,
            "proposed_initial_date": proposal.proposed_initial_date.isoformat(),
            "proposed_final_date": proposal.proposed_final_date.isoformat(),
            "proposed_guest_count": proposal.proposed_guest_count,
            "proposed_total_price": str(proposal.proposed_total_price),
            "proposed_nightly_prices": proposal.proposed_nightly_prices,
            "expires_at": proposal.expires_at.isoformat(),
        },
        status=201,
    )

@login_required
def accept_booking_change_proposal(request, proposal_id):
    if request.method != "POST":
        return JsonResponse(
            {"error": "Método no permitido."},
            status=405,
        )

    # Comprobación inicial de autorización.
    proposal = get_object_or_404(
        BookingChangeProposal.objects.select_related(
            "booking",
            "booking__property",
        ),
        pk=proposal_id,
    )

    if proposal.booking.tenant != request.user:
        raise PermissionDenied

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

            # Repetir autorización dentro de la transacción.
            if booking.tenant != request.user:
                raise PermissionDenied

            if proposal.status != BookingChangeProposal.Status.PENDING:
                return JsonResponse(
                    {"error": "La propuesta ya no está pendiente."},
                    status=409,
                )

            if proposal.is_expired():
                proposal.status = BookingChangeProposal.Status.EXPIRED
                proposal.save(update_fields=["status"])

                return JsonResponse(
                    {"error": "La propuesta ha caducado."},
                    status=409,
                )

            if booking.status not in Booking.ACTIVE_STATUSES:
                return JsonResponse(
                    {"error": "La reserva ya no admite cambios."},
                    status=409,
                )

            if (
                booking.status == "PENDING"
                and booking.expires_at is not None
                and booking.expires_at <= timezone.now()
            ):
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
                return JsonResponse(
                    {"error": "El intervalo de fechas no es válido."},
                    status=400,
                )

            if guest_count < 1:
                return JsonResponse(
                    {"error": "El número de huéspedes no es válido."},
                    status=400,
                )

            if guest_count > property.adults + property.children:
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

            if not availability:
                return JsonResponse(
                    {"error": "El intervalo de fechas no es válido."},
                    status=400,
                )

            if any(
                item["status"] != "OPEN"
                for item in availability
            ):
                return JsonResponse(
                    {"error": "Hay noches que ya no están disponibles."},
                    status=409,
                )

            minimum_nights = availability[0]["min_nights"]
            number_of_nights = (final_date - initial_date).days

            if number_of_nights < minimum_nights:
                return JsonResponse(
                    {
                        "error": (
                            "La estancia es inferior al mínimo requerido."
                        )
                    },
                    status=400,
                )

            # Comprobar que la propuesta tiene un snapshot válido.
            if (
                not proposal.proposed_nightly_prices
                or proposal.proposed_total_price is None
            ):
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

            if (
                not proposal.proposed_nightly_prices
                or proposal.proposed_total_price is None
            ):
                return JsonResponse(
                    {"error": "The proposal has no valid price snapshot."},
                    status=409,
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
                return JsonResponse(
                    {
                        "error": (
                            "The nightly prices have changed since the proposal "
                            "was created. A new proposal is required."
                        )
                    },
                    status=409,
                )
            
            # Evitar aceptar si cambió cualquier tarifa nocturna,
            # aunque el total resultante fuese el mismo.
            if (
                current_nightly_prices != proposed_nightly_prices
                or current_total_price != proposed_total_price
            ):
                return JsonResponse(
                    {
                        "error": (
                            "El precio de la propuesta ha cambiado. "
                            "Debe crearse una nueva propuesta."
                        ),
                        "proposed_total_price": str(
                            proposed_total_price
                        ),
                        "current_total_price": str(
                            current_total_price
                        ),
                    },
                    status=409,
                )

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

    except ValidationError as exc:
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
        return JsonResponse(
            {
                "error": (
                    "No se puede aceptar la propuesta porque "
                    "existe un conflicto con la disponibilidad."
                )
            },
            status=409,
        )

    return JsonResponse(
        {
            "id": proposal.pk,
            "status": proposal.status,
            "booking_id": booking.pk,
            "initial_date": booking.initial_date.isoformat(),
            "final_date": booking.final_date.isoformat(),
            "guest_count": booking.guest_count,
            "total_price": str(booking.total_price),
            "proposed_total_price": str(
                proposal.proposed_total_price
            ),
        },
        status=200,
    )

@login_required
def reject_booking_change_proposal(request, proposal_id):
    if request.method != "POST":
        return JsonResponse(
            {"error": "Método no permitido."},
            status=405,
        )

    proposal = get_object_or_404(
        BookingChangeProposal.objects.select_related("booking"),
        pk=proposal_id,
    )

    if proposal.booking.tenant != request.user:
        raise PermissionDenied

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

        if booking.tenant != request.user:
            raise PermissionDenied

        if proposal.status != BookingChangeProposal.Status.PENDING:
            return JsonResponse(
                {"error": "La propuesta ya no está pendiente."},
                status=409,
            )

        if proposal.is_expired():
            proposal.status = BookingChangeProposal.Status.EXPIRED
            proposal.save(update_fields=["status"])

            return JsonResponse(
                {"error": "La propuesta ha caducado."},
                status=409,
            )

        proposal.status = BookingChangeProposal.Status.REJECTED
        proposal.save(update_fields=["status"])

        return JsonResponse(
            {
                "id": proposal.pk,
                "status": proposal.status,
            },
            status=200,
        )

PENDING_BOOKING_MINUTES = 15

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
        expires_at = timezone.now() + timedelta(
            minutes=PENDING_BOOKING_MINUTES
        )

        booking = Booking.create_pending(
            tenant=tenant,
            property=property,
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
        )

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
    
    return JsonResponse(
        {
            "success": True,
            "message": "Reserva pendiente.",
            "booking_id": booking.pk,
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