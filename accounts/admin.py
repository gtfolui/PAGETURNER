from django.contrib import admin

from .models import UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "is_email_verified", "location", "created_at")
    list_filter = ("is_email_verified",)
    search_fields = ("user__username", "user__email", "location")
    readonly_fields = ("email_verification_token", "email_verification_sent_at", "created_at")
