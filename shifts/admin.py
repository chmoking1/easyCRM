from django.contrib import admin
from .models import Notification, Shift, ShiftSchedule


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ("employee", "organization", "opened_at", "closed_at", "status", "calculated_payout")
    list_filter = ("status", "organization", "opened_at")
    search_fields = ("employee__first_name", "employee__last_name")
    readonly_fields = ("opened_at", "closed_at")  # Исправлено: заменено created_at на opened_at и closed_at


@admin.register(ShiftSchedule)
class ShiftScheduleAdmin(admin.ModelAdmin):
    list_display = ("employee", "organization", "date", "start_time", "end_time", "status", "created_at")
    list_filter = ("status", "organization", "date")
    search_fields = ("employee__first_name", "employee__last_name")
    readonly_fields = ("created_at",)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "organization", "is_read", "created_at")
    list_filter = ("is_read", "organization", "created_at")
    readonly_fields = ("created_at",)