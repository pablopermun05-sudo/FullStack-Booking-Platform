from django.urls import path
from . import views

urlpatterns = [
    path("", views.index, name='index'),
    path("login", views.login_view, name="login"),
    path("logout", views.logout_view, name="logout"),
    path("register", views.manage_profile, name="register"),
    path("profile/edit", views.manage_profile, name="edit_profile"),
    path("property/<int:property_id>", views.property, name="property"),
    path("property/create", views.manage_property, name="create_property"),
    path("property/edit/<int:property_id>", views.manage_property, name="edit_property"),
    path("booking/cancel/<int:booking_id>/", views.cancel_booking, name="cancel_booking"),
    path("my_properties", views.my_properties, name="my_properties"),
    path("my_bookings", views.my_bookings, name="my_bookings"),
    path("property/<int:property_id>/availability", views.property_availability, name="property_availability"),
    path("property/<int:property_id>/availability/reset", views.property_availability_reset, name="property_availability_reset",),
    path("property/<int:property_id>/availability/data", views.property_availability_data, name="property_availability_data",),
    path("property/<int:property_id>/availability/save", views.property_availability_save, name="property_availability_save",),
    #API ROUTES
    path("properties/", views.properties, name="properties"),
    path("booking/<int:property_id>/", views.booking, name="booking"),
    path("confirm_booking/<int:property_id>", views.create_booking, name="confirm_booking"),
    path("booking/<int:booking_id>/propose-change", views.propose_booking_change, name="propose_booking_change"),
    path("booking-change-proposal/<int:proposal_id>/reject", views.reject_booking_change_proposal, name="reject_booking_change_proposal"),
    path("booking-change-proposal/<int:proposal_id>/accept", views.accept_booking_change_proposal, name="accept_booking_change_proposal"),
    path("booking/<int:booking_id>/admin-force-change", views.admin_force_booking_change, name="admin_force_booking_change"),
    path("booking-change-proposal/access/<str:token>", views.view_booking_change_proposal_by_token, name="view_booking_change_proposal_by_token"),
    path("booking/<int:property_id>/details", views.booking_details, name="booking_details"),
    path("booking/<int:property_id>/hold", views.create_booking_hold, name="create_booking_hold"),
    path("booking/<int:property_id>/hold/release", views.release_booking_hold, name="release_booking_hold"),
    path("booking/<int:booking_id>/payment", views.mock_payment, name="mock_payment"),
]