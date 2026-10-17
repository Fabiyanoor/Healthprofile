from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import serializers

from .models import EmergencyContact, HealthProfile


class EmergencyContactSerializer(serializers.ModelSerializer):
    # "profile" is not a field, so a request can never move a contact to another profile.
    class Meta:
        model = EmergencyContact
        fields = ("id", "name", "relationship", "phone", "is_primary", "created_at")
        read_only_fields = ("id", "created_at")

    def validate(self, attrs):
        # A profile with contacts must always keep one primary
        if self.instance and self.instance.is_primary and attrs.get("is_primary") is False:
            raise serializers.ValidationError(
                {"is_primary": "Choose another contact as primary instead of unsetting this one."}
            )
        return attrs

    def create(self, validated_data):
        contact = EmergencyContact(profile=self.context["profile"], **validated_data)
        try:
            contact.clean()  # friendly "max 3" message
            contact.save()  # save() repeats the check as a safety net
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"non_field_errors": exc.messages})
        return contact


class ProfileSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)
    contacts = EmergencyContactSerializer(many=True, read_only=True)
    # Send true to record consent. The timestamp is set once and cannot be edited directly.
    consent = serializers.BooleanField(write_only=True, required=False)

    class Meta:
        model = HealthProfile
        fields = (
            "id",
            "email",
            "full_name",
            "date_of_birth",
            "age_range",
            "phone",
            "contact_preference",
            "profile_picture",
            "wellness_goals",
            "allergies",
            "lifestyle_notes",
            "consent",
            "consent_accepted_at",
            "status",
            "contacts",
            "created_at",
            "updated_at",
        )
        # Only the fields listed above can be written. status, user and timestamps are read-only,
        # so a request cannot change them (mass assignment protection).
        read_only_fields = ("id", "consent_accepted_at", "status", "created_at", "updated_at")
        extra_kwargs = {
            "wellness_goals": {"max_length": 2000},
            "allergies": {"max_length": 2000},
            "lifestyle_notes": {"max_length": 2000},
        }

    def validate_date_of_birth(self, value):
        if value is not None and value.year < 1900:
            raise serializers.ValidationError("Enter a realistic date of birth.")
        return value

    def _merged(self, attrs, name):
        """Value after this request: the new one if sent, otherwise the stored one."""
        if name in attrs:
            return attrs[name]
        return getattr(self.instance, name, None) if self.instance else None

    def validate(self, attrs):
        # PATCH may send only one field, so the rules must also look at stored values
        dob = self._merged(attrs, "date_of_birth")
        age_range = self._merged(attrs, "age_range") or ""
        preference = self._merged(attrs, "contact_preference")
        phone = self._merged(attrs, "phone") or ""
        errors = {}
        if dob and age_range:
            errors["age_range"] = "Provide either a date of birth or an age range, not both."
        if preference == HealthProfile.ContactPreference.PHONE and not phone:
            errors["phone"] = "A phone number is required when the contact preference is phone."
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def update(self, instance, validated_data):
        consent = validated_data.pop("consent", None)
        if consent and instance.consent_accepted_at is None:
            instance.consent_accepted_at = timezone.now()

        old_picture = instance.profile_picture.name if instance.profile_picture else None
        instance = super().update(instance, validated_data)

        # Remove the replaced or cleared picture file so files do not pile up
        if "profile_picture" in validated_data and old_picture:
            new_picture = instance.profile_picture.name if instance.profile_picture else None
            if new_picture != old_picture:
                instance.profile_picture.storage.delete(old_picture)
        return instance