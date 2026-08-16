"""HTTP views for managing shifts, schedules, shift reports, and payroll adjustments."""

import calendar
import csv
import io
import os
from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.html import mark_safe

# ReportLab imports for PDF generation
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable

from accounts.models import Employee
from accounts.views import get_owner_organization
from .forms import CloseShiftForm, ShiftScheduleForm
from .models import (
    Event,
    Notification,
    PayrollAdjustment,
    PayrollPayment,
    Position,
    Shift,
    ShiftSchedule,
)
from .services import PayrollService, ScheduleService, ShiftReportService
from .services.pdf_generator import PDFAnalyticsService, PDFReceiptService


def get_active_shift_info(shift, organization, today_date):
    """Определяет статус активности смены и факт выхода на замену."""
    scheduled_today = ShiftSchedule.objects.filter(
        organization=organization,
        date=today_date,
        status=ShiftSchedule.Status.APPROVED,
    )
    
    # Запланирован ли этот сотрудник сегодня?
    is_scheduled = scheduled_today.filter(employee=shift.employee).exists()
    
    is_replacement = False
    replaced_emp_name = None

    if not is_scheduled:
        # Ищем коллегу, который был запланирован на сегодня, но не открыл свою смену
        scheduled_colleague = scheduled_today.exclude(
            employee=shift.employee
        ).filter(is_completed=False).first()
        
        if scheduled_colleague:
            is_replacement = True
            replaced_emp_name = scheduled_colleague.employee.first_name
        else:
            is_replacement = True
            replaced_emp_name = "Вне плана"

    return {
        "shift": shift,
        "is_replacement": is_replacement,
        "replaced_emp_name": replaced_emp_name,
    }


@login_required
def active_shifts_api(request):
    """JSON API endpoint для блока 'Работают прямо сейчас' с индикацией замен."""
    if hasattr(request.user, "employee_profile"):
        return JsonResponse({"error": "Forbidden"}, status=403)

    organization = get_owner_organization(request.user)
    today = timezone.localdate()
    open_shifts = Shift.objects.filter(
        organization=organization, status=Shift.Status.OPEN
    ).select_related("employee").order_by("-opened_at")

    shifts_data = []
    for s in open_shifts:
        info = get_active_shift_info(s, organization, today)
        shifts_data.append({
            "id": s.id,
            "employee_name": s.employee.full_name,
            "employee_first_name": s.employee.first_name,
            "opened_at": s.opened_at.strftime("%H:%M"),
            "duration_hours": s.duration_hours,
            "is_replacement": info["is_replacement"],
            "replaced_emp_name": info["replaced_emp_name"],
        })

    return JsonResponse({"active_shifts": shifts_data})


@login_required
def schedule_view(request):
    """Render shift schedule calendar and handle shift creation/proposals."""
    user = request.user
    is_employee = hasattr(user, "employee_profile")
    employee = getattr(user, "employee_profile", None)

    if is_employee:
        organization = employee.organization
    else:
        organization = get_owner_organization(user)

    today = timezone.localdate()
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
    except (ValueError, TypeError):
        year, month = today.year, today.month

    selected_date = datetime(year, month, 1).date()
    prev_month = (selected_date - timedelta(days=1)).replace(day=1)
    next_month = (selected_date + timedelta(days=32)).replace(day=1)

    if request.method == "POST":
        if is_employee and not employee.can_edit_schedule:
            messages.error(request, "У вас нет прав для изменения графика.")
            return redirect("shift-schedule")

        form = ShiftScheduleForm(
            request.POST,
            organization=organization,
            is_employee=is_employee,
        )
        if form.is_valid():
            start_date = form.cleaned_data["date"]
            start_time = form.cleaned_data["start_time"]
            end_time = form.cleaned_data["end_time"]
            note = form.cleaned_data.get("note", "")

            selected_employee = employee if is_employee else form.cleaned_data.get("employee")
            repeat_mode = form.cleaned_data.get("repeat_mode", "single")
            repeat_until = form.cleaned_data.get("repeat_until")

            if not is_employee and repeat_mode != "single" and repeat_until and repeat_until >= start_date:
                created_count = ScheduleService.create_shift_series(
                    organization=organization,
                    employee=selected_employee,
                    start_date=start_date,
                    start_time=start_time,
                    end_time=end_time,
                    note=note,
                    repeat_mode=repeat_mode,
                    repeat_until=repeat_until,
                    work_days=form.cleaned_data.get("work_days"),
                    rest_days=form.cleaned_data.get("rest_days"),
                )
                messages.success(request, f"Успешно создана серия из {created_count} смен по графику!")
            else:
                schedule_item = form.save(commit=False)
                schedule_item.organization = organization
                schedule_item.employee = selected_employee

                if is_employee:
                    schedule_item.status = ShiftSchedule.Status.PENDING
                    schedule_item.save()

                    Notification.objects.create(
                        organization=organization,
                        title="Новая заявка на смену",
                        message=(
                            f"Сотрудник {employee.full_name} предложил смену на "
                            f"{schedule_item.date.strftime('%d.%m.%Y')} "
                            f"({schedule_item.start_time.strftime('%H:%M')}–{schedule_item.end_time.strftime('%H:%M')})."
                        ),
                    )
                    messages.success(request, "Заявка на смену отправлена на подтверждение работодателю.")
                else:
                    schedule_item.status = ShiftSchedule.Status.APPROVED
                    schedule_item.save()
                    messages.success(request, "Смена добавлена в график.")

            return redirect(f"/shifts/schedule/?year={start_date.year}&month={start_date.month}")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Ошибка в поле '{field}': {error}")
    else:
        form = ShiftScheduleForm(organization=organization, is_employee=is_employee)

    # Получаем смены и события за месяц через сервис
    items_by_date = ScheduleService.get_schedule_for_month(organization, year, month)
    completed_shifts_set = ScheduleService.get_completed_shifts_set(organization, year, month)

    cal = calendar.Calendar(firstweekday=0)
    month_days = list(cal.itermonthdates(year, month))

    # Получаем список всех должностей организации для модального окна выбора
    positions = Position.objects.filter(organization=organization)

    return render(request, "shifts/schedule.html", {
        "organization": organization,
        "is_employee": is_employee,
        "employee": employee,
        "form": form,
        "items_by_date": items_by_date,
        "positions": positions,
        "completed_shifts_set": completed_shifts_set,
        "month_days": month_days,
        "selected_date": selected_date,
        "prev_month": prev_month,
        "next_month": next_month,
        "today": today,
        "active_page": "schedule",
    })


