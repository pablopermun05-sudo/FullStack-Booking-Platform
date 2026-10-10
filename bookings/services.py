import hashlib
import secrets


def generate_proposal_access_token():
    """Return a secure raw token and its SHA-256 hash."""
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    return raw_token, token_hash


def hash_proposal_access_token(raw_token):
    """Return the SHA-256 hash for a supplied access token."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
