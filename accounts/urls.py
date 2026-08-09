"""Public URLs owned by the accounts app."""

from django.urls import path
from . import views


urlpatterns = [
    # The landing page contains both login and registration forms.
    path("", views.landing, name="landing"),
    # Employer home page shown after a successful login or registration.
    path("dashboard/", views.dashboard, name="dashboard"),
    # Employee list and creation are the first team-management routes.
    path("employees/", views.employee_list, name="employees"),
    path("employees/new/", views.employee_create, name="employee-create"),
    path("employees/<int:employee_id>/", views.employee_detail, name="employee-detail"),
    path("employees/<int:employee_id>/edit/", views.employee_edit, name="employee-edit"),
    path("employees/<int:employee_id>/deactivate/", views.employee_deactivate, name="employee-deactivate"),
]
