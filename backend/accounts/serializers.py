from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework import serializers

from profiles.models import HealthProfile

User = get_user_model()


class SignupSerializer(serializers.Serializer):
    # No "role" field: extra fields are ignored, so nobody can sign up as admin
    name = serializers.CharField(max_length=150)
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        max_length=128,
        style={"input_type": "password"},
    )

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate(self, attrs):
        candidate = User(email=attrs["email"], name=attrs["name"])
        try:
            validate_password(attrs["password"], user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)})
        return attrs

    def create(self, validated_data):
        try:
            # User and profile are created together or not at all
            with transaction.atomic():
                user = User.objects.create_user(
                    email=validated_data["email"],
                    name=validated_data["name"],
                    password=validated_data["password"],
                )
                HealthProfile.objects.create(user=user, full_name=validated_data["name"])
        except IntegrityError:
            # Two signups with the same email at the same moment: the database wins
            raise serializers.ValidationError(
                {"email": ["An account with this email already exists."]}
            )
        return user


class LoginSerializer(serializers.Serializer):
    # Plain CharField on purpose: a bad email format gets the same generic error as a wrong password
    email = serializers.CharField(max_length=254)
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)


class UserPublicSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "email", "name", "role")
        read_only_fields = fields