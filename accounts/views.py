"""HTTP views for authentication, entry page, dashboard, and employee management."""

import secrets
from datetime import datetime
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from shifts.models import Shift, ShiftSchedule
from .forms import EmployeeForm, OrganizationRegistrationForm, SignInForm
from .models import Employee, Organization


def get_owner_organization(user):
    """Return the organisation owned by the logged-in employer or show a standard 404 response."""
    return get_object_or_404(Organization, owner=user)


def user_login(request):
    """Authenticate and log in a user."""
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        form = SignInForm(request=request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            messages.success(request, "Добро пожаловать!")
            return redirect("dashboard")
        else:
            messages.error(request, "Неверный логин или пароль.")

    return redirect("landing")


def user_logout(request):
    """Log out the user and redirect to landing."""
    logout(request)
    messages.info(request, "Вы успешно вышли из системы.")
    return redirect("landing")


def landing(request):
    """Render the minimal entry page and process either login or registration."""
    if request.user.is_authenticated:
        return redirect("dashboard")

    active_tab = "login"
    login_form = SignInForm(request=request)
    registration_form = OrganizationRegistrationForm()

    if request.method == "POST":
        form_type = request.POST.get("form_type")
        if form_type == "login":
            login_form = SignInForm(request=request, data=request.POST)
            if login_form.is_valid():
                login(request, login_form.get_user())
                return redirect("dashboard")
        elif form_type == "registration":
            active_tab = "registration"
            registration_form = OrganizationRegistrationForm(request.POST)
            if registration_form.is_valid():
                with transaction.atomic():
                    user = registration_form.save()
                    Organization.objects.create(
                        name=registration_form.cleaned_data["organization_name"],
                        owner=user,
                    )
                login(request, user)
                return redirect("dashboard")

    return render(
        request,
        "accounts/landing.html",
        {
            "login_form": login_form,
            "registration_form": registration_form,
            "active_tab": active_tab,
        },
    )


@login_required
def dashboard(request):
    """Render the employer's dashboard with live shift metrics and scheduled shifts."""
    if hasattr(request.user, "employee_profile"):
        return redirect("employee-dashboard")

    organization = Organization.objects.filter(owner=request.user).first()
    if not organization:
        organization = get_owner_organization(request.user)

    now = timezone.now()
    today = timezone.localdate()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    today_shifts = Shift.objects.filter(
        organization=organization,
        opened_at__gte=today_start,
    )

    open_shifts = today_shifts.filter(status=Shift.Status.OPEN)
    completed_shifts = today_shifts.filter(status=Shift.Status.COMPLETED)

    planned_count = ShiftSchedule.objects.filter(
        organization=organization,
        date=today,
    ).count()

    today_summary = {
        "planned": planned_count,
        "open": open_shifts.count(),
        "completed": completed_shifts.count(),
    }

    recent_completed = Shift.objects.filter(
        organization=organization,
        status=Shift.Status.COMPLETED,
    ).select_related("employee")[:5]

    return render(
        request,
        "accounts/dashboard.html",
        {
            "organization": organization,
            "today_summary": today_summary,
            "open_shifts": open_shifts,
            "recent_completed": recent_completed,
            "active_page": "dashboard",
        },
    )


@login_required
def employee_dashboard(request):
    """Render the personal dashboard for an employee with upcoming schedule, shift control, and stats."""
    employee = getattr(request.user, "employee_profile", None)
    if not employee:
        return redirect("dashboard")

    now = timezone.now()
    today = now.date()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    active_shift = Shift.objects.filter(employee=employee, status=Shift.Status.OPEN).first()

    completed_shifts = Shift.objects.filter(
        employee=employee,
        status=Shift.Status.COMPLETED,
    )

    # 1. Расчёт за текущий месяц
    month_shifts = completed_shifts.filter(opened_at__gte=month_start)
    month_payout_raw = month_shifts.aggregate(Sum("calculated_payout"))["calculated_payout__sum"] or 0
    month_payout = Decimal(str(month_payout_raw)).quantize(Decimal("0.01"))
    month_hours = sum(shift.duration_hours for shift in month_shifts)

    # 2. Расчёт за ВСЁ время
    total_payout_raw = completed_shifts.aggregate(Sum("calculated_payout"))["calculated_payout__sum"] or 0
    total_payout = Decimal(str(total_payout_raw)).quantize(Decimal("0.01"))
    total_hours = sum(shift.duration_hours for shift in completed_shifts)

    # 3. Фильтрация по произвольному диапазону дат
    date_from_str = request.GET.get("date_from", "")
    date_to_str = request.GET.get("date_to", "")

    custom_shifts = completed_shifts
    has_custom_filter = False

    if date_from_str:
        try:
            df = datetime.strptime(date_from_str, "%Y-%m-%d")
            custom_shifts = custom_shifts.filter(opened_at__gte=df)
            has_custom_filter = True
        except ValueError:
            pass

    if date_to_str:
        try:
            dt = datetime.strptime(date_to_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            custom_shifts = custom_shifts.filter(opened_at__lte=dt)
            has_custom_filter = True
        except ValueError:
            pass

    if has_custom_filter:
        custom_payout_raw = custom_shifts.aggregate(Sum("calculated_payout"))["calculated_payout__sum"] or 0
        custom_payout = Decimal(str(custom_payout_raw)).quantize(Decimal("0.01"))
        custom_hours = sum(shift.duration_hours for shift in custom_shifts)
        custom_count = custom_shifts.count()
    else:
        custom_payout = Decimal("0.00")
        custom_hours = 0
        custom_count = 0

    stats = {
        "month_shifts_count": month_shifts.count(),
        "month_hours": round(month_hours, 2),
        "month_payout": month_payout,
        "total_shifts_count": completed_shifts.count(),
        "total_hours": round(total_hours, 2),
        "total_payout": total_payout,
        "custom_payout": custom_payout,
        "custom_hours": round(custom_hours, 2),
        "custom_count": custom_count,
        "has_custom_filter": has_custom_filter,
    }

    upcoming_schedule = ShiftSchedule.objects.filter(
        employee=employee,
        date__gte=today,
    ).order_by("date", "start_time").first()

    recent_shifts = completed_shifts.order_by("-opened_at")[:5]

    return render(
        request,
        "accounts/employee_dashboard.html",
        {
            "employee": employee,
            "organization": employee.organization,
            "active_shift": active_shift,
            "recent_shifts": recent_shifts,
            "upcoming_schedule": upcoming_schedule,
            "today": today,
            "stats": stats,
            "date_from": date_from_str,
            "date_to": date_to_str,
        },
    )


@login_required
def employee_list(request):
    """Show only employees that belong to the current employer's organisation."""
    organization = get_owner_organization(request.user)
    return render(
        request,
        "accounts/employee_list.html",
        {
            "organization": organization,
            "employees": organization.employees.all(),
            "active_page": "employees",
        },
    )


@login_required
def employee_create(request):
    """Create a team member with a unique user login and return the employer to their employee list."""
    organization = get_owner_organization(request.user)
    form = EmployeeForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            employee = form.save(commit=False)
            employee.organization = organization
            employee.is_active = True

            email = form.cleaned_data.get("email")
            phone = form.cleaned_data.get("phone") or ""
            clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")

            base_username = email if email else f"emp_{clean_phone}"
            if not base_username or base_username == "emp_":
                base_username = f"emp_{secrets.token_hex(3)}"

            username = base_username
            counter = 1

            while User.objects.filter(username=username).exists():
                user_obj = User.objects.get(username=username)
                if not hasattr(user_obj, "employee_profile"):
                    break
                username = f"{base_username}_{counter}"
                counter += 1

            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": employee.first_name,
                    "last_name": employee.last_name,
                    "email": email or "",
                },
            )

            raw_password = form.cleaned_data.get("password") or secrets.token_hex(4)
            user.set_password(raw_password)
            user.save()

            employee.user = user
            employee.save()

            # Локальный импорт Position для предотвращения циклического импорта
            from shifts.models import Position
            if employee.position and employee.position.strip():
                Position.objects.get_or_create(
                    organization=organization,
                    name=employee.position.strip(),
                )

        messages.success(
            request,
            f"Сотрудник «{employee.full_name}» добавлен. Логин: {username}, Пароль: {raw_password}",
        )
        return redirect("employees")

    return render(
        request,
        "accounts/employee_form.html",
        {
            "organization": organization,
            "form": form,
            "active_page": "employees",
            "is_edit": False,
        },
    )


