"""Regression tests for the public account entry flow."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Employee, Organization


class LandingPageTests(TestCase):
    """Verify that the first screen stays usable as the project grows."""

    def test_landing_page_is_available(self) -> None:
        """Anyone should be able to see the entry page without an account."""
        response = self.client.get(reverse("landing"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Создать организацию")

    def test_registration_creates_owner_and_organization(self) -> None:
        """One valid registration must create a linked user and organisation."""
        response = self.client.post(reverse("landing"), {
            "form_type": "registration",
            "organization_name": "Тестовая кофейня",
            "username": "owner",
            "email": "owner@example.test",
            "password1": "safe-test-password-123",
            "password2": "safe-test-password-123",
        })

        # A successful registration takes the new owner to their protected workspace.
        self.assertRedirects(response, reverse("dashboard"))
        user = User.objects.get(username="owner")
        self.assertEqual(Organization.objects.get(owner=user).name, "Тестовая кофейня")

    def test_owner_can_open_dashboard(self) -> None:
        """The authenticated owner should see their organisation name and zero-state summary."""
        user = User.objects.create_user(username="manager", password="safe-test-password-123")
        Organization.objects.create(name="Ночная смена", owner=user)
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ночная смена")
        self.assertContains(response, "Соберите свою команду")

    def test_owner_can_add_and_see_employee(self) -> None:
        """Creating an employee must link it to the current organisation and show it in the list."""
        user = User.objects.create_user(username="manager", password="safe-test-password-123")
        organization = Organization.objects.create(name="Ночная смена", owner=user)
        self.client.force_login(user)

        response = self.client.post(reverse("employee-create"), {
            "first_name": "Анна",
            "last_name": "Иванова",
            "phone": "+7 999 123-45-67",
            "email": "anna@example.test",
            "telegram_username": "@anna_ivanova",
            "position": "Бариста",
            "hourly_rate": "350",
            "sales_percentage": "5",
        })

        self.assertRedirects(response, reverse("employees"))
        employee = Employee.objects.get(organization=organization)
        self.assertEqual(employee.full_name, "Анна Иванова")
        self.assertEqual(employee.telegram_username, "anna_ivanova")
        self.assertContains(self.client.get(reverse("employees")), "Бариста")

    def test_new_employee_form_is_available(self) -> None:
        """The form route must render all contact and payroll fields for an authenticated owner."""
        user = User.objects.create_user(username="manager", password="safe-test-password-123")
        Organization.objects.create(name="Ночная смена", owner=user)
        self.client.force_login(user)

        response = self.client.get(reverse("employee-create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Контакты")
        self.assertContains(response, "Процент от продаж")
