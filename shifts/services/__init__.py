"""Service layer for shifts app - contains business logic separated from views."""

from datetime import timedelta
from decimal import Decimal
from django.db.models import Sum, Q
from django.utils import timezone

from accounts.models import Employee
from shifts.models import (
    Event,
    Notification,
    PayrollAdjustment,
    PayrollPayment,
    Position,
    Shift,
    ShiftSchedule,
)


class ShiftReportService:
    """Сервис для формирования аналитических отчётов по сменам."""

    @staticmethod
    def get_date_range(period_mode: str):
        """Возвращает кортеж (start_date, end_date) для заданного периода."""
        today = timezone.localdate()

        if period_mode == "today":
            return today, today
        elif period_mode == "last_7":
            return today - timedelta(days=6), today
        elif period_mode == "last_30":
            return today - timedelta(days=29), today
        elif period_mode == "last_month":
            first_of_this_month = today.replace(day=1)
            end_date = first_of_this_month - timedelta(days=1)
            return end_date.replace(day=1), end_date
        else:  # this_month
            return today.replace(day=1), today

    @staticmethod
    def calculate_kpis(organization, start_date, end_date):
        """Рассчитывает ключевые показатели эффективности за период."""
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

        total_bonuses = adjustments.filter(
            adjustment_type=PayrollAdjustment.AdjustmentType.BONUS
        ).aggregate(t=Sum("amount"))["t"] or Decimal("0.00")

        total_penalties = adjustments.filter(
            adjustment_type=PayrollAdjustment.AdjustmentType.PENALTY
        ).aggregate(t=Sum("amount"))["t"] or Decimal("0.00")

        total_fot = max(
            Decimal("0.00"),
            total_shifts_payout + Decimal(str(total_bonuses)) - Decimal(str(total_penalties))
        )

        fot_percentage = round(
            (total_fot / total_revenue * Decimal("100")), 1
        ) if total_revenue > 0 else Decimal("0.0")

        total_hours = sum(s.duration_hours for s in completed_shifts)
        total_hours_dec = Decimal(str(total_hours))
        revenue_per_hour = (
            (total_revenue / total_hours_dec).quantize(Decimal("0.01"))
            if total_hours > 0 else Decimal("0.00")
        )

        return {
            "total_revenue": total_revenue.quantize(Decimal("0.01")),
            "total_fot": total_fot.quantize(Decimal("0.01")),
            "fot_percentage": fot_percentage,
            "total_hours": round(total_hours, 1),
            "revenue_per_hour": revenue_per_hour,
            "completed_shifts": completed_shifts,
            "adjustments": adjustments,
        }

    @staticmethod
    def get_chart_data(completed_shifts, start_date, end_date):
        """Генерирует данные для графиков выручки и ФОТ по дням."""
        chart_dates = []
        chart_revenues = []
        chart_fots = []

        curr_date = start_date
        while curr_date <= end_date:
            day_shifts = [s for s in completed_shifts if s.opened_at.date() == curr_date]
            day_revenue = sum(
                (s.total_sales or Decimal("0.00") for s in day_shifts),
                Decimal("0.00")
            )
            day_payout = sum(
                (s.calculated_payout or Decimal("0.00") for s in day_shifts),
                Decimal("0.00")
            )

            chart_dates.append(curr_date.strftime("%d.%m"))
            chart_revenues.append(float(day_revenue))
            chart_fots.append(float(day_payout))

            curr_date += timedelta(days=1)

        return chart_dates, chart_revenues, chart_fots

    @staticmethod
    def get_weekday_revenues(completed_shifts):
        """Агрегирует выручку по дням недели."""
        weekday_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        weekday_revenues = [0.0] * 7

        for s in completed_shifts:
            w_idx = s.opened_at.weekday()
            weekday_revenues[w_idx] += float(s.total_sales or Decimal("0.00"))

        return weekday_names, weekday_revenues

    @staticmethod
    def get_employee_stats(employees, completed_shifts, adjustments, period_mode):
        """Рассчитывает статистику по каждому сотруднику."""
        employee_stats = []

        for emp in employees:
            emp_shifts = [s for s in completed_shifts if s.employee_id == emp.id]
            if not emp_shifts and period_mode != "this_month":
                continue

            emp_shifts_count = len(emp_shifts)
            emp_hours = sum(s.duration_hours for s in emp_shifts)

            emp_revenue = sum(
                (s.total_sales or Decimal("0.00") for s in emp_shifts),
                Decimal("0.00")
            )
            emp_payout = sum(
                (s.calculated_payout or Decimal("0.00") for s in emp_shifts),
                Decimal("0.00")
            )

            emp_bonuses = sum(
                (a.amount for a in adjustments
                 if a.employee_id == emp.id and a.adjustment_type == PayrollAdjustment.AdjustmentType.BONUS),
                Decimal("0.00")
            )
            emp_penalties = sum(
                (a.amount for a in adjustments
                 if a.employee_id == emp.id and a.adjustment_type == PayrollAdjustment.AdjustmentType.PENALTY),
                Decimal("0.00")
            )

            emp_total_fot = max(
                Decimal("0.00"),
                emp_payout + emp_bonuses - emp_penalties
            )
            emp_rev_per_hour = (
                (emp_revenue / Decimal(str(emp_hours))).quantize(Decimal("0.01"))
                if emp_hours > 0 else Decimal("0.00")
            )

            employee_stats.append({
                "employee": emp,
                "shifts_count": emp_shifts_count,
                "hours": round(emp_hours, 1),
                "revenue": emp_revenue.quantize(Decimal("0.01")),
                "fot": emp_total_fot.quantize(Decimal("0.01")),
                "rev_per_hour": emp_rev_per_hour,
            })

        employee_stats.sort(key=lambda x: x["revenue"], reverse=True)
        return employee_stats


