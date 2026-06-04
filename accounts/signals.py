import random

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UserProfile


# Curated palette so avatars look pleasant
_PALETTE = [
    ("#C4922A", "#8B3E2A"),
    ("#3A5A8A", "#2D3A4A"),
    ("#4A6741", "#2D4A2D"),
    ("#5A3A5A", "#3A2D4A"),
    ("#6B4C35", "#4A3D2D"),
    ("#8B3E2A", "#4A2D35"),
    ("#3A5A5A", "#2D4A3E"),
    ("#5A5A3A", "#4A4A2D"),
]


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        a, b = random.choice(_PALETTE)
        UserProfile.objects.create(user=instance, avatar_color_a=a, avatar_color_b=b)
