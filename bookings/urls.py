from django.urls import path
from . import views

urlpatterns = [
    path("", views.index, name='index'),
    path("login", views.login_view, name="login"),
    path("logout", views.logout_view, name="logout"),
    path("register", views.register, name="register"),
    path("property/<int:property_id>", views.property, name="property"),
    #API ROUTES
    path("properties/", views.properties, name="properties"),
    path("booking/<int:property_id>/", views.booking, name="booking")
]