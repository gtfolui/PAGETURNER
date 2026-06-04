from django.contrib import admin
from django.utils import timezone

from .models import (
    Activity,
    Book,
    BuddyRead,
    BuddyReadMessage,
    DailyActivity,
    FriendRequest,
    Friendship,
    Notification,
    ReadingChallenge,
    Report,
    UserBook,
)


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ("title", "author", "genre", "year", "avg_rating", "pages", "source")
    list_filter = ("genre", "source", "year")
    search_fields = ("title", "author", "isbn", "external_id")
    readonly_fields = ("avg_rating", "created_at")


@admin.register(UserBook)
class UserBookAdmin(admin.ModelAdmin):
    list_display = ("user", "book", "shelf", "rating", "progress", "updated_at")
    list_filter = ("shelf",)
    search_fields = ("user__username", "book__title")


@admin.register(FriendRequest)
class FriendRequestAdmin(admin.ModelAdmin):
    list_display = ("sender", "receiver", "status", "created_at", "responded_at")
    list_filter = ("status",)
    search_fields = ("sender__username", "receiver__username")


@admin.register(Friendship)
class FriendshipAdmin(admin.ModelAdmin):
    list_display = ("user", "friend", "created_at")
    search_fields = ("user__username", "friend__username")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "text", "is_read", "created_at")
    list_filter = ("is_read",)
    search_fields = ("user__username", "text")


@admin.register(ReadingChallenge)
class ReadingChallengeAdmin(admin.ModelAdmin):
    list_display = ("user", "year", "goal")
    list_filter = ("year",)


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ("user", "action", "book", "stars", "created_at")
    list_filter = ("action",)
    search_fields = ("user__username", "book__title")


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("created_at", "reporter", "target_type", "target_id", "reason", "status")
    list_filter = ("status", "reason", "target_type")
    search_fields = ("reporter__username", "detail")
    actions = ("mark_resolved", "mark_dismissed")

    def mark_resolved(self, request, queryset):
        queryset.update(status="resolved", resolved_at=timezone.now(), resolved_by=request.user)
    mark_resolved.short_description = "Mark selected as resolved"

    def mark_dismissed(self, request, queryset):
        queryset.update(status="dismissed", resolved_at=timezone.now(), resolved_by=request.user)
    mark_dismissed.short_description = "Mark selected as dismissed"


@admin.register(BuddyRead)
class BuddyReadAdmin(admin.ModelAdmin):
    list_display = ("book", "initiator", "partner", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("book__title", "initiator__username", "partner__username")


@admin.register(BuddyReadMessage)
class BuddyReadMessageAdmin(admin.ModelAdmin):
    list_display = ("buddy_read", "author", "page_marker", "created_at")
    search_fields = ("author__username", "text")


@admin.register(DailyActivity)
class DailyActivityAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "actions")
    list_filter = ("date",)
    search_fields = ("user__username",)