@login_required
def create_event(request):
    """Создание нового календарного события с немедленной рассылкой уведомлений."""
    if hasattr(request.user, "employee_profile"):
        messages.error(request, "У вас нет прав для создания событий.")
        return redirect("shift-schedule")

    organization = get_owner_organization(request.user)

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        date_str = request.POST.get("date")
        color = request.POST.get("color", "#3b82f6")
        description = request.POST.get("description", "").strip()
        position_ids = request.POST.getlist("target_positions")

        if title and date_str:
            event_obj = Event.objects.create(
                organization=organization,
                title=title,
                date=date_str,
                color=color,
                description=description,
            )
            if position_ids:
                event_obj.target_positions.set(position_ids)

            # РАССЫЛКА УВЕДОМЛЕНИЙ СОТРУДНИКАМ через сервис
            ScheduleService.notify_about_event(organization, event_obj)

            messages.success(request, f"Событие «{title}» успешно добавлено и разослано сотрудникам!")
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                return redirect(f"/shifts/schedule/?year={dt.year}&month={dt.month}")
            except Exception:
                pass
        else:
            messages.error(request, "Необходимо указать название и дату события.")

    return redirect("shift-schedule")


@login_required
def update_event(request, event_id):
    """Редактирование существующего календарного события и его целевых должностей."""
    if hasattr(request.user, "employee_profile"):
        messages.error(request, "У вас нет прав для редактирования событий.")
        return redirect("shift-schedule")

    organization = get_owner_organization(request.user)
    event_obj = get_object_or_404(Event, id=event_id, organization=organization)

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        date_str = request.POST.get("date")
        color = request.POST.get("color", event_obj.color)
        description = request.POST.get("description", "").strip()
        position_ids = request.POST.getlist("target_positions")

        if title and date_str:
            event_obj.title = title
            event_obj.date = date_str
            event_obj.color = color
            event_obj.description = description
            event_obj.save()

            # Обновляем список выбранных должностей
            event_obj.target_positions.set(position_ids)

            messages.success(request, f"Событие «{title}» успешно обновлено!")
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                return redirect(f"/shifts/schedule/?year={dt.year}&month={dt.month}")
            except Exception:
                pass
        else:
            messages.error(request, "Заполните обязательные поля события.")

    return redirect("shift-schedule")


@login_required
def delete_event(request, event_id):
    """Удаление календарного события из графика."""
    if hasattr(request.user, "employee_profile"):
        messages.error(request, "У вас нет прав для удаления событий.")
        return redirect("shift-schedule")

    organization = get_owner_organization(request.user)
    event_obj = get_object_or_404(Event, id=event_id, organization=organization)

    target_year, target_month = event_obj.date.year, event_obj.date.month
    title = event_obj.title
    event_obj.delete()

    messages.success(request, f"Событие «{title}» удалено из графика.")
    return redirect(f"/shifts/schedule/?year={target_year}&month={target_month}")


@login_required
def approve_schedule(request, schedule_id):
    """Approve a pending shift schedule request."""
    if hasattr(request.user, "employee_profile"):
        messages.error(request, "У вас нет прав для управления графиком.")
        return redirect("shift-schedule")

    organization = get_owner_organization(request.user)
    schedule_item = get_object_or_404(ShiftSchedule, id=schedule_id, organization=organization)

    schedule_item.status = ShiftSchedule.Status.APPROVED
    schedule_item.save()

    messages.success(
        request,
        f"Заявка сотрудника {schedule_item.employee.full_name} на {schedule_item.date.strftime('%d.%m.%Y')} утверждена."
    )
    return redirect(f"/shifts/schedule/?year={schedule_item.date.year}&month={schedule_item.date.month}")


@login_required
def reject_schedule(request, schedule_id):
    """Reject and delete a pending shift schedule request."""
    if hasattr(request.user, "employee_profile"):
        messages.error(request, "У вас нет прав для управления графиком.")
        return redirect("shift-schedule")

    organization = get_owner_organization(request.user)
    schedule_item = get_object_or_404(ShiftSchedule, id=schedule_id, organization=organization)

    employee_name = schedule_item.employee.full_name
    shift_date = schedule_item.date.strftime("%d.%m.%Y")
    target_year, target_month = schedule_item.date.year, schedule_item.date.month

    schedule_item.delete()

    messages.info(request, f"Заявка на смену {employee_name} на {shift_date} отклонена.")
    return redirect(f"/shifts/schedule/?year={target_year}&month={target_month}")


@login_required
def delete_schedule(request, schedule_id):
    """Delete an existing shift schedule."""
    if hasattr(request.user, "employee_profile"):
        messages.error(request, "У вас нет прав для управления графиком.")
        return redirect("shift-schedule")

    organization = get_owner_organization(request.user)
    schedule_item = get_object_or_404(ShiftSchedule, id=schedule_id, organization=organization)

    target_year, target_month = schedule_item.date.year, schedule_item.date.month
    schedule_item.delete()

    messages.success(request, "Смена удалена из графика.")
    return redirect(f"/shifts/schedule/?year={target_year}&month={target_month}")


@login_required
def shift_start(request):
    """Start an open shift for the logged-in employee."""
    employee = getattr(request.user, "employee_profile", None)
    if not employee:
        messages.error(request, "Доступно только для сотрудников.")
        return redirect("dashboard")

    active_shift = Shift.objects.filter(employee=employee, status=Shift.Status.OPEN).first()
    if active_shift:
        messages.warning(request, "У вас уже есть открытая смена.")
        return redirect("employee-dashboard")

    Shift.objects.create(
        organization=employee.organization,
        employee=employee,
        opened_at=timezone.now(),
        status=Shift.Status.OPEN,
    )
    messages.success(request, "Смена успешно открыта!")
    return redirect("employee-dashboard")


