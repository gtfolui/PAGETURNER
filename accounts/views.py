from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import LoginForm, SignUpForm


def _send_verification_email(request, user):
    """Send (or print, in dev) the verification link."""
    profile = user.profile
    profile.rotate_verification_token()
    verify_url = request.build_absolute_uri(
        reverse("accounts:verify_email", args=[profile.email_verification_token])
    )
    send_mail(
        subject="Verify your PageTurner account",
        message=(
            f"Hi {user.first_name or user.username},\n\n"
            f"Welcome to PageTurner. Please confirm your email by opening this link:\n\n"
            f"{verify_url}\n\n"
            f"If you did not sign up, ignore this message.\n"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email] if user.email else [],
        fail_silently=True,
    )
    return verify_url


def login_view(request):
    if request.user.is_authenticated:
        return redirect("books:home")

    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = authenticate(
            request,
            username=form.cleaned_data["username"],
            password=form.cleaned_data["password"],
        )
        if user is not None:
            # Fixed: explicitly added the authentication backend path
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            next_url = request.GET.get("next") or reverse("books:home")
            return redirect(next_url)
        messages.error(request, "Invalid username or password.")

    return render(request, "accounts/login.html", {"form": form})


def signup_view(request):
    if request.user.is_authenticated:
        return redirect("books:home")

    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        _send_verification_email(request, user)
        # Fixed: explicitly added the authentication backend path
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        if settings.REQUIRE_EMAIL_VERIFICATION:
            messages.info(
                request,
                "Account created. Check your email to verify and unlock social features.",
            )
        else:
            messages.success(request, f"Welcome to PageTurner, {user.first_name}!")
        return redirect("books:home")

    return render(request, "accounts/signup.html", {"form": form})


@login_required
def logout_view(request):
    logout(request)
    messages.info(request, "You've been signed out.")
    return redirect("accounts:login")


def verify_email(request, token):
    """Public link clicked from the verification email."""
    from .models import UserProfile  # local import avoids circular reference

    profile = get_object_or_404(UserProfile, email_verification_token=token)
    if not profile.is_email_verified:
        profile.is_email_verified = True
        profile.save(update_fields=["is_email_verified"])
        messages.success(request, "Email verified. You can now use all features.")
    else:
        messages.info(request, "Email already verified.")
    return redirect("books:home" if request.user.is_authenticated else "accounts:login")


@login_required
def resend_verification(request):
    if request.user.profile.is_email_verified:
        messages.info(request, "Your email is already verified.")
        return redirect("books:home")
    _send_verification_email(request, request.user)
    messages.success(request, "Verification email sent. Please check your inbox.")
    return redirect("books:home")


@login_required
def profile_edit(request):
    from .forms import ProfileEditForm
    profile = request.user.profile
    if request.method == "POST":
        form = ProfileEditForm(request.POST, request.FILES, instance=profile, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated.")
            return redirect("books:profile")
    else:
        form = ProfileEditForm(instance=profile, user=request.user)
    return render(request, "accounts/profile_edit.html", {"form": form})