class PayrollService:
    """Сервис для расчётов заработной платы и выплат."""

    @staticmethod
    def calculate_employee_payroll(employee):
        """Рассчитывает полную информацию о зарплате сотрудника."""
        from accounts.models import Employee

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

        return {
            "total_earned": total_earned,
            "total_bonuses": total_bonuses,
            "total_penalties": total_penalties,
            "total_paid": total_paid,
            "total_due": total_due,
            "unpaid_amount": unpaid_amount,
        }

    @staticmethod
    def mark_as_paid_if_zero_debt(employee):
        """Отмечает смены и корректировки как оплаченные, если долга нет."""
        payroll_info = PayrollService.calculate_employee_payroll(employee)

        if payroll_info["unpaid_amount"] == Decimal("0.00"):
            Shift.objects.filter(
                employee=employee, status=Shift.Status.COMPLETED, is_paid=False
            ).update(is_paid=True)

            PayrollAdjustment.objects.filter(
                employee=employee, is_settled=False
            ).update(is_settled=True)

    @staticmethod
    def get_unpaid_shifts_count(employee):
        """Возвращает количество неоплаченных смен сотрудника."""
        return Shift.objects.filter(
            employee=employee, status=Shift.Status.COMPLETED, is_paid=False
        ).count()

    @staticmethod
    def calculate_organization_payroll(organization):
        """Рассчитывает сводную зарплатную ведомость по организации."""
        employees = organization.employees.filter(is_active=True)
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

            # Авто-маркировка оплаченных
            if emp_unpaid_sum == Decimal("0.00"):
                Shift.objects.filter(
                    employee=emp, status=Shift.Status.COMPLETED, is_paid=False
                ).update(is_paid=True)
                PayrollAdjustment.objects.filter(
                    employee=emp, is_settled=False
                ).update(is_settled=True)

            emp_unpaid_shifts = Shift.objects.filter(
                employee=emp, status=Shift.Status.COMPLETED, is_paid=False
            )
            last_payment = PayrollPayment.objects.filter(
                employee=emp
            ).order_by("-paid_at").first()

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

        return {
            "payroll_data": payroll_data,
            "due_today_data": due_today_data,
            "total_unpaid_sum": total_unpaid_sum.quantize(Decimal("0.01")),
            "employees": employees,
        }

    @staticmethod
    def get_monthly_totals(organization, month=None, year=None):
        """Возвращает totals по выплатам, бонусам и штрафам за месяц."""
        now = timezone.now()
        if month is None:
            month = now.month
        if year is None:
            year = now.year

        total_paid_this_month = PayrollPayment.objects.filter(
            organization=organization,
            paid_at__month=month,
            paid_at__year=year,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        month_bonuses = PayrollAdjustment.objects.filter(
            organization=organization,
            adjustment_type=PayrollAdjustment.AdjustmentType.BONUS,
            created_at__month=month,
            created_at__year=year,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        month_penalties = PayrollAdjustment.objects.filter(
            organization=organization,
            adjustment_type=PayrollAdjustment.AdjustmentType.PENALTY,
            created_at__month=month,
            created_at__year=year,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        return {
            "total_paid": Decimal(str(total_paid_this_month)).quantize(Decimal("0.01")),
            "bonuses": Decimal(str(month_bonuses)).quantize(Decimal("0.01")),
            "penalties": Decimal(str(month_penalties)).quantize(Decimal("0.01")),
        }

    @staticmethod
    def process_payment(organization, employee, amount, comment="", created_by=None):
        """Проводит выплату сотруднику и маркирует связанные смены/корректировки."""
        from decimal import InvalidOperation

        try:
            amount = Decimal(amount).quantize(Decimal("0.01"))
        except (ValueError, TypeError, InvalidOperation):
            amount = Decimal("0.00")

        if amount <= 0:
            raise ValueError("Сумма выплаты должна быть больше нуля")

        payment = PayrollPayment.objects.create(
            organization=organization,
            employee=employee,
            amount=amount,
            comment=comment,
            created_by=created_by,
        )

        # Маркируем смены как оплаченные
        Shift.objects.filter(
            employee=employee,
            status=Shift.Status.COMPLETED,
            is_paid=False,
        ).update(is_paid=True)

        # Маркируем корректировки как погашенные
        PayrollAdjustment.objects.filter(
            employee=employee,
            is_settled=False,
        ).update(is_settled=True, payment=payment)

        # Создаём уведомление
        recipient_user = getattr(employee, "user", None)
        Notification.objects.create(
            organization=organization,
            recipient=recipient_user,
            title="Вам перечислена выплата",
            message=f"Вам выплачена сумма {amount} ₽. Чек доступен в истории выплат.",
            category=Notification.Category.PAYROLL,
            link="/shifts/payroll/",
        )

        return payment

    @staticmethod
    def get_payout_details(employee):
        """Возвращает детальную расшифровку выплат для сотрудника."""
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
            employee=employee
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

        return {
            "total_earned": total_earned.quantize(Decimal("0.01")),
            "total_bonuses": bonuses_sum.quantize(Decimal("0.01")),
            "total_penalties": penalties_sum.quantize(Decimal("0.01")),
            "total_paid": total_paid.quantize(Decimal("0.01")),
            "debt": debt,
            "shifts": shifts_data,
            "adjustments": adjustments_data,
        }


class ScheduleService:
    """Сервис для управления графиками смен."""

    @staticmethod
    def create_shift_series(
        organization,
        employee,
        start_date,
        start_time,
        end_time,
        note,
        repeat_mode,
        repeat_until,
        work_days=None,
        rest_days=None,
    ):
        """Создаёт серию смен по графику повторения."""
        if repeat_mode == "2/2":
            w_days, r_days = 2, 2
        elif repeat_mode == "3/3":
            w_days, r_days = 3, 3
        else:
            w_days = work_days or 1
            r_days = rest_days or 1

        created_count = 0
        curr_date = start_date

        while curr_date <= repeat_until:
            for _ in range(w_days):
                if curr_date > repeat_until:
                    break

                ShiftSchedule.objects.create(
                    organization=organization,
                    employee=employee,
                    date=curr_date,
                    start_time=start_time,
                    end_time=end_time,
                    note=note,
                    status=ShiftSchedule.Status.APPROVED,
                )
                created_count += 1
                curr_date += timedelta(days=1)

            curr_date += timedelta(days=r_days)

        return created_count

    @staticmethod
    def get_schedule_for_month(organization, year, month):
        """Возвращает все смены и события за месяц, сгруппированные по датам."""
        schedules = ShiftSchedule.objects.filter(
            organization=organization,
            date__year=year,
            date__month=month,
        ).select_related("employee", "replaced_by")

        events = Event.objects.filter(
            organization=organization,
            date__year=year,
            date__month=month,
        ).prefetch_related("target_positions")

        items_by_date = {}
        for sch in schedules:
            items_by_date.setdefault(sch.date, []).append({"type": "shift", "data": sch})
        for ev in events:
            items_by_date.setdefault(ev.date, []).append({"type": "event", "data": ev})

        return items_by_date

    @staticmethod
    def get_completed_shifts_set(organization, year, month):
        """Возвращает set кортежей (employee_id, date_str) завершённых смен."""
        completed_shifts = Shift.objects.filter(
            organization=organization,
            status=Shift.Status.COMPLETED,
            opened_at__year=year,
            opened_at__month=month,
        ).values_list("employee_id", "opened_at__date")

        return {
            (emp_id, dt.strftime("%Y-%m-%d"))
            for emp_id, dt in completed_shifts if dt
        }

    @staticmethod
    def notify_about_event(organization, event_obj, employees=None):
        """Рассылает уведомления о событии сотрудникам."""
        if employees is None:
            employees = Employee.objects.filter(
                organization=organization, is_active=True
            )

        # Фильтрация по должностям, если указаны
        position_ids = list(event_obj.target_positions.values_list("id", flat=True))
        if position_ids:
            target_positions = Position.objects.filter(id__in=position_ids)
            target_names = list(target_positions.values_list("name", flat=True))
            employees = employees.filter(position__in=target_names)

        from datetime import datetime
        formatted_date = event_obj.date.strftime("%d.%m.%Y")

        notifications_to_create = []
        for emp in employees:
            recipient_user = getattr(emp, "user", None)
            if recipient_user:
                notifications_to_create.append(
                    Notification(
                        organization=organization,
                        recipient=recipient_user,
                        title=f"Событие: {event_obj.title}",
                        message=f"Запланировано событие на {formatted_date}: {event_obj.title}. {event_obj.description}".strip(),
                        category=Notification.Category.SCHEDULE,
                        link="/shifts/schedule/",
                    )
                )

        if notifications_to_create:
            Notification.objects.bulk_create(notifications_to_create)

        event_obj.is_notification_sent = True
        event_obj.save(update_fields=["is_notification_sent"])
