from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

urlpatterns = [
    path("auth/", include("accounts.urls")),
    path("profiles/", include("profiles.urls")),
]

# Development only: serve uploaded pictures
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)