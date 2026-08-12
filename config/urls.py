"""Top-level URL routing for the Shiftly CRM."""

from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    # Django admin is useful for support and initial data management.
    path("admin/", admin.site.urls),
    path("shifts/", include("shifts.urls")),
    # Account routes own the landing page, login, and organisation registration.
    path("", include("accounts.urls")),
]