def get_organization_employee(organization, employee_id):
    """Fetch an employee only when it belongs to the logged-in owner's organisation."""
    return get_object_or_404(Employee, pk=employee_id, organization=organization)


@login_required
def employee_detail(request, employee_id):
    """Show employee details, earnings metrics with custom date filtering, and shift history."""
    organization = get_owner_organization(request.user)
    employee = get_organization_employee(organization, employee_id)

    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    completed_shifts = Shift.objects.filter(
        employee=employee,
        status=Shift.Status.COMPLETED,
    )

    month_shifts = completed_shifts.filter(opened_at__gte=month_start)
    month_payout_raw = month_shifts.aggregate(Sum("calculated_payout"))["calculated_payout__sum"] or 0
    month_payout = Decimal(str(month_payout_raw)).quantize(Decimal("0.01"))
    month_hours = sum(shift.duration_hours for shift in month_shifts)

    total_payout_raw = completed_shifts.aggregate(Sum("calculated_payout"))["calculated_payout__sum"] or 0
    total_payout = Decimal(str(total_payout_raw)).quantize(Decimal("0.01"))
    total_hours = sum(shift.duration_hours for shift in completed_shifts)

    date_from_str = request.GET.get("date_from", "")
    date_to_str = request.GET.get("date_to", "")

    custom_shifts = completed_shifts
    has_custom_filter = False

    if date_from_str:
        try:
            df = datetime.strptime(date_from_str, "%Y-%m-%d")
            custom_shifts = custom_shifts.filter(opened_at__gte=df)
            has_custom_filter = True
        except ValueError:
            pass

    if date_to_str:
        try:
            dt = datetime.strptime(date_to_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            custom_shifts = custom_shifts.filter(opened_at__lte=dt)
            has_custom_filter = True
        except ValueError:
            pass

    if has_custom_filter:
        custom_payout_raw = custom_shifts.aggregate(Sum("calculated_payout"))["calculated_payout__sum"] or 0
        custom_payout = Decimal(str(custom_payout_raw)).quantize(Decimal("0.01"))
        custom_hours = sum(shift.duration_hours for shift in custom_shifts)
        custom_count = custom_shifts.count()
    else:
        custom_payout = Decimal("0.00")
        custom_hours = 0
        custom_count = 0

    stats = {
        "month_shifts_count": month_shifts.count(),
        "month_hours": round(month_hours, 2),
        "month_payout": month_payout,
        "total_shifts_count": completed_shifts.count(),
        "total_hours": round(total_hours, 2),
        "total_payout": total_payout,
        "custom_payout": custom_payout,
        "custom_hours": round(custom_hours, 2),
        "custom_count": custom_count,
        "has_custom_filter": has_custom_filter,
    }

    recent_shifts = completed_shifts.order_by("-opened_at")[:5]

    return render(
        request,
        "accounts/employee_detail.html",
        {
            "organization": organization,
            "employee": employee,
            "stats": stats,
            "recent_shifts": recent_shifts,
            "date_from": date_from_str,
            "date_to": date_to_str,
            "active_page": "employees",
        },
    )


@login_required
def employee_edit(request, employee_id):
    """Update existing employee information without creating a duplicate record."""
    organization = get_owner_organization(request.user)
    employee = get_organization_employee(organization, employee_id)
    form = EmployeeForm(request.POST or None, instance=employee)

    if request.method == "POST" and form.is_valid():
        form.save()

        # Локальный импорт Position для предотвращения циклического импорта
        from shifts.models import Position
        if employee.position and employee.position.strip():
            Position.objects.get_or_create(
                organization=organization,
                name=employee.position.strip(),
            )

        messages.success(request, f"Данные и финансовые настройки сотрудника «{employee.full_name}» обновлены.")
        return redirect("employee-detail", employee_id=employee.id)

    return render(
        request,
        "accounts/employee_form.html",
        {
            "organization": organization,
            "form": form,
            "employee": employee,
            "active_page": "employees",
            "is_edit": True,
        },
    )


@login_required
def employee_deactivate(request, employee_id):
    """Deactivate an employee through a POST-only action, preserving all stored information."""
    organization = get_owner_organization(request.user)
    employee = get_organization_employee(organization, employee_id)

    if request.method == "POST":
        employee.is_active = False
        employee.save(update_fields=["is_active"])
        messages.success(request, f"Сотрудник «{employee.full_name}» отключён от активной команды.")
        return redirect("employees")

    return redirect("employee-detail", employee_id=employee.id)


@login_required
def employee_reset_password(request, employee_id):
    """Generate a new temporary password for the employee and display it to the employer."""
    organization = get_owner_organization(request.user)
    employee = get_organization_employee(organization, employee_id)

    if request.method == "POST":
        new_password = secrets.token_hex(4)
        employee.user.set_password(new_password)
        employee.user.save()
        messages.success(
            request,
            f"Новый пароль для {employee.full_name}: {new_password}",
        )

    return redirect("employee-detail", employee_id=employee.id)


@login_required
def employee_delete(request, employee_id):
    """Permanently delete an employee and their associated user account."""
    organization = get_owner_organization(request.user)
    employee = get_organization_employee(organization, employee_id)

    if request.method == "POST":
        full_name = employee.full_name
        user_account = employee.user

        employee.delete()

        if user_account:
            user_account.delete()

        messages.success(request, f"Сотрудник «{full_name}» полностью удалён из системы.")
        return redirect("employees")

    return redirect("employee-detail", employee_id=employee.id)