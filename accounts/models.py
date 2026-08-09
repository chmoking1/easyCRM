"""Database models needed to create the first employer organisation."""

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Organization(models.Model):
    """A business that will later own employees, schedules, and payroll data."""

    # A short business name is enough for the first registration flow.
    name = models.CharField("Название организации", max_length=150)
    # The owner is created by the registration form and controls the organisation initially.
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="owned_organization")
    # Creation time supports audit history without exposing it in the UI yet.
    created_at = models.DateTimeField("Создана", auto_now_add=True)

    class Meta:
        # Russian labels make Django admin understandable to the product owner.
        verbose_name = "Организация"
        verbose_name_plural = "Организации"

    def __str__(self) -> str:
        """Show the business name in Django admin and debug output."""
        return self.name


class Employee(models.Model):
    """A team member belonging to one organisation, independent from a future login account."""

    # Deleting an organisation removes its private employee data with it.
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="employees")
    first_name = models.CharField("Имя", max_length=80)
    last_name = models.CharField("Фамилия", max_length=80, blank=True)
    phone = models.CharField("Телефон", max_length=30)
    # Optional digital contacts let an employer reach staff without requiring a CRM login yet.
    email = models.EmailField("Электронная почта", blank=True)
    telegram_username = models.CharField("Telegram", max_length=64, blank=True)
    position = models.CharField("Должность", max_length=100)
    # DecimalField avoids floating-point rounding mistakes in payroll calculations.
    hourly_rate = models.DecimalField("Ставка в час", max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    sales_percentage = models.DecimalField("Процент от продаж", max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    # Deactivation preserves payroll history while excluding a former employee from future schedules.
    is_active = models.BooleanField("Работает", default=True)
    created_at = models.DateTimeField("Добавлен", auto_now_add=True)

    class Meta:
        """Default ordering puts recently added team members at the top."""

        ordering = ("-is_active", "-created_at")
        verbose_name = "Сотрудник"
        verbose_name_plural = "Сотрудники"

    @property
    def full_name(self) -> str:
        """Return a display-ready name without leaving extra whitespace for a missing surname."""
        return f"{self.first_name} {self.last_name}".strip()

    def __str__(self) -> str:
        """Use the full name in Django admin and developer output."""
        return self.full_name
