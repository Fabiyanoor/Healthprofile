from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from accounts.authentication import CookieJWTAuthentication

from .models import EmergencyContact, HealthProfile
from .serializers import EmergencyContactSerializer, ProfileSerializer


class UserOnlyMixin:
    """Every view here accepts user JWT cookies only. Admin sessions are not accepted."""

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]


class ProfileMeView(UserOnlyMixin, generics.RetrieveUpdateAPIView):
    serializer_class = ProfileSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        # The profile comes from the logged-in user, never from an id in the URL
        return get_object_or_404(
            HealthProfile.objects.select_related("user").prefetch_related("contacts"),
            user=self.request.user,
        )


class ContactListCreateView(UserOnlyMixin, generics.ListCreateAPIView):
    serializer_class = EmergencyContactSerializer
    pagination_class = None  # a profile has at most 3 contacts

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return EmergencyContact.objects.none()
        return EmergencyContact.objects.filter(profile__user=self.request.user)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if not getattr(self, "swagger_fake_view", False):
            context["profile"] = get_object_or_404(HealthProfile, user=self.request.user)
        return context


class ContactDetailView(UserOnlyMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = EmergencyContactSerializer
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        # Another user's contact is simply "not found" (404)
        if getattr(self, "swagger_fake_view", False):
            return EmergencyContact.objects.none()
        return EmergencyContact.objects.filter(profile__user=self.request.user)