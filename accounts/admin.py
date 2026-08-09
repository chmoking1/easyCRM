"""Admin configuration for the earliest organisation model."""

from django.contrib import admin
from .models import Employee, Organization


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    """Show the most useful organisation fields in Django's built-in admin."""

    list_display = ("name", "owner", "created_at")
    search_fields = ("name", "owner__username", "owner__email")


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    """Make employee data searchable and readable for support work in Django admin."""

    list_display = ("full_name", "organization", "position", "hourly_rate", "sales_percentage", "is_active")
    list_filter = ("organization", "is_active")
    search_fields = ("first_name", "last_name", "phone", "email", "telegram_username", "position")
