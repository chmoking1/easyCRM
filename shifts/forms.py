"""Forms for managing employee work shifts and schedules."""

from decimal import Decimal
from django import forms
from accounts.models import Employee
from .models import Shift, ShiftSchedule


class CloseShiftForm(forms.ModelForm):
    """Form to collect total sales when closing an active shift."""

    total_sales = forms.DecimalField(
        label="Итоговая выручка за смену (руб.)",
        max_digits=12,
        decimal_places=2,
        initial=Decimal("0.00"),
        min_value=Decimal("0.00"),
        widget=forms.NumberInput(attrs={
            "class": "form-control",
            "placeholder": "0.00",
            "step": "0.01",
        }),
        help_text="Укажите общую сумму продаж, если к вашей ставке привязан процент.",
    )

    class Meta:
        model = Shift
        fields = ("total_sales",)


class ShiftScheduleForm(forms.ModelForm):
    """Form for employers to schedule employee shifts and for employees to propose shifts."""

    repeat_mode = forms.ChoiceField(
        label="Тип графика",
        choices=[
            ("single", "Одна смена"),
            ("2/2", "График 2/2"),
            ("3/3", "График 3/3"),
            ("custom", "Произвольный (X через Y)"),
        ],
        initial="single",
        required=False,
    )
    work_days = forms.IntegerField(
        label="Рабочих дней",
        initial=2,
        min_value=1,
        max_value=30,
        required=False,
    )
    rest_days = forms.IntegerField(
        label="Выходных дней",
        initial=2,
        min_value=1,
        max_value=30,
        required=False,
    )
    repeat_until = forms.DateField(
        label="Заполнить график до",
        required=False,
        widget=forms.DateInput(attrs={
            "type": "date",
            "style": "background: #18181b; border: 1px solid rgba(255,255,255,0.15); color: #fff; padding: 0.5rem; border-radius: 8px; width: 100%; color-scheme: dark;"
        })
    )

    class Meta:
        model = ShiftSchedule
        fields = ("employee", "date", "start_time", "end_time", "note")
        widgets = {
            "date": forms.DateInput(attrs={
                "type": "date",
                "id": "id_schedule_date",
                "style": "background: #18181b; border: 1px solid rgba(255,255,255,0.15); color: #fff; padding: 0.5rem; border-radius: 8px; width: 100%; color-scheme: dark;"
            }),
            "start_time": forms.TimeInput(attrs={
                "type": "time",
                "style": "background: #18181b; border: 1px solid rgba(255,255,255,0.15); color: #fff; padding: 0.5rem; border-radius: 8px; width: 100%; color-scheme: dark;"
            }),
            "end_time": forms.TimeInput(attrs={
                "type": "time",
                "style": "background: #18181b; border: 1px solid rgba(255,255,255,0.15); color: #fff; padding: 0.5rem; border-radius: 8px; width: 100%; color-scheme: dark;"
            }),
            "note": forms.TextInput(attrs={
                "placeholder": "Заметка (необязательно)",
                "style": "background: #18181b; border: 1px solid rgba(255,255,255,0.15); color: #fff; padding: 0.5rem; border-radius: 8px; width: 100%;"
            }),
        }

    def __init__(self, *args, organization=None, is_employee=False, **kwargs):
        super().__init__(*args, **kwargs)
        if organization:
            self.fields["employee"].queryset = Employee.objects.filter(
                organization=organization, is_active=True
            )
            self.fields["employee"].widget.attrs.update({
                "style": "background: #18181b; border: 1px solid rgba(255,255,255,0.15); color: #fff; padding: 0.5rem; border-radius: 8px; width: 100%;"
            })

        if is_employee:
            self.fields["employee"].required = False
            self.fields["repeat_mode"].widget = forms.HiddenInput()