"""Forms for secure login and organisation registration."""

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User

from .models import Employee

class SignInForm(AuthenticationForm):
    """Login form that adds CSS classes without changing Django authentication rules."""

    username = forms.CharField(label="Логин", widget=forms.TextInput(attrs={"placeholder": "Электронная почта или логин", "autocomplete": "username"}))
    password = forms.CharField(label="Пароль", widget=forms.PasswordInput(attrs={"placeholder": "Пароль", "autocomplete": "current-password"}))


class OrganizationRegistrationForm(UserCreationForm):
    """Create the employer account and collect the name of its first organisation."""

    organization_name = forms.CharField(max_length=150, label="Название организации", widget=forms.TextInput(attrs={"placeholder": "Например, Кофейня на Пушкина"}))
    email = forms.EmailField(label="Электронная почта", widget=forms.EmailInput(attrs={"placeholder": "name@example.com", "autocomplete": "email"}))

    class Meta(UserCreationForm.Meta):
        # Django's default user is sufficient for the first release and keeps auth reliable.
        model = User
        fields = ("organization_name", "username", "email", "password1", "password2")
        # Labels are explicitly Russian so the form needs no translation configuration.
        labels = {"username": "Логин", "password1": "Пароль", "password2": "Повторите пароль"}
        widgets = {"username": forms.TextInput(attrs={"placeholder": "Придумайте логин", "autocomplete": "username"})}

    def __init__(self, *args, **kwargs) -> None:
        """Replace Django's technical password hints with concise product-language help."""
        super().__init__(*args, **kwargs)
        # Password inputs need Russian labels and placeholders because they are inherited from Django.
        self.fields["password1"].label = "Пароль"
        self.fields["password1"].widget.attrs.update({"placeholder": "Не менее 8 символов", "autocomplete": "new-password"})
        self.fields["password1"].help_text = "Используйте не менее 8 символов."
        self.fields["password2"].label = "Повторите пароль"
        self.fields["password2"].widget.attrs.update({"placeholder": "Повторите пароль", "autocomplete": "new-password"})
        self.fields["password2"].help_text = ""


class EmployeeForm(forms.ModelForm):
    """Validate the employee details collected by the employer."""

    class Meta:
        """Keep all field labels and input hints next to the data definition."""

        model = Employee
        fields = ("first_name", "last_name", "phone", "email", "telegram_username", "position", "hourly_rate", "sales_percentage")
        labels = {
            "first_name": "Имя",
            "last_name": "Фамилия",
            "phone": "Телефон",
            "email": "Электронная почта",
            "telegram_username": "Telegram",
            "position": "Должность",
            "hourly_rate": "Ставка в час, ₽",
            "sales_percentage": "Процент от продаж, %",
        }
        widgets = {
            "first_name": forms.TextInput(attrs={"placeholder": "Анна", "autocomplete": "given-name"}),
            "last_name": forms.TextInput(attrs={"placeholder": "Иванова", "autocomplete": "family-name"}),
            "phone": forms.TextInput(attrs={"placeholder": "+7 999 123-45-67", "autocomplete": "tel"}),
            "email": forms.EmailInput(attrs={"placeholder": "anna@example.com", "autocomplete": "email"}),
            "telegram_username": forms.TextInput(attrs={"placeholder": "@anna_ivanova", "autocomplete": "off"}),
            "position": forms.TextInput(attrs={"placeholder": "Бариста"}),
            "hourly_rate": forms.NumberInput(attrs={"placeholder": "350", "min": "0", "step": "0.01"}),
            "sales_percentage": forms.NumberInput(attrs={"placeholder": "5", "min": "0", "step": "0.01"}),
        }

    def clean_telegram_username(self) -> str:
        """Store a Telegram username consistently, whether the employer types @ or not."""
        return self.cleaned_data["telegram_username"].strip().removeprefix("@")
