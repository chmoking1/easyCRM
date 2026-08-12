"""URL configuration for the shifts app."""

from django.urls import path
from . import views

urlpatterns = [
    path("schedule/", views.schedule_view, name="shift-schedule"),
    path("schedule/<int:schedule_id>/delete/", views.delete_schedule, name="schedule-delete"),
    path("schedule/<int:schedule_id>/approve/", views.approve_schedule, name="schedule-approve"),
    path("schedule/<int:schedule_id>/reject/", views.reject_schedule, name="schedule-reject"),
    path("start/", views.shift_start, name="shift-start"),
    path("close/<int:shift_id>/", views.shift_close, name="shift-close"),
    path("reports/", views.shift_reports, name="shift-reports"),

    path("payroll/", views.payroll_view, name="payroll"),
    path("payroll/pay/<int:employee_id>/", views.process_payment, name="process-payment"),

    path("payroll/history/<int:employee_id>/", views.employee_payment_history, name="employee-payment-history"),
    path("payroll/details/<int:employee_id>/", views.employee_payout_details, name="employee-payout-details"),
    path("payroll/export/", views.export_payroll_csv, name="export-payroll"),

    path("payroll/receipt/<int:payment_id>/pdf/", views.download_payment_receipt_pdf, name="download-payment-receipt"),

    path("api/notifications/", views.get_notifications_api, name="api-notifications"),
    path("api/notifications/read/", views.mark_notifications_read_api, name="api-notifications-read"),

    path("api/adjustments/add/", views.add_adjustment_api, name="api-add-adjustment"),
    path("api/adjustments/list/", views.get_adjustments_api, name="api-get-adjustments"),

    path("reports/pdf/", views.export_analytics_pdf, name="export-analytics-pdf"),

]