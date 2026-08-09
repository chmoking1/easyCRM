"""HTTP views for the public entry page and its two forms."""

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from .forms import EmployeeForm, OrganizationRegistrationForm, SignInForm
from .models import Employee, Organization


def get_owner_organization(user):
    """Return the organisation owned by the logged-in employer or show a standard 404 response."""
    return get_object_or_404(Organization, owner=user)


def landing(request):
    """Render the minimal entry page and process either login or registration."""
    # The active tab helps the template keep the correct form visible after validation errors.
    active_tab = "login"
    login_form = SignInForm(request=request)
    registration_form = OrganizationRegistrationForm()

    if request.method == "POST":
        # One endpoint serves both forms; a hidden field makes the user's intent unambiguous.
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
                # User and organisation must be saved together to avoid incomplete registrations.
                with transaction.atomic():
                    user = registration_form.save()
                    Organization.objects.create(name=registration_form.cleaned_data["organization_name"], owner=user)
                login(request, user)
                return redirect("dashboard")

    return render(request, "accounts/landing.html", {"login_form": login_form, "registration_form": registration_form, "active_tab": active_tab})


@login_required
def dashboard(request):
    """Render the employer's initial dashboard for their organisation."""
    # Every registered owner receives one organisation during the first product flow.
    organization = get_owner_organization(request.user)

    # Shift and employee models are the next product milestone; these zero values deliberately
    # describe a new organisation truthfully until those records exist.
    today_summary = {
        "planned": 0,
        "open": 0,
        "completed": 0,
    }

    return render(request, "accounts/dashboard.html", {
        "organization": organization,
        "today_summary": today_summary,
        "active_page": "dashboard",
    })


@login_required
def employee_list(request):
    """Show only employees that belong to the current employer's organisation."""
    organization = get_owner_organization(request.user)
    return render(request, "accounts/employee_list.html", {
        "organization": organization,
        "employees": organization.employees.all(),
        "active_page": "employees",
    })


@login_required
def employee_create(request):
    """Create a team member and return the employer to their employee list."""
    organization = get_owner_organization(request.user)
    form = EmployeeForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        # The browser never submits an organisation ID, preventing cross-organisation creation.
        employee = form.save(commit=False)
        employee.organization = organization
        employee.save()
        messages.success(request, f"Сотрудник «{employee.full_name}» добавлен.")
        return redirect("employees")

    return render(request, "accounts/employee_form.html", {
        "organization": organization,
        "form": form,
        "active_page": "employees",
        "is_edit": False,
    })


def get_organization_employee(organization, employee_id):
    """Fetch an employee only when it belongs to the logged-in owner's organisation."""
    return get_object_or_404(Employee, pk=employee_id, organization=organization)


@login_required
def employee_detail(request, employee_id):
    """Show the employee's current contacts, compensation terms, and active status."""
    organization = get_owner_organization(request.user)
    employee = get_organization_employee(organization, employee_id)
    return render(request, "accounts/employee_detail.html", {
        "organization": organization,
        "employee": employee,
        "active_page": "employees",
    })


@login_required
def employee_edit(request, employee_id):
    """Update existing employee information without creating a duplicate record."""
    organization = get_owner_organization(request.user)
    employee = get_organization_employee(organization, employee_id)
    form = EmployeeForm(request.POST or None, instance=employee)

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Данные сотрудника обновлены.")
        return redirect("employee-detail", employee_id=employee.id)

    return render(request, "accounts/employee_form.html", {
        "organization": organization,
        "form": form,
        "employee": employee,
        "active_page": "employees",
        "is_edit": True,
    })


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

    # A direct GET has no state-changing side effect and goes back to the employee card.
    return redirect("employee-detail", employee_id=employee.id)
