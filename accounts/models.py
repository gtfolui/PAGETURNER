import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


def _initials_from_name(full_name: str, fallback: str = "") -> str:
    parts = [p for p in (full_name or "").split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (fallback[:2] or "U").upper()


def _gen_token() -> str:
    return secrets.token_urlsafe(32)


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    bio = models.CharField(max_length=200, blank=True, default="")
    location = models.CharField(max_length=100, blank=True, default="")
    picture = models.ImageField(upload_to="avatars/", blank=True, null=True)
    # Stored colour pair so each user has a stable avatar gradient
    avatar_color_a = models.CharField(max_length=7, default="#C4922A")
    avatar_color_b = models.CharField(max_length=7, default="#8B3E2A")

    # Email verification (required to send friend requests, post reviews, etc.
    # when settings.REQUIRE_EMAIL_VERIFICATION is True).
    is_email_verified = models.BooleanField(default=False)
    email_verification_token = models.CharField(max_length=64, blank=True, default=_gen_token)
    email_verification_sent_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Profile<{self.user.username}>"

    @property
    def initials(self) -> str:
        full = (self.user.get_full_name() or self.user.username).strip()
        return _initials_from_name(full, fallback=self.user.username)

    @property
    def display_name(self) -> str:
        return self.user.get_full_name() or self.user.username

    @property
    def joined_year(self) -> int:
        return self.user.date_joined.year

    def rotate_verification_token(self):
        self.email_verification_token = _gen_token()
        self.email_verification_sent_at = timezone.now()
        self.save(update_fields=["email_verification_token", "email_verification_sent_at"])
        return self.email_verification_token
