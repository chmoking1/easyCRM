from decimal import Decimal
from django.conf import settings
from django.db import models
from django.utils import timezone
from accounts.models import Employee, Organization


class Shift(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Открыта"
        COMPLETED = "completed", "Завершена"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="shifts",
        verbose_name="Организация",
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="shifts",
        verbose_name="Сотрудник",
    )
    opened_at = models.DateTimeField("Время открытия", default=timezone.now)
    closed_at = models.DateTimeField("Время закрытия", null=True, blank=True)
    total_sales = models.DecimalField(
        "Выручка за смену (₽)",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    calculated_payout = models.DecimalField(
        "Начисленная выплата (₽)",
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    status = models.CharField(
        "Статус смены",
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
    )
    is_paid = models.BooleanField("Оплачено", default=False)

    class Meta:
        verbose_name = "Смена"
        verbose_name_plural = "Смены"
        ordering = ["-opened_at"]

    def __str__(self):
        return f"Смена {self.employee.full_name} ({self.opened_at.strftime('%d.%m.%Y %H:%M')})"

    @property
    def duration_hours(self) -> float:
        """Возвращает длительность смены в часах."""
        end_time = self.closed_at or timezone.now()
        duration = end_time - self.opened_at
        return round(duration.total_seconds() / 3600, 2)

    def calculate_payout(self) -> Decimal:
        """Вычисляет заработок сотрудника в зависимости от его pay_type."""
        employee = self.employee
        if not employee:
            return Decimal("0.00")

        pay_type = str(getattr(employee, "pay_type", "hourly"))
        hours = Decimal(str(self.duration_hours))
        total_payout = Decimal("0.00")

        # 1. Почасовая ставка
        if pay_type in ["hourly", "hybrid"]:
            hourly_rate = employee.hourly_rate or Decimal("0.00")
            total_payout += hours * hourly_rate

        # 2. Процент от продаж
        if pay_type in ["percent", "hybrid"]:
            sales = self.total_sales or Decimal("0.00")
            sales_pct = employee.sales_percentage or Decimal("0.00")
            total_payout += sales * (sales_pct / Decimal("100"))

        return total_payout.quantize(Decimal("0.01"))


class ShiftSchedule(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "На рассмотрении"
        APPROVED = "approved", "Подтверждена"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="schedules",
        verbose_name="Организация",
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="schedules",
        verbose_name="Сотрудник",
    )
    date = models.DateField("Дата смены")
    start_time = models.TimeField("Время начала")
    end_time = models.TimeField("Время окончания")
    note = models.CharField("Заметка / Задание", max_length=255, blank=True)
    status = models.CharField(
        "Статус заявки",
        max_length=20,
        choices=Status.choices,
        default=Status.APPROVED,
    )
    is_completed = models.BooleanField(
        "Отработана",
        default=False,
        help_text="Отмечается автоматически, когда сотрудник закрывает смену через CRM.",
    )
    replaced_by = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="replacements_performed",
        verbose_name="Кем заменён",
    )
    is_replacement = models.BooleanField(
        "Выход на замену",
        default=False,
    )
    created_at = models.DateTimeField("Создана", auto_now_add=True)

    class Meta:
        verbose_name = "Запланированная смена"
        verbose_name_plural = "Запланированные смены"
        ordering = ["date", "start_time"]

    def __str__(self):
        rep = f" (Замена: {self.replaced_by.first_name})" if self.replaced_by else ""
        return f"{self.employee.full_name} ({self.date}): {self.start_time.strftime('%H:%M')}-{self.end_time.strftime('%H:%M')}{rep} [{self.get_status_display()}]"


class Notification(models.Model):
    class Category(models.TextChoices):
        SCHEDULE = "schedule", "График смен"
        PAYROLL = "payroll", "Выплаты"
        SHIFT = "shift", "Открытие/Закрытие смен"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="Организация",
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notifications",
        verbose_name="Получатель",
    )
    title = models.CharField("Заголовок", max_length=255)
    message = models.TextField("Текст сообщения")
    category = models.CharField(
        "Категория",
        max_length=20,
        choices=Category.choices,
        default=Category.SCHEDULE,
    )
    link = models.CharField("Ссылка для перехода", max_length=255, blank=True, null=True)
    is_read = models.BooleanField("Прочитано", default=False)
    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        verbose_name = "Уведомление"
        verbose_name_plural = "Уведомления"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.created_at.strftime('%d.%m %H:%M')})"


class PayrollPayment(models.Model):
    """Model to log salary payments issued to employees."""

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="payroll_payments",
        verbose_name="Организация",
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="payments",
        verbose_name="Сотрудник",
    )
    amount = models.DecimalField("Сумма выплаты (₽)", max_digits=12, decimal_places=2)
    paid_at = models.DateTimeField("Дата выплаты", default=timezone.now)
    comment = models.CharField("Заметка", max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Кто выплатил",
    )

    class Meta:
        verbose_name = "Выплата зарплаты"
        verbose_name_plural = "Выплаты зарплаты"
        ordering = ["-paid_at"]

    def __str__(self):
        return f"{self.employee.full_name} — {self.amount} ₽ ({self.paid_at.strftime('%d.%m.%Y')})"


class PayrollAdjustment(models.Model):
    class AdjustmentType(models.TextChoices):
        BONUS = "bonus", "Премия"
        PENALTY = "penalty", "Штраф"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="adjustments",
        verbose_name="Организация",
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="adjustments",
        verbose_name="Сотрудник",
    )
    adjustment_type = models.CharField(
        "Тип",
        max_length=10,
        choices=AdjustmentType.choices,
        default=AdjustmentType.BONUS,
    )
    amount = models.DecimalField("Сумма (₽)", max_digits=10, decimal_places=2)
    reason = models.CharField("Причина", max_length=255)
    is_settled = models.BooleanField("Учтено в выплате", default=False)
    payment = models.ForeignKey(
        "PayrollPayment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="adjustments",
        verbose_name="Выплата",
    )
    created_at = models.DateTimeField("Дата", auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Назначил",
    )

    class Meta:
        verbose_name = "Штраф / Премия"
        verbose_name_plural = "Штрафы и Премии"
        ordering = ["-created_at"]

    def __str__(self):
        prefix = "+" if self.adjustment_type == self.AdjustmentType.BONUS else "-"
        return f"{self.employee.full_name}: {prefix}{self.amount} ₽ ({self.reason})"