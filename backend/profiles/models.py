from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, RegexValidator
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

MAX_IMAGE_BYTES = 2 * 1024 * 1024  # 2 MB
MAX_EMERGENCY_CONTACTS = 3

phone_validator = RegexValidator(
    regex=r"^\+?[0-9]{7,15}$",
    message="Enter a valid phone number: 7 to 15 digits, optional leading +.",
)


def validate_not_future(value):
    if value > timezone.localdate():
        raise ValidationError("Date of birth cannot be in the future.")


def validate_image_size(image):
    if image.size > MAX_IMAGE_BYTES:
        raise ValidationError("Image must be 2 MB or smaller.")


class HealthProfile(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        DEACTIVATED = "deactivated", "Deactivated"

    class ContactPreference(models.TextChoices):
        EMAIL = "email", "Email"
        PHONE = "phone", "Phone"
        NONE = "none", "No contact"

    class AgeRange(models.TextChoices):
        AGE_18_24 = "18-24", "18 to 24"
        AGE_25_34 = "25-34", "25 to 34"
        AGE_35_44 = "35-44", "35 to 44"
        AGE_45_54 = "45-54", "45 to 54"
        AGE_55_64 = "55-64", "55 to 64"
        AGE_65_PLUS = "65+", "65 and over"

    # One profile per user. Deleting the user deletes the profile.
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    full_name = models.CharField(max_length=150)
    date_of_birth = models.DateField(null=True, blank=True, validators=[validate_not_future])
    age_range = models.CharField(max_length=10, choices=AgeRange.choices, blank=True)
    phone = models.CharField(max_length=16, blank=True, validators=[phone_validator])
    contact_preference = models.CharField(
        max_length=10,
        choices=ContactPreference.choices,
        default=ContactPreference.EMAIL,
    )
    # Only the file path is stored in the database, never the image itself.
    profile_picture = models.ImageField(
        upload_to="profile_pictures/",
        null=True,
        blank=True,
        validators=[
            FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png"]),
            validate_image_size,
        ],
    )
    wellness_goals = models.TextField(blank=True)
    allergies = models.TextField(blank=True)
    lifestyle_notes = models.TextField(blank=True)
    consent_accepted_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    deactivated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            # Admin list: filter by status, newest first, with no extra sorting
            models.Index(fields=["status", "-created_at"], name="profile_status_created_idx"),
        ]
        constraints = [
            # Date of birth or age range, never both
            models.CheckConstraint(
                condition=Q(date_of_birth__isnull=True) | Q(age_range=""),
                name="profile_dob_or_age_range",
            ),
            # Phone number is required when the contact preference is phone
            models.CheckConstraint(
                condition=~Q(contact_preference="phone") | ~Q(phone=""),
                name="profile_phone_required_if_preferred",
            ),
            # status and deactivated_at must agree
            models.CheckConstraint(
                condition=(
                    Q(status="active", deactivated_at__isnull=True)
                    | Q(status="deactivated", deactivated_at__isnull=False)
                ),
                name="profile_status_matches_deactivated_at",
            ),
        ]

    def clean(self):
        """Friendly error messages. The database constraints above are the safety net."""
        errors = {}
        if self.date_of_birth and self.age_range:
            errors["age_range"] = "Provide either a date of birth or an age range, not both."
        if self.contact_preference == self.ContactPreference.PHONE and not self.phone:
            errors["phone"] = "A phone number is required when the contact preference is phone."
        if errors:
            raise ValidationError(errors)

    @transaction.atomic
    def deactivate(self):
        """Admin deactivation: profile is marked, time recorded, and the user can no longer log in."""
        self.status = self.Status.DEACTIVATED
        self.deactivated_at = timezone.now()
        self.save(update_fields=["status", "deactivated_at", "updated_at"])
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

    def __str__(self):
        return f"Profile of {self.user.email}"


class EmergencyContact(models.Model):
    # Many contacts per profile. Deleting the profile deletes its contacts.
    # Django automatically indexes this foreign key.
    profile = models.ForeignKey(
        HealthProfile,
        on_delete=models.CASCADE,
        related_name="contacts",
    )
    name = models.CharField(max_length=150)
    relationship = models.CharField(max_length=50)
    phone = models.CharField(max_length=16, validators=[phone_validator])
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_primary", "created_at", "id"]
        constraints = [
            # At most one primary contact per profile, enforced by the database
            models.UniqueConstraint(
                fields=["profile"],
                condition=Q(is_primary=True),
                name="one_primary_contact_per_profile",
            ),
        ]

    def clean(self):
        """Friendly error message for forms and serializers."""
        if self._state.adding and self.profile_id:
            count = EmergencyContact.objects.filter(profile_id=self.profile_id).count()
            if count >= MAX_EMERGENCY_CONTACTS:
                raise ValidationError(
                    f"A profile can have at most {MAX_EMERGENCY_CONTACTS} emergency contacts."
                )

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self._state.adding:
                existing = EmergencyContact.objects.filter(profile_id=self.profile_id)
                # Safety net: the limit holds even if code skips clean()
                if existing.count() >= MAX_EMERGENCY_CONTACTS:
                    raise ValidationError(
                        f"A profile can have at most {MAX_EMERGENCY_CONTACTS} emergency contacts."
                    )
                # The first contact becomes primary automatically
                if not existing.exists():
                    self.is_primary = True
            if self.is_primary:
                # Only one primary: demote any other before saving this one
                EmergencyContact.objects.filter(
                    profile_id=self.profile_id, is_primary=True
                ).exclude(pk=self.pk).update(is_primary=False)
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        profile_id = self.profile_id
        was_primary = self.is_primary
        with transaction.atomic():
            result = super().delete(*args, **kwargs)
            if was_primary:
                # Promote the oldest remaining contact so the profile keeps a primary
                nxt = EmergencyContact.objects.filter(profile_id=profile_id).order_by(
                    "created_at", "id"
                ).first()
                if nxt:
                    nxt.is_primary = True
                    nxt.save(update_fields=["is_primary"])
        return result

    def __str__(self):
        return f"{self.name} ({self.relationship})"