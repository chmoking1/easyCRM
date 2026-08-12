from django.contrib import admin
from .models import Employee, Organization


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "created_at")
    search_fields = ("name", "owner__username")


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = (
        "full_name",
        "organization",
        "position",
        "hourly_rate",
        "sales_percentage",
        "can_edit_schedule",
        "is_active",
    )
    list_filter = ("organization", "is_active", "can_edit_schedule")
    search_fields = ("first_name", "last_name", "phone", "email", "telegram_username")