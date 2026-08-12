"""URL configuration for accounts and organization management."""

from django.urls import path
from . import views

urlpatterns = [
    # Главная страница с формой входа/регистрации
    path("", views.landing, name="landing"),
    path("login/", views.user_login, name="login"),
    path("logout/", views.user_logout, name="logout"),
    path("logout-user/", views.user_logout, name="user-logout"),
    
    # Дашборды
    path("dashboard/", views.dashboard, name="dashboard"),
    path("my-dashboard/", views.employee_dashboard, name="employee-dashboard"),
    
    # Управление сотрудниками
    path("employees/", views.employee_list, name="employees"),
    path("employees/add/", views.employee_create, name="employee-create"),
    path("employees/<int:employee_id>/", views.employee_detail, name="employee-detail"),
    path("employees/<int:employee_id>/edit/", views.employee_edit, name="employee-edit"),
    path("employees/<int:employee_id>/deactivate/", views.employee_deactivate, name="employee-deactivate"),

    path("employees/<int:employee_id>/reset-password/", views.employee_reset_password, name="employee-reset-password"),

    path("employees/<int:employee_id>/delete/", views.employee_delete, name="employee-delete"),
]