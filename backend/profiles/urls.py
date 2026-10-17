from django.urls import path

from . import views

urlpatterns = [
    path("me/", views.ProfileMeView.as_view(), name="profile-me"),
    path("me/contacts/", views.ContactListCreateView.as_view(), name="contact-list"),
    path("me/contacts/<int:pk>/", views.ContactDetailView.as_view(), name="contact-detail"),
]