"""Forms for secure login, organisation registration, and employee settings."""

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User

from .models import Employee


class SignInForm(AuthenticationForm):
    """Login form that adds CSS classes without changing Django authentication rules."""

    username = forms.CharField(
        label="Логин",
        widget=forms.TextInput(attrs={"placeholder": "Электронная почта или логин", "autocomplete": "username"}),
    )
    password = forms.CharField(
        label="Пароль",
        widget=forms.PasswordInput(attrs={"placeholder": "Пароль", "autocomplete": "current-password"}),
    )


class OrganizationRegistrationForm(UserCreationForm):
    """Create the employer account and collect the name of its first organisation."""

    organization_name = forms.CharField(
        max_length=150,
        label="Название организации",
        widget=forms.TextInput(attrs={"placeholder": "Например, Кофейня на Пушкина"}),
    )
    email = forms.EmailField(
        label="Электронная почта",
        widget=forms.EmailInput(attrs={"placeholder": "name@example.com", "autocomplete": "email"}),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("organization_name", "username", "email", "password1", "password2")
        labels = {"username": "Логин", "password1": "Пароль", "password2": "Повторите пароль"}
        widgets = {"username": forms.TextInput(attrs={"placeholder": "Придумайте логин", "autocomplete": "username"})}

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["password1"].label = "Пароль"
        self.fields["password1"].widget.attrs.update({"placeholder": "Не менее 8 символов", "autocomplete": "new-password"})
        self.fields["password1"].help_text = "Используйте не менее 8 символов."
        self.fields["password2"].label = "Повторите пароль"
        self.fields["password2"].widget.attrs.update({"placeholder": "Повторите пароль", "autocomplete": "new-password"})
        self.fields["password2"].help_text = ""


class EmployeeForm(forms.ModelForm):
    """Validate and manage employee details collected by the employer."""

    password = forms.CharField(
        label="Пароль для входа",
        required=False,
        widget=forms.PasswordInput(attrs={"placeholder": "Оставьте пустым для автогенерации", "autocomplete": "new-password"}),
        help_text="Пароль, по которому сотрудник сможет войти в систему.",
    )

    class Meta:
        model = Employee
        fields = (
            "first_name",
            "last_name",
            "phone",
            "email",
            "telegram_username",
            "position",
            "pay_type",
            "hourly_rate",
            "sales_percentage",
            "payout_frequency",
            "payout_days",
            "can_edit_schedule",
        )
        labels = {
            "first_name": "Имя",
            "last_name": "Фамилия",
            "phone": "Телефон",
            "email": "Электронная почта",
            "telegram_username": "Telegram",
            "position": "Должность",
            "pay_type": "Тип оплаты",
            "hourly_rate": "Ставка в час, ₽",
            "sales_percentage": "Процент от продаж, %",
            "payout_frequency": "График выплат",
            "payout_days": "Дни выплат",
            "can_edit_schedule": "Разрешено предлагать график",
        }
        widgets = {
            "first_name": forms.TextInput(attrs={"placeholder": "Анна", "autocomplete": "given-name"}),
            "last_name": forms.TextInput(attrs={"placeholder": "Иванова", "autocomplete": "family-name"}),
            "phone": forms.TextInput(attrs={"placeholder": "+7 999 123-45-67", "autocomplete": "tel"}),
            "email": forms.EmailInput(attrs={"placeholder": "anna@example.com", "autocomplete": "email"}),
            "telegram_username": forms.TextInput(attrs={"placeholder": "@anna_ivanova", "autocomplete": "off"}),
            "position": forms.TextInput(attrs={"placeholder": "Бариста"}),
            "pay_type": forms.Select(attrs={"id": "id_pay_type"}),
            "hourly_rate": forms.NumberInput(attrs={"placeholder": "350", "min": "0", "step": "0.01"}),
            "sales_percentage": forms.NumberInput(attrs={"placeholder": "5", "min": "0", "step": "0.01"}),
            "payout_frequency": forms.Select(attrs={"id": "id_payout_frequency"}),
            "payout_days": forms.HiddenInput(attrs={"id": "id_payout_days"}),
            "can_edit_schedule": forms.CheckboxInput(attrs={"style": "width: 18px; height: 18px; accent-color: #22c55e;"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["payout_days"].required = False

    def clean_telegram_username(self) -> str:
        return self.cleaned_data["telegram_username"].strip().removeprefix("@")