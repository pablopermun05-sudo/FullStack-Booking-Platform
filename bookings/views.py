from django.shortcuts import render
from django.urls import reverse
from django.http import HttpResponse, HttpResponseRedirect
from django.contrib.auth import authenticate, login, logout
from django.views.decorators.csrf import csrf_exempt
from django.db import IntegrityError
from .models import User, Property, Booking
from django import forms
from django.forms import ModelForm
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.forms import AuthenticationForm
from django.http import JsonResponse
from datetime import date
from django.core.paginator import Paginator
from django.contrib.auth.decorators import login_required
import json
from django.core.exceptions import ValidationError
from django.core.exceptions import PermissionDenied

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
    property = Property.objects.get(pk=property_id)
    # Filter bookings that end today or in the future
    active_bookings = property.bookings.filter(final_date__gte=date.today()).order_by('initial_date')

    return render(request, "bookings/property.html", {
        "property": property,
        "active_bookings": active_bookings
    })

@login_required
def my_properties(request):
    properties = Property.objects.filter(owner=request.user)
    
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
        fields = ("title", "description", "location", "image", "price_per_night", "children", "adults", "rooms", "allow_pets")

@login_required
def manage_property(request, property_id=None):
    if property_id is None:
        property = None
        form = PropertyForm()
    else :
        property = Property.objects.get(pk=property_id)
        if property.owner != request.user:
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
def delete_booking(request, booking_id):
    if request.method == "POST":
        booking = Booking.objects.get(pk=booking_id)
        if booking.tenant != request.user:
            raise PermissionDenied
        else:
            booking.delete()
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

    if initial_date or final_date:
        if not initial_date or not final_date:
             return JsonResponse({"error": "Ambas fechas deben ser seleccionadas."}, status=400)

        # Convert dates from String into actual dates
        initial_date = date.fromisoformat(initial_date)
        final_date = date.fromisoformat(final_date)

        if initial_date >= final_date:
            return JsonResponse({"error": "La fecha de salida debe ser posterior a la de entrada."}, status=400)
        elif initial_date < date.today():
            return JsonResponse({"error": "La fecha de entrada no puede ser anterior al día de hoy."}, status=400)

        # Using "__" to filter data across related models.
        # Using "distinct" to prevent from duplicated properties when join
        properties = properties.exclude(
            bookings__initial_date__lt=final_date,
            bookings__final_date__gt=initial_date
        ).distinct()
    
    if adults:
        try:
            adults = int(adults)
            if adults < 1:
                return JsonResponse({"error": "El número de adultos tiene que ser mayor que 0."}, status=400)
            properties = properties.filter(adults__gte=adults)
        except:
            return JsonResponse({"error": "Introduce un número válido para indicar el número de adultos."}, status=400)

    if children:
        try:
            children = int(children)
            if children < 0:
                return JsonResponse({"error": "El número de niños tiene que ser mayor o igual a 0."}, status=400)
            properties = properties.filter(children__gte=children)
        except:
            return JsonResponse({"error": "Introduce un número válido para indicar el número de niños."}, status=400)

    if rooms:
        try:
            rooms = int(rooms)
            if rooms < 1:
                return JsonResponse({"error": "El número de habitaciones tiene que ser mayor que 0."}, status=400)
            properties = properties.filter(rooms__gte=rooms)
        except:
            return JsonResponse({"error": "Introduce un número válido para indicar el número de habitaciones."}, status=400)
    
    if pets:
        properties = properties.filter(allow_pets=True)

    properties = properties.order_by("id")
    paginator = Paginator(properties, 6)
    page_number = request.GET.get('page')

    try:
        page_properties = paginator.page(page_number)
        properties = list(page_properties.object_list.values())
    except:
        # If page doesn`t exist, return empty list
        properties = []

    return JsonResponse(properties, safe=False)

@login_required
def booking(request, property_id):
    initial_date = request.GET.get('start')
    final_date = request.GET.get('end')

    if not initial_date or not final_date:
            return JsonResponse({"error": "Ambas fechas deben ser seleccionadas."}, status=400)

    try:
        # Convert dates from String into actual dates
        initial_date = date.fromisoformat(initial_date)
        final_date = date.fromisoformat(final_date)

        if initial_date >= final_date:
            return JsonResponse({"error": "La fecha de salida debe ser posterior a la de entrada."}, status=400)
        elif initial_date < date.today():
            return JsonResponse({"error": "La fecha de entrada no puede ser anterior al día de hoy."}, status=400)
        else:
            # Check for any overlapping bookings in the database
            is_occupied = Booking.objects.filter(
                property_id=property_id,
                initial_date__lt=final_date,
                final_date__gt=initial_date
            ).exists()

            if is_occupied:
                return JsonResponse({"error": "El alojamiento ya está reservado en esas fechas."}, status=400)

            return JsonResponse({
                "available": True
            })
        
    except ValueError:
        return JsonResponse({"error": "Formato de fecha inválido."}, status=400)

@login_required
def confirm_booking(request, property_id):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            
            initial_date = date.fromisoformat(data.get('start'))
            final_date = date.fromisoformat(data.get('end'))

            booking = Booking(
                property_id=property_id,
                tenant=request.user,
                initial_date=initial_date,
                final_date=final_date
            )

            try:
                # Execute clean() method to control booking restrictions
                booking.full_clean() 
                booking.save()
                return JsonResponse({"success": True})
            except ValidationError as e:
                print(e.message_dict)
                return JsonResponse({"error": e.message_dict}, status=400)
            
        except json.JSONDecodeError:
            print("ERROR:", e)
            return JsonResponse({"error": "JSON inválido"}, status=400)

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
    logout(request)
    return HttpResponseRedirect(reverse("index"))

class RegisterForm(UserCreationForm):
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
    if request.user.is_authenticated and request.resolver_match.url_name == 'register':
        return HttpResponseRedirect(reverse("edit_profile"))

    # If an unauthenticated user tries to access the edit profile URL, redirect them to login
    if not request.user.is_authenticated and request.resolver_match.url_name == 'edit_profile':
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