@login_required
def shift_close(request, shift_id):
    """Close an active shift, compute payout, and mark scheduled shift as completed (with replacement handling)."""
    employee = getattr(request.user, "employee_profile", None)
    if not employee:
        messages.error(request, "Доступно только для сотрудников.")
        return redirect("dashboard")

    shift_obj = get_object_or_404(Shift, id=shift_id, employee=employee, status=Shift.Status.OPEN)

    if request.method == "POST":
        form = CloseShiftForm(request.POST)
        if form.is_valid():
            now_dt = timezone.now()
            shift_obj.closed_at = now_dt
            shift_obj.total_sales = form.cleaned_data["total_sales"]
            shift_obj.calculated_payout = shift_obj.calculate_payout()
            shift_obj.status = Shift.Status.COMPLETED
            shift_obj.save()

            shift_date = timezone.localdate(shift_obj.opened_at)

            # 1. Проверяем, была ли смена запланирована именно на этого сотрудника
            own_schedule = ShiftSchedule.objects.filter(
                organization=employee.organization,
                employee=employee,
                date=shift_date,
            ).first()

            if own_schedule:
                own_schedule.is_completed = True
                own_schedule.save()
            else:
                # 2. Если нет — ищем смену коллеги на эту дату, чтобы зафиксировать замену
                other_schedule = ShiftSchedule.objects.filter(
                    organization=employee.organization,
                    date=shift_date,
                    is_completed=False,
                ).first()

                if other_schedule:
                    other_schedule.is_completed = True
                    other_schedule.replaced_by = employee
                    other_schedule.is_replacement = True
                    other_schedule.save()
                else:
                    # 3. Если вообще не было смен в графике — фиксируем внеплановый выход
                    ShiftSchedule.objects.create(
                        organization=employee.organization,
                        employee=employee,
                        date=shift_date,
                        start_time=shift_obj.opened_at.time(),
                        end_time=now_dt.time(),
                        note="Внеплановый выход",
                        status=ShiftSchedule.Status.APPROVED,
                        is_completed=True,
                        is_replacement=True,
                    )

            messages.success(request, f"Смена успешно закрыта. Заработано: {shift_obj.calculated_payout} ₽")
            return redirect("employee-dashboard")
    else:
        form = CloseShiftForm()

    return render(request, "shifts/close_shift.html", {
        "shift": shift_obj,
        "form": form,
    })


@login_required
def shift_reports(request):
    """Render analytical business report with KPIs, charts data, and employee rankings."""
    if hasattr(request.user, "employee_profile"):
        messages.error(request, "У вас нет прав для просмотра аналитики.")
        return redirect("employee-dashboard")

    organization = get_owner_organization(request.user)
    today = timezone.localdate()
    period_mode = request.GET.get("period", "this_month")

    # Получаем период через сервис
    start_date, end_date = ShiftReportService.get_date_range(period_mode)

    # Рассчитываем KPI через сервис
    kpis = ShiftReportService.calculate_kpis(organization, start_date, end_date)
    total_revenue = kpis["total_revenue"]
    total_fot = kpis["total_fot"]
    fot_percentage = kpis["fot_percentage"]
    total_hours = kpis["total_hours"]
    revenue_per_hour = kpis["revenue_per_hour"]
    completed_shifts = kpis["completed_shifts"]
    adjustments = kpis["adjustments"]

    # Генерируем данные для графиков через сервис
    chart_dates, chart_revenues, chart_fots = ShiftReportService.get_chart_data(
        completed_shifts, start_date, end_date
    )

    # Данные по дням недели через сервис
    weekday_names, weekday_revenues = ShiftReportService.get_weekday_revenues(completed_shifts)

    # Статистика сотрудников через сервис
    employees = organization.employees.filter(is_active=True)
    employee_stats = ShiftReportService.get_employee_stats(
        employees, completed_shifts, adjustments, period_mode
    )

    return render(request, "shifts/reports.html", {
        "organization": organization,
        "period_mode": period_mode,
        "start_date": start_date,
        "end_date": end_date,
        "total_revenue": total_revenue,
        "total_fot": total_fot,
        "fot_percentage": fot_percentage,
        "total_hours": total_hours,
        "revenue_per_hour": revenue_per_hour,
        "chart_dates": chart_dates,
        "chart_revenues": chart_revenues,
        "chart_fots": chart_fots,
        "weekday_names": weekday_names,
        "weekday_revenues": weekday_revenues,
        "employee_stats": employee_stats,
        "active_page": "reports",
    })


