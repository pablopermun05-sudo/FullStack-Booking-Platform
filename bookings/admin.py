from django.contrib import admin
from django.utils import timezone

from .models import OwnerProfile, User, Property, Booking


@admin.register(OwnerProfile)
class OwnerProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "status",
        "created_at",
        "reviewed_at",
    )
    list_filter = ("status",)
    search_fields = (
        "user__username",
        "user__email",
        "user__first_name",
        "user__last_name",
    )
    actions = (
        "approve_owners",
        "reject_owners",
    )

    @admin.action(description="Aprobar propietarios seleccionados")
    def approve_owners(self, request, queryset):
        queryset.update(
            status="APPROVED",
            reviewed_at=timezone.now(),
        )

    @admin.action(description="Rechazar propietarios seleccionados")
    def reject_owners(self, request, queryset):
        queryset.update(
            status="REJECTED",
            reviewed_at=timezone.now(),
        )


admin.site.register(User)
admin.site.register(Property)
admin.site.register(Booking)