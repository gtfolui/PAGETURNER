from .models import Notification


def global_context(request):
    ctx = {}
    if request.user.is_authenticated:
        ctx["unread_notif_count"] = Notification.objects.filter(
            user=request.user, is_read=False
        ).count()
        # Profile is auto-created via signal; fall back gracefully
        ctx["user_profile"] = getattr(request.user, "profile", None)
    return ctx
