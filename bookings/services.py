import hashlib
import secrets
from django.contrib.auth import get_user_model
from django.db import transaction

from bookings.models import OwnerProfile

def generate_proposal_access_token():
    """Return a secure raw token and its SHA-256 hash."""
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    return raw_token, token_hash


def hash_proposal_access_token(raw_token):
    """Return the SHA-256 hash for a supplied access token."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

class OwnerRequestError(Exception):
    """Error de negocio al gestionar solicitudes de propietario."""


@transaction.atomic
def request_owner_status(user):
    """Crea o vuelve a enviar una solicitud de propietario."""

    if not user.is_authenticated:
        raise OwnerRequestError(
            "Debes iniciar sesión para solicitar ser propietario."
        )

    User = get_user_model()
    locked_user = User.objects.select_for_update().get(pk=user.pk)

    try:
        profile = OwnerProfile.objects.select_for_update().get(
            user=locked_user
        )
    except OwnerProfile.DoesNotExist:
        return OwnerProfile.objects.create(
            user=locked_user,
            status="PENDING",
        )

    if profile.status == "APPROVED":
        raise OwnerRequestError(
            "Tu cuenta ya tiene permisos de propietario."
        )

    if profile.status == "PENDING":
        raise OwnerRequestError(
            "Ya tienes una solicitud pendiente de revisión."
        )

    if profile.status not in {"REJECTED", "REVOKED"}:
        raise OwnerRequestError(
            "No se puede crear una solicitud con el estado actual."
        )

    profile.status = "PENDING"
    profile.reviewed_at = None
    profile.save(update_fields=["status", "reviewed_at"])

    return profile