@login_required
def payroll_view(request):
    """Render payroll dashboard with adjustments and payout history."""
    user = request.user
    is_employee = hasattr(user, "employee_profile")

    if is_employee:
        employee = user.employee_profile

        total_earned = Shift.objects.filter(
            employee=employee, status=Shift.Status.COMPLETED
        ).aggregate(total=Sum("calculated_payout"))["total"] or Decimal("0.00")

        total_bonuses = PayrollAdjustment.objects.filter(
            employee=employee, adjustment_type=PayrollAdjustment.AdjustmentType.BONUS
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        total_penalties = PayrollAdjustment.objects.filter(
            employee=employee, adjustment_type=PayrollAdjustment.AdjustmentType.PENALTY
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        total_paid = PayrollPayment.objects.filter(
            employee=employee
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        total_due = Decimal(str(total_earned)) + Decimal(str(total_bonuses)) - Decimal(str(total_penalties))
        unpaid_amount = max(Decimal("0.00"), total_due - Decimal(str(total_paid))).quantize(Decimal("0.01"))

        if unpaid_amount == Decimal("0.00"):
            Shift.objects.filter(employee=employee, status=Shift.Status.COMPLETED, is_paid=False).update(is_paid=True)
            PayrollAdjustment.objects.filter(employee=employee, is_settled=False).update(is_settled=True)

        unpaid_shifts_count = Shift.objects.filter(
            employee=employee, status=Shift.Status.COMPLETED, is_paid=False
        ).count()

        payments = PayrollPayment.objects.filter(employee=employee).order_by("-paid_at")

        return render(request, "shifts/employee_payroll.html", {
            "employee": employee,
            "unpaid_amount": unpaid_amount,
            "unpaid_shifts_count": unpaid_shifts_count,
            "payments": payments,
            "active_page": "payroll",
        })

    # --- РЕЖИМ РАБОТОДАТЕЛЯ ---
    organization = get_owner_organization(user)
    employees = organization.employees.filter(is_active=True)
    now = timezone.now()

    payroll_data = []
    due_today_data = []
    total_unpaid_sum = Decimal("0.00")

    for emp in employees:
        emp_earned = Shift.objects.filter(
            employee=emp, status=Shift.Status.COMPLETED
        ).aggregate(total=Sum("calculated_payout"))["total"] or Decimal("0.00")

        emp_bonuses = PayrollAdjustment.objects.filter(
            employee=emp, adjustment_type=PayrollAdjustment.AdjustmentType.BONUS
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        emp_penalties = PayrollAdjustment.objects.filter(
            employee=emp, adjustment_type=PayrollAdjustment.AdjustmentType.PENALTY
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        emp_paid = PayrollPayment.objects.filter(
            employee=emp
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        total_due = Decimal(str(emp_earned)) + Decimal(str(emp_bonuses)) - Decimal(str(emp_penalties))
        emp_unpaid_sum = max(Decimal("0.00"), total_due - Decimal(str(emp_paid))).quantize(Decimal("0.01"))
        total_unpaid_sum += emp_unpaid_sum

        if emp_unpaid_sum == Decimal("0.00"):
            Shift.objects.filter(employee=emp, status=Shift.Status.COMPLETED, is_paid=False).update(is_paid=True)
            PayrollAdjustment.objects.filter(employee=emp, is_settled=False).update(is_settled=True)

        emp_unpaid_shifts = Shift.objects.filter(
            employee=emp, status=Shift.Status.COMPLETED, is_paid=False
        )
        last_payment = PayrollPayment.objects.filter(employee=emp).order_by("-paid_at").first()

        item = {
            "employee": emp,
            "unpaid_sum": emp_unpaid_sum,
            "unpaid_count": emp_unpaid_shifts.count(),
            "last_payment": last_payment,
            "is_due_today": emp.is_payout_due_today(),
        }

        payroll_data.append(item)

        if item["is_due_today"] and emp_unpaid_sum > 0:
            due_today_data.append(item)

    total_unpaid_sum = total_unpaid_sum.quantize(Decimal("0.01"))

    total_paid_this_month = PayrollPayment.objects.filter(
        organization=organization,
        paid_at__month=now.month,
        paid_at__year=now.year,
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    total_paid_this_month = Decimal(str(total_paid_this_month)).quantize(Decimal("0.01"))

    month_bonuses = PayrollAdjustment.objects.filter(
        organization=organization,
        adjustment_type=PayrollAdjustment.AdjustmentType.BONUS,
        created_at__month=now.month,
        created_at__year=now.year,
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    month_penalties = PayrollAdjustment.objects.filter(
        organization=organization,
        adjustment_type=PayrollAdjustment.AdjustmentType.PENALTY,
        created_at__month=now.month,
        created_at__year=now.year,
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    return render(request, "shifts/payroll.html", {
        "organization": organization,
        "employees": employees,
        "payroll_data": payroll_data,
        "due_today_data": due_today_data,
        "total_unpaid_sum": total_unpaid_sum,
        "total_paid_this_month": total_paid_this_month,
        "month_bonuses": Decimal(str(month_bonuses)).quantize(Decimal("0.01")),
        "month_penalties": Decimal(str(month_penalties)).quantize(Decimal("0.01")),
        "active_page": "payroll",
    })


@login_required
def process_payment(request, employee_id):
    """Process salary payout to an employee, settling unpaid shifts and adjustments."""
    if hasattr(request.user, "employee_profile"):
        messages.error(request, "У вас нет прав для проведения выплат.")
        return redirect("payroll")

    organization = get_owner_organization(request.user)
    employee = get_object_or_404(Employee, id=employee_id, organization=organization)

    if request.method == "POST":
        try:
            amount = Decimal(request.POST.get("amount", "0.00")).quantize(Decimal("0.01"))
        except (ValueError, TypeError):
            amount = Decimal("0.00")

        comment = request.POST.get("comment", "")

        if amount <= 0:
            messages.error(request, "Сумма выплаты должна быть больше нуля.")
            return redirect("payroll")

        payment = PayrollPayment.objects.create(
            organization=organization,
            employee=employee,
            amount=amount,
            comment=comment,
            created_by=request.user,
        )

        Shift.objects.filter(
            employee=employee,
            status=Shift.Status.COMPLETED,
            is_paid=False,
        ).update(is_paid=True)

        PayrollAdjustment.objects.filter(
            employee=employee,
            is_settled=False,
        ).update(is_settled=True, payment=payment)

        recipient_user = getattr(employee, "user", None)
        Notification.objects.create(
            organization=organization,
            recipient=recipient_user,
            title="Вам перечислена выплата",
            message=f"Вам выплачена сумма {amount} ₽. Чек доступен в истории выплат.",
            category=Notification.Category.PAYROLL,
            link="/shifts/payroll/",
        )

        receipt_url = f"/shifts/payroll/receipt/{payment.id}/pdf/"
        messages.success(
            request,
            mark_safe(
                f"Выплата {amount} ₽ сотруднику {employee.full_name} успешно проведена! "
                f'<a href="{receipt_url}" target="_blank" style="color: #fff; font-weight: 600; text-decoration: underline; margin-left: 0.5rem;">Скачать чек (PDF)</a>'
            )
        )

    return redirect("payroll")


@login_required
def employee_payment_history(request, employee_id):
    """Return JSON history of payments for a specific employee."""
    if hasattr(request.user, "employee_profile"):
        return JsonResponse({"error": "Forbidden"}, status=403)

    organization = get_owner_organization(request.user)
    employee = get_object_or_404(Employee, id=employee_id, organization=organization)

    payments = PayrollPayment.objects.filter(employee=employee).order_by("-paid_at")

    data = [
        {
            "id": p.id,
            "amount": str(p.amount),
            "comment": p.comment or "—",
            "paid_at": p.paid_at.strftime("%d.%m.%Y %H:%M"),
            "created_by": p.created_by.get_full_name() or p.created_by.username,
        }
        for p in payments
    ]

    return JsonResponse({
        "employee_name": employee.full_name,
        "payments": data
    })


@login_required
def employee_payout_details(request, employee_id):
    """Return detailed breakdown of unpaid shifts, active adjustments, and precise payout calculation."""
    if hasattr(request.user, "employee_profile"):
        return JsonResponse({"error": "Forbidden"}, status=403)

    organization = get_owner_organization(request.user)
    employee = get_object_or_404(Employee, id=employee_id, organization=organization)

    completed_shifts = Shift.objects.filter(
        employee=employee, status=Shift.Status.COMPLETED
    ).order_by("-opened_at")

    total_earned = Decimal("0.00")
    shifts_data = []

    for shift in completed_shifts:
        payout = shift.calculated_payout or Decimal("0.00")
        total_earned += payout
        if not shift.is_paid:
            shifts_data.append({
                "id": shift.id,
                "date": shift.opened_at.strftime("%d.%m.%Y"),
                "time": f"{shift.opened_at.strftime('%H:%M')} – {shift.closed_at.strftime('%H:%M') if shift.closed_at else '...'}",
                "payout": str(payout.quantize(Decimal("0.01"))),
            })

    all_adjustments = PayrollAdjustment.objects.filter(
        organization=organization,
        employee=employee,
    ).order_by("-created_at")

    bonuses_sum = Decimal("0.00")
    penalties_sum = Decimal("0.00")
    adjustments_data = []

    for adj in all_adjustments:
        amount = adj.amount or Decimal("0.00")
        if adj.adjustment_type == PayrollAdjustment.AdjustmentType.BONUS:
            bonuses_sum += amount
        else:
            penalties_sum += amount

        if not adj.is_settled:
            adjustments_data.append({
                "id": adj.id,
                "type": adj.adjustment_type,
                "type_label": adj.get_adjustment_type_display(),
                "amount": str(amount.quantize(Decimal("0.01"))),
                "reason": adj.reason,
                "date": adj.created_at.strftime("%d.%m.%Y"),
            })

    total_paid = PayrollPayment.objects.filter(
        employee=employee
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    total_due = total_earned + bonuses_sum - penalties_sum
    debt = max(Decimal("0.00"), total_due - Decimal(str(total_paid))).quantize(Decimal("0.01"))

    return JsonResponse({
        "employee_name": employee.full_name,
        "total_earned": str(total_earned.quantize(Decimal("0.01"))),
        "total_bonuses": str(bonuses_sum.quantize(Decimal("0.01"))),
        "total_penalties": str(penalties_sum.quantize(Decimal("0.01"))),
        "total_paid": str(total_paid.quantize(Decimal("0.01"))),
        "debt": str(debt),
        "shifts": shifts_data,
        "adjustments": adjustments_data,
    })


@login_required
def add_adjustment_api(request):
    """Ajax API endpoint to assign bonus or penalty."""
    if hasattr(request.user, "employee_profile"):
        return JsonResponse({"error": "Forbidden"}, status=403)

    organization = get_owner_organization(request.user)

    if request.method == "POST":
        employee_id = request.POST.get("employee_id")
        employee = get_object_or_404(Employee, id=employee_id, organization=organization)

        adj_type = request.POST.get("adjustment_type", "bonus")
        reason = request.POST.get("reason", "").strip()

        try:
            amount = Decimal(request.POST.get("amount", "0.00")).quantize(Decimal("0.01"))
        except (ValueError, TypeError):
            amount = Decimal("0.00")

        if amount <= 0:
            return JsonResponse({"error": "Сумма должна быть больше нуля."}, status=400)
        if not reason:
            return JsonResponse({"error": "Укажите причину назначении."}, status=400)

        PayrollAdjustment.objects.create(
            organization=organization,
            employee=employee,
            adjustment_type=adj_type,
            amount=amount,
            reason=reason,
            created_by=request.user,
        )

        type_label = "Премия" if adj_type == "bonus" else "Штраф"
        
        recipient_user = getattr(employee, "user", None)
        Notification.objects.create(
            organization=organization,
            recipient=recipient_user,
            title=f"Вам зафиксирован {type_label.lower()}",
            message=f"Зафиксирована {type_label.lower()} {amount} ₽. Причина: {reason}.",
            category=Notification.Category.PAYROLL,
            link="/shifts/payroll/",
        )

        return JsonResponse({"status": "ok", "message": f"{type_label} успешно добавлена!"})

    return JsonResponse({"error": "Invalid method"}, status=405)


@login_required
def get_adjustments_api(request):
    """Ajax API endpoint to return list of recent adjustments."""
    if hasattr(request.user, "employee_profile"):
        return JsonResponse({"error": "Forbidden"}, status=403)

    organization = get_owner_organization(request.user)
    adjustments = PayrollAdjustment.objects.filter(
        organization=organization
    ).select_related("employee", "created_by").order_by("-created_at")[:20]

    data = [
        {
            "id": adj.id,
            "employee_name": adj.employee.full_name,
            "type": adj.adjustment_type,
            "type_label": adj.get_adjustment_type_display(),
            "amount": str(adj.amount),
            "reason": adj.reason,
            "is_settled": adj.is_settled,
            "created_at": adj.created_at.strftime("%d.%m.%Y %H:%M"),
            "created_by": adj.created_by.get_full_name() if adj.created_by else "Система",
        }
        for adj in adjustments
    ]

    return JsonResponse({"adjustments": data})


@login_required
def export_payroll_csv(request):
    """Export current payroll statement as a CSV file for Excel."""
    if hasattr(request.user, "employee_profile"):
        messages.error(request, "У вас нет прав для экспорта финансовой отчетности.")
        return redirect("payroll")

    organization = get_owner_organization(request.user)
    employees = organization.employees.filter(is_active=True)

    response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    filename = f"payroll_statement_{timezone.now().strftime('%Y_%m_%d')}.csv"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    writer = csv.writer(response, delimiter=";")
    writer.writerow([
        "ФИО Сотрудника",
        "Должность",
        "График выплат",
        "Неоплачено смен",
        "К выплате (₽)",
        "Дата последней выплаты",
        "Сумма последней выплаты (₽)"
    ])

    for emp in employees:
        emp_earned = Shift.objects.filter(
            employee=emp, status=Shift.Status.COMPLETED
        ).aggregate(total=Sum("calculated_payout"))["total"] or Decimal("0.00")

        emp_bonuses = PayrollAdjustment.objects.filter(
            employee=emp, adjustment_type=PayrollAdjustment.AdjustmentType.BONUS
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        emp_penalties = PayrollAdjustment.objects.filter(
            employee=emp, adjustment_type=PayrollAdjustment.AdjustmentType.PENALTY
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        emp_paid = PayrollPayment.objects.filter(
            employee=emp
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        total_due = Decimal(str(emp_earned)) + Decimal(str(emp_bonuses)) - Decimal(str(emp_penalties))
        unpaid_sum = max(Decimal("0.00"), total_due - Decimal(str(emp_paid))).quantize(Decimal("0.01"))

        unpaid_shifts_count = Shift.objects.filter(
            employee=emp, status=Shift.Status.COMPLETED, is_paid=False
        ).count()

        last_payment = PayrollPayment.objects.filter(employee=emp).order_by("-paid_at").first()

        writer.writerow([
            emp.full_name,
            emp.position or "Сотрудник",
            emp.get_payout_frequency_display() if hasattr(emp, "get_payout_frequency_display") else "Раз в неделю",
            unpaid_shifts_count,
            str(unpaid_sum).replace(".", ","),
            last_payment.paid_at.strftime("%d.%m.%Y %H:%M") if last_payment else "Нет выплат",
            str(last_payment.amount).replace(".", ",") if last_payment else "0,00"
        ])

    return response


@login_required
def download_payment_receipt_pdf(request, payment_id):
    """Генерация стильного PDF-чека с детализацией смен, премий и штрафов."""
    user = request.user

    if hasattr(user, "employee_profile"):
        employee = user.employee_profile
        payment = get_object_or_404(PayrollPayment, id=payment_id, employee=employee)
    else:
        organization = get_owner_organization(request.user)
        payment = get_object_or_404(PayrollPayment, id=payment_id, organization=organization)

    font_path = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "arial.ttf")
    font_bold_path = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "arialbd.ttf")

    font_name = "Arial"
    font_bold_name = "Arial-Bold"

    if os.path.exists(font_path):
        try:
            pdfmetrics.registerFont(TTFont(font_name, font_path))
        except Exception:
            pass
    else:
        font_name = "Helvetica"

    if os.path.exists(font_bold_path):
        try:
            pdfmetrics.registerFont(TTFont(font_bold_name, font_bold_path))
        except Exception:
            pass
    else:
        font_bold_name = font_name

    shifts = Shift.objects.filter(
        employee=payment.employee,
        status=Shift.Status.COMPLETED,
        opened_at__lte=payment.paid_at,
    ).order_by("-opened_at")[:10]

    adjustments = PayrollAdjustment.objects.filter(
        Q(payment=payment) | Q(employee=payment.employee, is_settled=True, created_at__lte=payment.paid_at)
    ).distinct()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    story = []
    styles = getSampleStyleSheet()

    style_title = ParagraphStyle("DocTitle", fontName=font_bold_name, fontSize=16, leading=20, textColor=colors.HexColor("#111111"))
    style_subtitle = ParagraphStyle("DocSubtitle", fontName=font_name, fontSize=9, leading=12, textColor=colors.HexColor("#666666"))
    style_box_title = ParagraphStyle("BoxTitle", fontName=font_bold_name, fontSize=8, leading=10, textColor=colors.HexColor("#64748b"))
    style_body = ParagraphStyle("BodyTextCustom", fontName=font_name, fontSize=9.5, leading=13, textColor=colors.HexColor("#111111"))
    style_body_bold = ParagraphStyle("BodyBoldCustom", fontName=font_bold_name, fontSize=9.5, leading=13, textColor=colors.HexColor("#111111"))
    style_amount_val = ParagraphStyle("AmountVal", fontName=font_bold_name, fontSize=22, leading=26, alignment=1, textColor=colors.HexColor("#15803d"))
    style_amount_lbl = ParagraphStyle("AmountLbl", fontName=font_bold_name, fontSize=9, leading=12, alignment=1, textColor=colors.HexColor("#166534"))
    style_th = ParagraphStyle("TH", fontName=font_bold_name, fontSize=8, leading=10, textColor=colors.HexColor("#475569"))
    style_td = ParagraphStyle("TD", fontName=font_name, fontSize=8.5, leading=11, textColor=colors.HexColor("#111111"))
    style_td_right = ParagraphStyle("TDRight", fontName=font_bold_name, fontSize=8.5, leading=11, alignment=2, textColor=colors.HexColor("#111111"))
    style_footer = ParagraphStyle("Footer", fontName=font_name, fontSize=7.5, leading=10, textColor=colors.HexColor("#94a3b8"), alignment=4)

    # 1. Шапка
    header_left = [
        Paragraph(payment.organization.name, style_title),
        Paragraph("Официальный расчетный чек по заработной плате", style_subtitle),
    ]
    header_right = [
        Paragraph(f"Квитанция № {payment.id}", ParagraphStyle("HRight1", parent=style_body_bold, alignment=2)),
        Paragraph(f"Дата: {payment.paid_at.strftime('%d.%m.%Y %H:%M')}", ParagraphStyle("HRight2", parent=style_subtitle, alignment=2)),
    ]

    header_table = Table([[header_left, header_right]], colWidths=[110 * mm, 70 * mm])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(header_table)
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#22c55e"), spaceAfter=12))

    # 2. Инфо-блоки
    emp_pos = payment.employee.position or "Сотрудник"
    emp_freq = payment.employee.get_payout_days_display() if hasattr(payment.employee, "get_payout_days_display") else "—"
    creator = payment.created_by.get_full_name() or payment.created_by.username if payment.created_by else "Администратор"

    info_left = [
        Paragraph("СОТРУДНИК (ПОЛУЧАТЕЛЬ)", style_box_title),
        Spacer(1, 2 * mm),
        Paragraph(f"<b>{payment.employee.full_name}</b>", style_body),
        Paragraph(f"Должность: {emp_pos}", style_body),
        Paragraph(f"График выплат: {emp_freq}", style_body),
    ]

    info_right = [
        Paragraph("ВЫДАНО (РАБОТОДАТЕЛЬ)", style_box_title),
        Spacer(1, 2 * mm),
        Paragraph(f"Организация: {payment.organization.name}", style_body),
        Paragraph(f"Выдал: {creator}", style_body),
        Paragraph(f"Заметка: {payment.comment or 'Без комментариев'}", style_body),
    ]

    box_table = Table([[info_left, info_right]], colWidths=[87 * mm, 87 * mm])
    box_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#f8fafc")),
        ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (0, 0), 0.5, colors.HexColor("#e2e8f0")),
        ("BOX", (1, 0), (1, 0), 0.5, colors.HexColor("#e2e8f0")),
        ("PADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(box_table)
    story.append(Spacer(1, 10))

    # 3. Сумма
    amount_content = [
        Paragraph("ВЫПЛАЧЕННАЯ СУММА", style_amount_lbl),
        Spacer(1, 2 * mm),
        Paragraph(f"{payment.amount} руб.", style_amount_val),
    ]
    amount_table = Table([[amount_content]], colWidths=[180 * mm])
    amount_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0fdf4")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#bbf7d0")),
        ("PADDING", (0, 0), (-1, -1), 10),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    story.append(amount_table)
    story.append(Spacer(1, 12))

    # 4. Таблица смен
    story.append(Paragraph("<b>Отработанные смены в расчете:</b>", style_body))
    story.append(Spacer(1, 4))

    table_data = [[
        Paragraph("Дата смены", style_th),
        Paragraph("Время работы", style_th),
        Paragraph("Часы", style_th),
        Paragraph("Выручка", style_th),
        Paragraph("Начислено", ParagraphStyle("THRight", parent=style_th, alignment=2)),
    ]]

    for shift in shifts:
        closed_str = shift.closed_at.strftime("%H:%M") if shift.closed_at else "..."
        time_str = f"{shift.opened_at.strftime('%H:%M')} — {closed_str}"
        sales_str = f"{shift.total_sales or Decimal('0.00')} руб."
        payout_str = f"{shift.calculated_payout or Decimal('0.00')} руб."

        table_data.append([
            Paragraph(shift.opened_at.strftime("%d.%m.%Y"), style_td),
            Paragraph(time_str, style_td),
            Paragraph(f"{shift.duration_hours} ч.", style_td),
            Paragraph(sales_str, style_td),
            Paragraph(payout_str, style_td_right),
        ])

    if not shifts:
        table_data.append([
            Paragraph("Нет сведений о конкретных сменах", ParagraphStyle("NoShifts", parent=style_td, alignment=1)),
            "", "", "", ""
        ])

    shifts_table = Table(table_data, colWidths=[32 * mm, 42 * mm, 25 * mm, 43 * mm, 38 * mm])
    shifts_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#cbd5e1")),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    if not shifts:
        shifts_table.setStyle(TableStyle([("SPAN", (0, 1), (4, 1))]))

    story.append(shifts_table)

    # 5. Визуализация Премий и Штрафов в ЧЕКЕ
    if adjustments.exists():
        story.append(Spacer(1, 10))
        story.append(Paragraph("<b>Премии и удержания (штрафы):</b>", style_body))
        story.append(Spacer(1, 4))

        adj_data = [[
            Paragraph("Тип", style_th),
            Paragraph("Причина / Комментарий", style_th),
            Paragraph("Дата", style_th),
            Paragraph("Сумма", ParagraphStyle("THRight2", parent=style_th, alignment=2)),
        ]]

        for adj in adjustments:
            is_bonus = adj.adjustment_type == PayrollAdjustment.AdjustmentType.BONUS
            sign = "+" if is_bonus else "-"
            amount_str = f"{sign}{adj.amount} руб."
            color_hex = "#15803d" if is_bonus else "#b91c1c"

            style_adj_val = ParagraphStyle("AdjVal", parent=style_td_right, textColor=colors.HexColor(color_hex))

            adj_data.append([
                Paragraph(adj.get_adjustment_type_display(), style_td),
                Paragraph(adj.reason, style_td),
                Paragraph(adj.created_at.strftime("%d.%m.%Y"), style_td),
                Paragraph(amount_str, style_adj_val),
            ])

        adj_table = Table(adj_data, colWidths=[35 * mm, 80 * mm, 30 * mm, 35 * mm])
        adj_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f8fafc")),
            ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(adj_table)

    story.append(Spacer(1, 20))

    # 6. Подписи
    sig_left = Paragraph("Подпись сотрудника", ParagraphStyle("SigL", parent=style_body, alignment=1))
    sig_right = Paragraph("Подпись / Печать работодателя", ParagraphStyle("SigR", parent=style_body, alignment=1))

    sig_table = Table([[sig_left, sig_right]], colWidths=[80 * mm, 80 * mm])
    sig_table.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (0, 0), 0.5, colors.HexColor("#111111")),
        ("LINEABOVE", (1, 0), (1, 0), 0.5, colors.HexColor("#111111")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(Spacer(1, 15))
    story.append(sig_table)
    story.append(Spacer(1, 15))

    footer_text = (
        f"Документ сформирован автоматически в CRM-системе easyCRM "
        f"{timezone.now().strftime('%d.%m.%Y %H:%M')}. "
        f"Электронный чек является подтверждением проведения денежной транзакции между работодателем и сотрудником."
    )
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"), spaceAfter=6))
    story.append(Paragraph(footer_text, style_footer))

    doc.build(story)

    buffer.seek(0)
    filename = f"Receipt_PAY-{payment.id}_{payment.employee.last_name}.pdf"
    response = HttpResponse(buffer.read(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def get_notifications_api(request):
    """Возвращает список последних уведомлений текущего пользователя."""
    user = request.user
    if hasattr(user, "employee_profile"):
        emp = user.employee_profile
        org = emp.organization
        search_term = emp.last_name or emp.full_name or user.username

        notifications = Notification.objects.filter(organization=org).filter(
            Q(recipient=user) | Q(recipient__isnull=True, message__icontains=search_term)
        )
    else:
        org = get_owner_organization(user)
        notifications = Notification.objects.filter(organization=org, recipient__isnull=True)

    unread_count = notifications.filter(is_read=False).count()
    latest_notifications = notifications[:10]

    data = [
        {
            "id": n.id,
            "title": n.title,
            "message": n.message,
            "category": n.category,
            "link": n.link or "#",
            "is_read": n.is_read,
            "created_at": n.created_at.strftime("%d.%m %H:%M"),
        }
        for n in latest_notifications
    ]

    return JsonResponse({"unread_count": unread_count, "notifications": data})


@login_required
def mark_notifications_read_api(request):
    """Отмечает все уведомления текущего пользователя прочитанными."""
    user = request.user
    if hasattr(user, "employee_profile"):
        emp = user.employee_profile
        org = emp.organization
        search_term = emp.last_name or emp.full_name or user.username

        Notification.objects.filter(organization=org, is_read=False).filter(
            Q(recipient=user) | Q(recipient__isnull=True, message__icontains=search_term)
        ).update(is_read=True)
    else:
        org = get_owner_organization(user)
        Notification.objects.filter(organization=org, recipient__isnull=True, is_read=False).update(is_read=True)

    return JsonResponse({"status": "ok"})


@login_required
def export_analytics_pdf(request):
    """Генерация сводного аналитического PDF-отчёта за выбранный период."""
    if hasattr(request.user, "employee_profile"):
        return HttpResponse("Forbidden", status=403)

    organization = get_owner_organization(request.user)
    today = timezone.localdate()

    period_mode = request.GET.get("period", "this_month")
    if period_mode == "today":
        start_date, end_date = today, today
    elif period_mode == "last_7":
        start_date, end_date = today - timedelta(days=6), today
    elif period_mode == "last_30":
        start_date, end_date = today - timedelta(days=29), today
    elif period_mode == "last_month":
        first_of_this = today.replace(day=1)
        end_date = first_of_this - timedelta(days=1)
        start_date = end_date.replace(day=1)
    else:  # this_month
        start_date, end_date = today.replace(day=1), today

    completed_shifts = Shift.objects.filter(
        organization=organization,
        status=Shift.Status.COMPLETED,
        opened_at__date__gte=start_date,
        opened_at__date__lte=end_date,
    ).select_related("employee")

    adjustments = PayrollAdjustment.objects.filter(
        organization=organization,
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
    )

    total_revenue = completed_shifts.aggregate(t=Sum("total_sales"))["t"] or Decimal("0.00")
    total_shifts_payout = completed_shifts.aggregate(t=Sum("calculated_payout"))["t"] or Decimal("0.00")
    total_bonuses = adjustments.filter(adjustment_type=PayrollAdjustment.AdjustmentType.BONUS).aggregate(t=Sum("amount"))["t"] or Decimal("0.00")
    total_penalties = adjustments.filter(adjustment_type=PayrollAdjustment.AdjustmentType.PENALTY).aggregate(t=Sum("amount"))["t"] or Decimal("0.00")

    total_fot = max(Decimal("0.00"), total_shifts_payout + Decimal(str(total_bonuses)) - Decimal(str(total_penalties)))
    fot_percentage = round((total_fot / total_revenue * Decimal("100")), 1) if total_revenue > 0 else Decimal("0.0")

    total_hours = sum(s.duration_hours for s in completed_shifts)
    revenue_per_hour = (total_revenue / Decimal(str(total_hours))).quantize(Decimal("0.01")) if total_hours > 0 else Decimal("0.00")

    font_path = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "arial.ttf")
    font_bold_path = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "arialbd.ttf")

    font_name = "Arial"
    font_bold_name = "Arial-Bold"

    if os.path.exists(font_path):
        try:
            pdfmetrics.registerFont(TTFont(font_name, font_path))
        except Exception:
            pass
    else:
        font_name = "Helvetica"

    if os.path.exists(font_bold_path):
        try:
            pdfmetrics.registerFont(TTFont(font_bold_name, font_bold_path))
        except Exception:
            pass
    else:
        font_bold_name = font_name

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    story = []
    style_title = ParagraphStyle("Title", fontName=font_bold_name, fontSize=16, leading=20, textColor=colors.HexColor("#111111"))
    style_subtitle = ParagraphStyle("SubTitle", fontName=font_name, fontSize=9, leading=12, textColor=colors.HexColor("#666666"))
    style_box_lbl = ParagraphStyle("BoxLbl", fontName=font_bold_name, fontSize=8, leading=10, textColor=colors.HexColor("#64748b"))
    style_box_val = ParagraphStyle("BoxVal", fontName=font_bold_name, fontSize=14, leading=18, textColor=colors.HexColor("#111111"))
    style_th = ParagraphStyle("TH", fontName=font_bold_name, fontSize=8, leading=10, textColor=colors.HexColor("#475569"))
    style_td = ParagraphStyle("TD", fontName=font_name, fontSize=8.5, leading=11, textColor=colors.HexColor("#111111"))
    style_td_bold = ParagraphStyle("TDB", fontName=font_bold_name, fontSize=8.5, leading=11, textColor=colors.HexColor("#111111"))

    # Шапка
    header_left = [
        Paragraph(organization.name, style_title),
        Paragraph(f"Сводный финансово-аналитический отчёт ({start_date.strftime('%d.%m.%Y')} — {end_date.strftime('%d.%m.%Y')})", style_subtitle),
    ]
    header_right = [
        Paragraph("easyCRM Analytics", ParagraphStyle("HR1", parent=style_subtitle, alignment=2, fontName=font_bold_name)),
        Paragraph(f"Сформирован: {timezone.now().strftime('%d.%m.%Y %H:%M')}", ParagraphStyle("HR2", parent=style_subtitle, alignment=2)),
    ]

    header_table = Table([[header_left, header_right]], colWidths=[110 * mm, 70 * mm])
    header_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story.append(header_table)
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#facc15"), spaceAfter=12))

    # Сводка KPI (4 карточки)
    kpi1 = [Paragraph("ВЫРУЧКА", style_box_lbl), Spacer(1, 1 * mm), Paragraph(f"{total_revenue} руб.", style_box_val)]
    kpi2 = [Paragraph("ФОТ (ЗАРПЛАТЫ)", style_box_lbl), Spacer(1, 1 * mm), Paragraph(f"{total_fot} руб.", style_box_val)]
    kpi3 = [Paragraph("ДОЛЯ ФОТ", style_box_lbl), Spacer(1, 1 * mm), Paragraph(f"{fot_percentage}%", style_box_val)]
    kpi4 = [Paragraph("ВЫРУЧКА В ЧАС", style_box_lbl), Spacer(1, 1 * mm), Paragraph(f"{revenue_per_hour} руб.", style_box_val)]

    kpi_table = Table([[kpi1, kpi2, kpi3, kpi4]], colWidths=[43 * mm, 43 * mm, 43 * mm, 43 * mm])
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("PADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 14))

    # Таблица эффективности сотрудников
    story.append(Paragraph("<b>Результативность команды за период:</b>", style_td_bold))
    story.append(Spacer(1, 4))

    emp_data = [[
        Paragraph("Сотрудник", style_th),
        Paragraph("Смен / Часов", style_th),
        Paragraph("Выручка", style_th),
        Paragraph("ФОТ", style_th),
        Paragraph("Выручка/час", ParagraphStyle("TH2", parent=style_th, alignment=2)),
    ]]

    employees = organization.employees.filter(is_active=True)
    for emp in employees:
        emp_shifts = [s for s in completed_shifts if s.employee_id == emp.id]
        if not emp_shifts and period_mode != "this_month":
            continue

        emp_hours = sum(s.duration_hours for s in emp_shifts)
        emp_rev = sum((s.total_sales or Decimal("0.00") for s in emp_shifts), Decimal("0.00"))
        emp_payout = sum((s.calculated_payout or Decimal("0.00") for s in emp_shifts), Decimal("0.00"))

        emp_bonuses = sum((a.amount for a in adjustments if a.employee_id == emp.id and a.adjustment_type == PayrollAdjustment.AdjustmentType.BONUS), Decimal("0.00"))
        emp_penalties = sum((a.amount for a in adjustments if a.employee_id == emp.id and a.adjustment_type == PayrollAdjustment.AdjustmentType.PENALTY), Decimal("0.00"))
        emp_total_fot = max(Decimal("0.00"), emp_payout + emp_bonuses - emp_penalties)

        rev_h = (emp_rev / Decimal(str(emp_hours))).quantize(Decimal("0.01")) if emp_hours > 0 else Decimal("0.00")

        emp_data.append([
            Paragraph(emp.full_name, style_td_bold),
            Paragraph(f"{len(emp_shifts)} смен ({round(emp_hours, 1)} ч.)", style_td),
            Paragraph(f"{emp_rev} руб.", style_td),
            Paragraph(f"{emp_total_fot} руб.", style_td),
            Paragraph(f"{rev_h} руб./ч", ParagraphStyle("TD2", parent=style_td, alignment=2)),
        ])

    emp_table = Table(emp_data, colWidths=[45 * mm, 35 * mm, 35 * mm, 35 * mm, 30 * mm])
    emp_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("PADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(emp_table)

    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"), spaceAfter=6))
    
    footer_text = f"Документ сгенерирован автоматически в CRM-системе easyCRM. Предназначен для управляющих и совладельцев организации {organization.name}."
    story.append(Paragraph(footer_text, ParagraphStyle("Foot", fontName=font_name, fontSize=7.5, textColor=colors.HexColor("#94a3b8"))))

    doc.build(story)
    buffer.seek(0)

    filename = f"Analytics_Report_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.pdf"
    response = HttpResponse(buffer.read(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response