from decimal import Decimal
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class Organization(models.Model):
    name = models.CharField("Название организации", max_length=255)
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="owned_organizations",
        verbose_name="Владелец",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Организация"
        verbose_name_plural = "Организации"
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class Employee(models.Model):
    class PayoutFrequency(models.TextChoices):
        WEEKLY = "weekly", "Раз в неделю"
        BIWEEKLY = "biweekly", "2 раза в месяц"
        DAILY = "daily", "Каждый день"
        CUSTOM = "custom", "По запросу"

    class PayType(models.TextChoices):
        HOURLY = "hourly", "Почасовая ставка"
        PERCENTAGE = "percent", "Процент от продаж"
        HYBRID = "hybrid", "Ставка + Процент"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="employees",
        verbose_name="Организация",
    )
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="employee_profile",
        verbose_name="Учётная запись",
        null=True,
        blank=True,
    )
    first_name = models.CharField("Имя", max_length=150)
    last_name = models.CharField("Фамилия", max_length=150)
    phone = models.CharField("Телефон", max_length=30, blank=True)
    email = models.EmailField("Email", blank=True)
    telegram_username = models.CharField("Telegram", max_length=100, blank=True)
    position = models.CharField("Должность", max_length=100, blank=True)

    # --- Настройки формата и расчёта оплаты ---
    pay_type = models.CharField(
        "Тип оплаты",
        max_length=20,
        choices=PayType.choices,
        default=PayType.HOURLY,
    )
    hourly_rate = models.DecimalField(
        "Почасовая ставка (₽)",
        max_digits=8,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    sales_percentage = models.DecimalField(
        "Процент от продаж (%)",
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    # --- Настройки графика выплат ---
    payout_frequency = models.CharField(
        "График выплат",
        max_length=20,
        choices=PayoutFrequency.choices,
        default=PayoutFrequency.WEEKLY,
    )
    payout_days = models.CharField(
        "Дни выплат",
        max_length=50,
        default="1",
        blank=True,
        help_text="Для 'weekly': 1 (Пн) - 7 (Вс). Для 'biweekly': числа месяца через запятую (например, 15,30).",
    )
    is_active = models.BooleanField("Активен", default=True)
    can_edit_schedule = models.BooleanField(
        "Разрешено предлагать график",
        default=False,
        help_text="Разрешает сотруднику создавать заявки на смены в календаре.",
    )

    class Meta:
        verbose_name = "Сотрудник"
        verbose_name_plural = "Сотрудники"
        ordering = ["first_name", "last_name"]

    def __str__(self):
        return f"{self.full_name} ({self.organization.name})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def get_payout_days_display(self):
        """Красивое представление выбранных дней выплаты."""
        if self.payout_frequency == self.PayoutFrequency.WEEKLY:
            weekdays = {
                "1": "Понедельник",
                "2": "Вторник",
                "3": "Среда",
                "4": "Четверг",
                "5": "Пятница",
                "6": "Суббота",
                "7": "Воскресенье",
            }
            day_name = weekdays.get(str(self.payout_days), "Понедельник")
            return f"Каждую неделю: {day_name.lower()}"
        elif self.payout_frequency == self.PayoutFrequency.BIWEEKLY:
            parts = str(self.payout_days).split(",")
            if len(parts) == 2:
                return f"{parts[0]} и {parts[1]} числа месяца"
            return f"{self.payout_days} числа месяца"
        elif self.payout_frequency == self.PayoutFrequency.CUSTOM:
            return f"{self.payout_days} число месяца (по запросу)"
        elif self.payout_frequency == self.PayoutFrequency.DAILY:
            return "Ежедневно"
        return self.get_payout_frequency_display()

    def is_payout_due_today(self) -> bool:
        """Проверяет, наступил ли сегодня день выплаты по графику сотрудника."""
        today = timezone.localdate()

        if self.payout_frequency == self.PayoutFrequency.DAILY:
            return True

        if self.payout_frequency == self.PayoutFrequency.WEEKLY:
            # 1 = Понедельник, 7 = Воскресенье
            return str(today.isoweekday()) == str(self.payout_days)

        if self.payout_frequency == self.PayoutFrequency.BIWEEKLY:
            days = [d.strip() for d in str(self.payout_days).split(",")]
            return str(today.day) in days

        if self.payout_frequency == self.PayoutFrequency.CUSTOM:
            return str(today.day) == str(self.payout_days)

        return False