from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User


class SignUpForm(UserCreationForm):
    first_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={"placeholder": "First name", "autocomplete": "given-name"}),
    )
    last_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={"placeholder": "Last name", "autocomplete": "family-name"}),
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={"placeholder": "you@example.com", "autocomplete": "email"}),
    )

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email", "password1", "password2")
        widgets = {
            "username": forms.TextInput(attrs={"placeholder": "Pick a username", "autocomplete": "username"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].widget.attrs.update(
            {"placeholder": "Choose a strong password", "autocomplete": "new-password"}
        )
        self.fields["password2"].widget.attrs.update(
            {"placeholder": "Confirm your password", "autocomplete": "new-password"}
        )
        # Strip Django's default help_text noise — we show our own clean copy
        for f in self.fields.values():
            f.help_text = ""

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with that email already exists.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        if commit:
            user.save()
        return user


class LoginForm(forms.Form):
    username = forms.CharField(
        widget=forms.TextInput(attrs={"placeholder": "Username", "autocomplete": "username"}),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "Password", "autocomplete": "current-password"}),
    )


class ProfileEditForm(forms.ModelForm):
    """Edit profile fields including the optional avatar picture."""

    first_name = forms.CharField(max_length=30, required=False)
    last_name = forms.CharField(max_length=30, required=False)
    email = forms.EmailField(required=False)

    class Meta:
        from .models import UserProfile  # local import avoids circular ref
        model = UserProfile
        fields = ("picture", "bio", "location")
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 3, "placeholder": "Tell us about yourself"}),
            "location": forms.TextInput(attrs={"placeholder": "City, Country"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._user = user
        if user:
            self.fields["first_name"].initial = user.first_name
            self.fields["last_name"].initial = user.last_name
            self.fields["email"].initial = user.email

    def save(self, commit=True):
        profile = super().save(commit=False)
        if self._user:
            self._user.first_name = self.cleaned_data.get("first_name", "")
            self._user.last_name = self.cleaned_data.get("last_name", "")
            new_email = (self.cleaned_data.get("email") or "").strip().lower()
            if new_email and new_email != self._user.email.lower():
                self._user.email = new_email
            if commit:
                self._user.save()
        if commit:
            profile.save()
        return profile
