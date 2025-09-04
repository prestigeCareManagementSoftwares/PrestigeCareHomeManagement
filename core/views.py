import json
import logging
import os
import tempfile
from email.quoprimime import unquote
from http.cookiejar import logger

import imgkit
from PIL import Image
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q
from django.forms import model_to_dict
from django.http import HttpResponseForbidden, FileResponse, Http404
from django.views.decorators.csrf import csrf_exempt
import requests
from django.views.decorators.http import require_POST, require_GET
from weasyprint import HTML
from weasyprint.text.fonts import FontConfiguration

from carehome_project import settings
from core.utils import get_or_create_latest_log, get_filtered_queryset, generate_shift_times, delete_image_file
from .models import CustomUser, LatestLogEntry, Mapping, MissedLog
from .forms import ServiceUserForm, StaffCreationForm, CareHomeForm, MappingForm, StaffEditForm
from io import BytesIO
from django.template.loader import render_to_string
from django.http import HttpResponse
from xhtml2pdf import pisa
from .models import ABCForm, IncidentReport
from .forms import ABCFormForm, IncidentReportForm
from django.contrib import messages
from datetime import datetime, timedelta, date
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from .models import CareHome, ServiceUser, LogEntry
from .forms import LogEntryForm
from django.http import JsonResponse
from datetime import time

def get_shifts_from_carehome(carehome):
    from datetime import datetime, timedelta, date

    if not carehome or not carehome.day_shift_start:
        return []

    start = carehome.day_shift_start
    day_end = (datetime.combine(date.today(), start) + timedelta(hours=12)).time()
    night_end = (datetime.combine(date.today(), start) + timedelta(hours=24)).time()

    return [
        f"Day Shift ({start.strftime('%I:%M %p')} - {day_end.strftime('%I:%M %p')})",
        f"Night Shift ({day_end.strftime('%I:%M %p')} - {night_end.strftime('%I:%M %p')})"
    ]


def create_log_view(request):
    carehomes = CareHome.objects.all()
    selected_carehome_id = request.GET.get('carehome') or request.POST.get('carehome')
    service_users = []
    shifts = []

    selected_carehome = None
    if selected_carehome_id:
        try:
            selected_carehome = CareHome.objects.get(id=selected_carehome_id)
            service_users = ServiceUser.objects.filter(carehome=selected_carehome)
            shifts = get_shifts_from_carehome(selected_carehome)
        except CareHome.DoesNotExist:
            messages.error(request, "Selected carehome does not exist.")

    if request.method == 'POST' and 'start_log' in request.POST:
        carehome_id = request.POST.get('carehome')
        shift = request.POST.get('shift')
        service_user_id = request.POST.get('service_user')

        if not all([carehome_id, shift, service_user_id]):
            messages.error(request, "All fields are required.")
        else:
            request.session['log_info'] = {
                'carehome_id': carehome_id,
                'shift': shift,
                'service_user_id': service_user_id
            }
            return redirect('log-entry-form')

    return render(request, 'pdf_templates/select_log_data.html', {
        'carehomes': carehomes,
        'service_users': service_users,
        'shifts': shifts,
        'selected_carehome_id': selected_carehome_id,
    })


def render_pdf_view(template_src, context_dict):
    html = render_to_string(template_src, context_dict)
    result = BytesIO()
    pdf = pisa.pisaDocument(BytesIO(html.encode("UTF-8")), result)
    if not pdf.err:
        return HttpResponse(result.getvalue(), content_type='application/pdf')
    return HttpResponse('Error generating PDF', status=500)


logger = logging.getLogger(__name__)


@login_required
def abc_form_list(request):
    """Show list of forms with visibility control"""
    if request.user.is_superuser:
        forms = ABCForm.objects.all().order_by('-date_time')
    elif request.user.groups.filter(name='Supervisors').exists():
        forms = ABCForm.objects.filter(
            Q(service_user__in=request.user.managed_clients.all()) |
            Q(created_by=request.user)
        ).order_by('-date_time')
    else:  # Regular care staff
        forms = ABCForm.objects.filter(
            created_by=request.user
        ).order_by('-date_time')

    # Add select_related for performance
    forms = forms.select_related('service_user', 'created_by')

    return render(request, 'forms/abc_form_list.html', {
        'forms': forms,
        'can_edit': lambda form: (
                request.user.is_superuser or
                request.user.groups.filter(name='Supervisors').exists()
        )
    })


@login_required
def view_abc_form(request, form_id):  # Changed from pk to form_id
    form_instance = get_object_or_404(ABCForm, pk=form_id)

    # Check permissions
    if not (request.user.is_superuser or
            request.user == form_instance.created_by or
            (request.user.groups.filter(name='Supervisors').exists() and
             form_instance.service_user in request.user.managed_clients.all())):
        return HttpResponseForbidden("You don't have permission to view this form")

    context = {
        'data': {
            'id': form_instance.id,
            'service_user': form_instance.service_user,
            'date_of_birth': form_instance.date_of_birth,
            'staff': form_instance.staff,
            'date_time': form_instance.date_time,
            'target_behaviours': form_instance.target_behaviours,
            'setting': form_instance.setting,
            'antecedent': form_instance.antecedent,
            'behaviour': form_instance.behaviour,
            'consequences': form_instance.consequences,
            'reflection': form_instance.reflection,
            'pdf_file': form_instance.pdf_file
        },
        'can_edit': (
                request.user.is_superuser or
                request.user.groups.filter(name='Supervisors').exists() or
                request.user == form_instance.created_by
        )
    }
    return render(request, 'core/abc_form_detail_template.html', context)


@login_required
def download_abc_pdf(request, form_id):
    """Download PDF with permission check"""
    instance = get_object_or_404(ABCForm, id=form_id)

    # Permission check
    if not (request.user.is_superuser or
            request.user == instance.created_by or
            request.user.groups.filter(name='Supervisors').exists() and
            instance.service_user in request.user.managed_clients.all()):
        return HttpResponse("Not authorized", status=403)

    if not instance.pdf_file:
        return HttpResponse("PDF not available", status=404)

    response = HttpResponse(instance.pdf_file, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="abc_form_{instance.id}.pdf"'
    return response


@login_required
def fill_abc_form(request):
    if request.method == 'POST':
        form = ABCFormForm(request.POST)
        if form.is_valid():
            try:
                # Save the form - the combining of fields is now handled in form.save()
                instance = form.save(commit=False)
                instance.created_by = request.user
                instance.save()
                form.save_m2m()  # Save many-to-many relationships (target_behaviours)

                # PDF Generation
                context = {
                    'data': {
                        'target_behaviours': form.cleaned_data['target_behaviours'],
                        'service_user': instance.service_user,
                        'date_of_birth': instance.date_of_birth,
                        'staff': instance.staff,
                        'date_time': instance.date_time,
                        'setting': instance.setting,
                        'antecedent': instance.antecedent,
                        'behaviour': instance.behaviour,
                        'consequences': instance.consequences,
                        'reflection': instance.reflection
                    }
                }

                html_string = render_to_string('pdf_templates/abc_pdf.html', context)
                pdf_bytes = HTML(string=html_string).write_pdf()

                # Delete old PDF if exists (for edit case)
                if hasattr(instance, 'pdf_file') and instance.pdf_file:
                    instance.pdf_file.delete()

                # Save new PDF
                file_content = ContentFile(pdf_bytes)
                filename = f'abc_form_{instance.id}_{instance.date_time.date()}.pdf'
                instance.pdf_file.save(filename, file_content, save=True)

                messages.success(request, 'ABC Form saved successfully!')
                return redirect('abc_form_list')

            except Exception as e:
                messages.error(request, f'Error saving form: {str(e)}')
                logger.exception("Error saving ABC form")
        else:
            messages.error(request, 'Please correct the form errors')
            logger.debug(f"Form errors: {form.errors}")
    else:
        # Initialize form with default values
        initial_data = {
            'staff': request.user.get_full_name(),
            'date_time': timezone.now()
        }
        form = ABCFormForm(initial=initial_data)

    return render(request, 'forms/abc_form.html', {'form': form})


@login_required
def edit_abc_form(request, form_id):
    instance = get_object_or_404(ABCForm, id=form_id)

    if request.method == 'POST':
        form = ABCFormForm(request.POST, instance=instance)
        if form.is_valid():
            try:
                updated = form.save(commit=False)
                updated.updated_by = request.user  # Track who made the update
                updated.save()
                form.save_m2m()

                # Regenerate PDF (same as fill_abc_form)
                context = {
                    'data': {
                        'target_behaviours': form.cleaned_data['target_behaviours'],
                        'service_user': updated.service_user,
                        'date_of_birth': updated.date_of_birth,
                        'staff': updated.staff,
                        'date_time': updated.date_time,
                        'setting': updated.setting,
                        'antecedent': updated.antecedent,
                        'behaviour': updated.behaviour,
                        'consequences': updated.consequences,
                        'reflection': updated.reflection
                    }
                }

                html_string = render_to_string('pdf_templates/abc_pdf.html', context)
                pdf_bytes = HTML(string=html_string).write_pdf()

                if updated.pdf_file:
                    updated.pdf_file.delete()

                file_content = ContentFile(pdf_bytes)
                filename = f'abc_form_{updated.id}_{updated.date_time.date()}.pdf'
                updated.pdf_file.save(filename, file_content, save=True)

                messages.success(request, 'ABC Form updated successfully!')
                return redirect('abc_form_list')

            except Exception as e:
                messages.error(request, f'Error updating form: {str(e)}')
                logger.exception("Error updating ABC form")
        else:
            messages.error(request, 'Please correct the form errors')
    else:
        # The form will automatically parse the instance data
        form = ABCFormForm(instance=instance)

    return render(request, 'forms/abc_form.html', {
        'form': form,
        'edit': True,
        'instance': instance
    })

def parse_abc_instance(instance):
    """Helper function to parse the ABCForm instance into individual template fields"""

    def extract_value(text, field_name, default=''):
        if not text:
            return default
        for line in text.split('\n'):
            if line.startswith(f"{field_name}:"):
                return line.split(':', 1)[1].strip()
        return default

    return {
        'service_user': instance.service_user,
        'date_of_birth': instance.date_of_birth,
        'staff': instance.staff,
        'date_time': instance.date_time,
        'target_behaviours': instance.target_behaviours,

        # Setting fields
        'setting_location': extract_value(instance.setting, 'Location'),
        'setting_present': extract_value(instance.setting, 'Present'),
        'setting_activity': extract_value(instance.setting, 'Activity'),
        'setting_environment': extract_value(instance.setting, 'Environment'),

        # Antecedent fields
        'antecedent_description': extract_value(instance.antecedent, 'Description'),
        'antecedent_change': extract_value(instance.antecedent, 'Routine change', 'no'),
        'antecedent_noise': extract_value(instance.antecedent, 'Unexpected noise', 'no'),
        'antecedent_waiting': extract_value(instance.antecedent, 'Waiting for'),

        # Behaviour field
        'behaviour_description': extract_value(instance.behaviour, 'Description'),

        # Consequences field
        'consequence_immediate': extract_value(instance.consequences, 'Immediate'),

        # Reflection field
        'reflection_learnings': extract_value(instance.reflection, 'Learnings'),
    }

User = get_user_model()


def login_view(request):
    print("Login view accessed")
    if request.method == 'POST':
        print("POST data:", request.POST)
        email = request.POST.get('username')  # Now we only use email
        password = request.POST.get('password')
        print(f"Attempting auth for {email}")

        user = authenticate(request, email=email, password=password)
        print("User object:", user)

        if user is not None:
            login(request, user)
            print("Login successful, redirecting...")

            # Update last active time
            user.last_active = timezone.now()
            user.save()

            if user.is_superuser:
                return redirect('admin-dashboard')
            elif user.role == CustomUser.STAFF:
                return redirect('admin-dashboard')
            else:
                return redirect('staff-dashboard')
        else:
            print("Authentication failed")
            return render(request, 'core/login.html', {
                'error': 'Invalid email or password'
            })

    return render(request, 'core/login.html')


@login_required
def dashboard(request):
    user = request.user

    if user.is_superuser or user.role == CustomUser.Manager:
        context = {
            "active_users_count": CustomUser.objects.filter(is_active=True).count(),
            "incident_reports_count": IncidentReport.objects.count(),
            "abc_forms_count": ABCForm.objects.count(),
            "latest_logs_count": LatestLogEntry.objects.count(),
            "missed_logs_count": LogEntry.objects.filter(is_locked=False, content="",
                                                         date__lt=timezone.localdate()).count(),
            "recent_carehomes": CareHome.objects.order_by("-created_at")[:5],
            "can_add_carehome": True,  # Show 'Add New Carehome' button
        }
        return render(request, "core/dashboard.html", context)

    elif user.role == CustomUser.TEAM_LEAD:
        # carehome = user.carehome
        # staff_users = CustomUser.objects.filter(role='staff', carehome=carehome)
        # latest_logs_qs = LatestLogEntry.objects.filter(user__in=staff_users)
        #
        # context = {
        #     "active_users_count": staff_users.filter(is_active=True).count(),
        #     "incident_reports_count": IncidentReport.objects.filter(carehome=carehome).count(),
        #     "abc_forms_count": ABCForm.objects.filter(service_user__carehome=carehome).count(),
        #     "latest_logs_count": latest_logs_qs.count(),
        #     "missed_logs_count": LogEntry.objects.filter(
        #         user__in=staff_users,
        #         is_locked=False,
        #         content="",
        #         date__lt=timezone.localdate()
        #     ).count(),
        #     "recent_carehomes": CareHome.objects.filter(id=carehome.id),
        #     "can_add_carehome": False,
        # }
        # return render(request, "core/dashboard.html", context)
        context = {
            "incident_reports_count": IncidentReport.objects.filter(staff=user).count(),
            "abc_forms_count": ABCForm.objects.filter(created_by=user).count(),
            "latest_logs_count": LatestLogEntry.objects.filter(user=user).count(),
            "missed_logs_count": LogEntry.objects.filter(user=user, is_locked=False, content="",
                                                         date__lt=timezone.localdate()).count(),
        }
        return render(request, "core/staff_dashboard.html", context)



    elif user.role == CustomUser.STAFF:
        context = {
            "incident_reports_count": IncidentReport.objects.filter(staff=user).count(),
            "abc_forms_count": ABCForm.objects.filter(created_by=user).count(),
            "latest_logs_count": LatestLogEntry.objects.filter(user=user).count(),
            "missed_logs_count": LogEntry.objects.filter(user=user, is_locked=False, content="",
                                                         date__lt=timezone.localdate()).count(),
        }
        return render(request, "core/staff_dashboard.html", context)

    return redirect("login")


def logout_view(request):
    logout(request)
    return redirect('login')


# In your create_staff view, add better error handling:
@login_required
def create_staff(request):
    carehomes = CareHome.objects.all()

    if request.method == 'POST':
        form = StaffCreationForm(request.POST, request.FILES)
        print(f"Form data: {request.POST}")  # Debug
        print(f"Form files: {request.FILES}")  # Debug

        if form.is_valid():
            try:
                staff = form.save(commit=False)

                # Handle role-based staff status
                if staff.role == CustomUser.TEAM_LEAD:
                    staff.is_staff = True
                else:
                    staff.is_staff = False

                staff.save()
                messages.success(request, 'Staff member created successfully!')
                return redirect('staff-dashboard')

            except Exception as e:
                print(f"Error during save: {e}")  # Debug
                messages.error(request, f'Error saving staff: {str(e)}')
        else:
            print(f"Form errors: {form.errors}")  # Debug
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        form = StaffCreationForm()

    return render(request, 'staff/create.html', {
        'form': form,
        'carehomes': carehomes,
        'edit_mode': False
    })

@login_required
def edit_staff(request, pk):
    staff = get_object_or_404(CustomUser, pk=pk)
    carehomes = CareHome.objects.all()

    image_exists = False
    if staff.image:
        try:
            image_exists = os.path.exists(staff.image.path)
        except:
            image_exists = False

    if request.method == 'POST':
        # For edit mode, use a different form that doesn't require passwords
        form = StaffEditForm(request.POST, request.FILES, instance=staff)

        if form.is_valid():
            staff = form.save(commit=False)

            # Handle password change only if provided
            password1 = request.POST.get('password1')
            password2 = request.POST.get('password2')

            if password1 and password2:
                if password1 == password2:
                    staff.set_password(password1)
                else:
                    messages.error(request, 'Passwords do not match.')
                    return render(request, 'staff/create.html', {
                        'form': form,
                        'carehomes': carehomes,
                        'edit_mode': True,
                        'image_exists': image_exists
                    })

            if staff.role == CustomUser.TEAM_LEAD:
                staff.is_staff = True
            else:
                staff.is_staff = False

            staff.save()
            messages.success(request, 'Staff member updated successfully!')
            return redirect('staff-dashboard')
        else:
            print(f"Form errors: {form.errors}")
    else:
        form = StaffEditForm(instance=staff)

    return render(request, 'staff/create.html', {
        'form': form,
        'carehomes': carehomes,
        'edit_mode': True,
        'image_exists': image_exists
    })


@login_required
def toggle_staff_status(request, pk):
    staff = get_object_or_404(CustomUser, pk=pk)
    staff.is_active = not staff.is_active
    staff.save()
    return redirect('staff-dashboard')


@login_required
def staff_dashboard(request):
    if request.user.role == CustomUser.TEAM_LEAD:
        staff_list = CustomUser.objects.filter(carehome=request.user.carehome)
    elif request.user.is_superuser:
        staff_list = CustomUser.objects.all()
    else:
        staff_list = CustomUser.objects.filter(pk=request.user.pk)

    return render(request, 'staff/dashboard.html', {'staff_list': staff_list})


# The rest of your views (carehomes, service users) remain the same
def carehomes_dashboard(request):
    carehomes = CareHome.objects.all().order_by('-created_at')
    return render(request, 'carehomes/dashboard.html', {'carehomes': carehomes})


def create_carehome(request):
    if request.method == 'POST':
        form = CareHomeForm(request.POST, request.FILES)
        if form.is_valid():
            postcode = form.cleaned_data['postcode'].replace(' ', '')
            api_valid = validate_postcode_with_api(postcode)

            if api_valid:
                # Calculate shift times before saving
                morning_start = form.cleaned_data['morning_shift_start']
                if morning_start:
                    # Calculate 12-hour shifts
                    morning_end = (datetime.combine(date.today(), morning_start) + timedelta(hours=12)).time()
                    night_start = morning_end
                    night_end = (datetime.combine(date.today(), night_start) + timedelta(hours=12)).time()

                    # Update form data with calculated times
                    form.instance.morning_shift_end = morning_end
                    form.instance.night_shift_start = night_start
                    form.instance.night_shift_end = night_end

                carehome = form.save()
                messages.success(request, f'Carehome "{carehome.name}" created successfully!')
                return redirect('carehomes-dashboard')
            else:
                messages.error(request, 'Invalid postcode - please enter a valid UK postcode')
        else:
            messages.error(request, 'Please correct the errors below')
    else:
        form = CareHomeForm()

    return render(request, 'carehomes/create.html', {'form': form})


def edit_carehome(request, id):
    carehome = get_object_or_404(CareHome, id=id)
    if request.method == 'POST':
        form = CareHomeForm(request.POST, request.FILES, instance=carehome)
        if form.is_valid():
            # Recalculate shift times if morning start changed
            if 'morning_shift_start' in form.changed_data:
                morning_start = form.cleaned_data['morning_shift_start']
                morning_end = (datetime.combine(date.today(), morning_start) + timedelta(hours=12)).time()
                night_start = morning_end
                night_end = (datetime.combine(date.today(), night_start) + timedelta(hours=12)).time()

                form.instance.morning_shift_end = morning_end
                form.instance.night_shift_start = night_start
                form.instance.night_shift_end = night_end

            form.save()
            messages.success(request, f'Carehome "{carehome.name}" updated successfully!')
            return redirect('carehomes-dashboard')
    else:
        form = CareHomeForm(instance=carehome)
    return render(request, 'carehomes/create.html', {'form': form, 'edit_mode': True})


def delete_carehome(request, id):
    carehome = get_object_or_404(CareHome, id=id)
    carehome.delete()
    return redirect('carehomes-dashboard')


def validate_postcode_with_api(postcode):
    try:
        response = requests.get(f'https://api.postcodes.io/postcodes/{postcode}/validate')
        if response.status_code == 200:
            data = response.json()
            return data.get('result', False)
        return False
    except requests.RequestException:
        return False


def create_service_user(request):
    carehomes = CareHome.objects.all()
    if request.method == 'POST':
        form = ServiceUserForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect('service-users-dashboard')
    else:
        form = ServiceUserForm()

    return render(request, 'service_users/create.html', {
        'form': form,
        'carehomes': carehomes
    })


def edit_service_user(request, id):
    service_user = get_object_or_404(ServiceUser, id=id)
    carehomes = CareHome.objects.all()

    if request.method == 'POST':
        form = ServiceUserForm(request.POST, request.FILES, instance=service_user)
        if form.is_valid():
            form.save()
            return redirect('service-users-dashboard')
    else:
        form = ServiceUserForm(instance=service_user)

    return render(request, 'service_users/create.html', {
        'form': form,
        'edit_mode': True,
        'carehomes': carehomes
    })


def delete_service_user(request, id):
    service_user = get_object_or_404(ServiceUser, id=id)
    service_user.delete()
    return redirect('service-users-dashboard')


def service_users_dashboard(request):
    service_users = ServiceUser.objects.all().order_by('-created_at')
    return render(request, 'service_users/dashboard.html', {'service_users': service_users})


@csrf_exempt
def validate_postcode(request):
    if request.method == 'POST':
        postcode = request.POST.get('postcode', '').replace(' ', '')
        try:
            response = requests.get(f'https://api.postcodes.io/postcodes/{postcode}/validate')
            if response.status_code == 200:
                data = response.json()
                return JsonResponse({'valid': data.get('result', False)})
            return JsonResponse({'valid': False})
        except requests.RequestException:
            return JsonResponse({'valid': False})
    return JsonResponse({'valid': False})


@login_required
def active_users_view(request):
    staff_list = get_filtered_queryset(CustomUser, request.user)
    return render(request, 'core/active_users.html', {'staff_list': staff_list})


def coerce_to_time(val):
    if isinstance(val, datetime.time):
        return val
    if isinstance(val, str):
        h, m = map(int, val.split(":"))
        return datetime.time(h, m)
    return None


@login_required
def view_latest_log_detail(request, pk):
    log = get_object_or_404(LatestLogEntry, id=pk)

    if request.user.role not in ['team_lead'] and not request.user.is_superuser:
        return HttpResponseForbidden("You are not allowed to view this log.")

    if log.log_pdf:
        # render PDF into HTML form OR show download
        return render(request, 'forms/log_entry_from_pdf.html', {'log': log})
    else:
        # fallback to show log data
        return redirect('log-entry-form')


@login_required
def staff_latest_logs_view(request):
    user = request.user

    if user.is_superuser:
        # Manager view: show all staff logs sorted by latest
        logs = LatestLogEntry.objects.all().order_by('-date', '-created_at')

    elif user.role == 'team_lead':
        # Team Lead view: show logs of staff in same carehome
        staff_users = CustomUser.objects.filter(role='staff', carehome=user.carehome)
        logs = LatestLogEntry.objects.filter(user__in=staff_users).order_by('-date', '-created_at')

    else:
        # Staff: only own logs
        logs = LatestLogEntry.objects.filter(user=user).order_by('-date', '-created_at')

    return render(request, 'forms/staff_latest_logs.html', {'logs': logs})


@csrf_exempt
def fetch_service_users(request):
    if request.method == "POST":
        data = json.loads(request.body)
        carehome_ids = data.get('carehome_ids', [])
        users = ServiceUser.objects.filter(carehome_id__in=carehome_ids)

        response = {
            'users': [{'id': su.id, 'name': str(su)} for su in users]
        }
        return JsonResponse(response)
    return JsonResponse({'error': 'Invalid method'}, status=400)


def create_mapping(request):
    if request.method == 'POST':
        form = MappingForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('mapping_success')  # or your desired success route
    else:
        form = MappingForm()
    return render(request, 'core/staff_mapping.html', {'form': form})


def staff_mapping_view(request):
    mappings = Mapping.objects.all().prefetch_related('carehomes', 'service_users')
    form = MappingForm()
    mapping_id = request.GET.get('edit', None)
    mapping_instance = None

    if mapping_id:
        mapping_instance = get_object_or_404(Mapping, id=mapping_id)

    if request.method == "POST":
        if mapping_instance:
            form = MappingForm(request.POST, instance=mapping_instance)
        else:
            form = MappingForm(request.POST)

        if form.is_valid():
            form.save()
            return redirect('staff-mapping')

    context = {
        'form': form,
        'mappings': mappings,
        'show_form': request.method == "POST" or 'show_form' in request.GET or mapping_id,
        'editing': mapping_instance is not None,
        'mapping_instance': mapping_instance
    }
    return render(request, 'core/staff_mapping.html', context)


def delete_mapping(request, pk):
    mapping = get_object_or_404(Mapping, id=pk)
    if request.method == 'POST':
        mapping.delete()
        return redirect('staff-mapping')
    return redirect('staff-mapping')

def load_service_users(request):
    carehome_ids = request.GET.getlist('carehome_ids[]')
    users = ServiceUser.objects.filter(carehome_id__in=carehome_ids)
    data = [{'id': u.id, 'name': f"{u.first_name} {u.last_name}"} for u in users]
    return JsonResponse({'service_users': data})


@login_required
def log_detail_view(request, pk):
    latest_log = get_object_or_404(LatestLogEntry, pk=pk)
    user = request.user

    # Permission logic
    is_owner = latest_log.user == user
    is_superuser = user.is_superuser
    is_manager = user.role == 'manager'
    is_team_lead = user.role == 'team_lead'

    # Determine access rights
    can_view = False
    can_edit = False

    if is_superuser or is_manager:
        # Managers/superusers can view/edit all logs
        can_view = True
        can_edit = not latest_log.status == 'locked'

    elif is_team_lead:
        # Team leads can view/edit logs from their carehome
        if latest_log.carehome == user.carehome:
            can_view = True
            can_edit = (is_owner or not latest_log.status == 'locked')

    elif is_owner:
        # Owners can always view their own logs
        can_view = True
        can_edit = not latest_log.status == 'locked'

    else:
        # Regular staff can only view if they're assigned to the same carehome
        if hasattr(user, 'carehome') and latest_log.carehome == user.carehome:
            can_view = True

    if not can_view:
        return HttpResponseForbidden("You don't have permission to view this log")

    # Get log entries
    log_entries = LogEntry.objects.filter(
        service_user=latest_log.service_user,
        date=latest_log.date,
        shift=latest_log.shift
    )

    context = {
        'latest_log': latest_log,
        'log_entries': log_entries,
        'can_edit': can_edit,
        'user_role': user.role
    }

    return render(request, 'logs/log_detail.html', context)

@login_required
def log_entry_form_view(request, latest_log_id):
    latest_log = get_object_or_404(LatestLogEntry, pk=latest_log_id, user=request.user)
    service_user = latest_log.service_user
    carehome = latest_log.carehome
    shift = latest_log.shift  # 'morning' or 'night'
    today = latest_log.date

    # Pick correct shift start/end from CareHome
    if shift == 'morning':
        start_time = carehome.morning_shift_start
        end_time = carehome.morning_shift_end
    else:  # night
        start_time = carehome.night_shift_start
        end_time = carehome.night_shift_end

    if not start_time or not end_time:
        messages.error(request, f"{shift.capitalize()} shift times are not set for this carehome.")
        return redirect('create_log_view')

    # Build start and end datetimes
    start_dt = datetime.combine(today, start_time)
    end_dt = datetime.combine(today, end_time)

    # Handle night shift that crosses midnight
    if shift == 'night' and end_time < start_time:
        end_dt += timedelta(days=1)

    # Generate slots (hourly — can adjust if you need custom intervals)
    time_slots = []
    current = start_dt
    while current < end_dt:
        time_slots.append(current.time())
        current += timedelta(hours=1)

    # Create or fetch log entries
    log_entries = []
    for slot in time_slots:
        entry, created = LogEntry.objects.get_or_create(
            latest_log=latest_log,
            time_slot=slot,
            defaults={'content': '', 'is_locked': False}
        )
        log_entries.append(entry)

    return render(request, 'logs/log_entry_form.html', {
        'today': today,
        'carehome': carehome,
        'service_user': service_user,
        'shift': shift.capitalize(),
        'log_entries': log_entries,
        'latest_log': latest_log,
    })

def view_incident_report(request, pk):
    incident = get_object_or_404(IncidentReport, pk=pk)

    context = {
        'data': {
            'id': incident.id,
            'staff': incident.staff,
            'service_user': incident.service_user,
            'carehome': incident.carehome,
            'incident_datetime': incident.incident_datetime.strftime('%Y-%m-%d %H:%M'),
            'location': incident.location,
            'dob': incident.dob.strftime('%Y-%m-%d'),
            'staff_involved': incident.staff_involved,
            'prior_description': incident.prior_description,
            'incident_description': incident.incident_description,
            'user_response': incident.user_response,
            'contacted_manager': incident.contacted_manager,
            'manager_contact_date': incident.manager_contact_date.strftime(
                '%Y-%m-%d %H:%M') if incident.manager_contact_date else None,
            'manager_contact_comment': incident.manager_contact_comment,
            'contacted_police': incident.contacted_police,
            'police_contact_date': incident.police_contact_date.strftime(
                '%Y-%m-%d %H:%M') if incident.police_contact_date else None,
            'police_contact_comment': incident.police_contact_comment,
            'contacted_paramedics': incident.contacted_paramedics,
            'paramedics_contact_date': incident.paramedics_contact_date.strftime(
                '%Y-%m-%d %H:%M') if incident.paramedics_contact_date else None,
            'paramedics_contact_comment': incident.paramedics_contact_comment,
            'contacted_other': incident.contacted_other,
            'other_contact_name': incident.other_contact_name,
            'other_contact_date': incident.other_contact_date.strftime(
                '%Y-%m-%d %H:%M') if incident.other_contact_date else None,
            'other_contact_comment': incident.other_contact_comment,
            'prn_administered': incident.prn_administered,
            'prn_by_whom': incident.prn_by_whom,
            'injuries_detail': incident.injuries_detail,
            'property_damage': incident.property_damage,
            'pdf_file': incident.pdf_file,
            # Add these image fields
            'image1': incident.image1,
            'image2': incident.image2,
            'image3': incident.image3,
            'get_images': [img for img in [incident.image1, incident.image2, incident.image3] if img]
        },
        'can_edit': request.user.has_perm('core.change_incidentreport')
    }
    return render(request, 'core/incident_report_template.html', context)


def generate_log_pdf(latest_log):
    try:
        # Get all entries for this log, including those that might not have latest_log set
        log_entries = LogEntry.objects.filter(
            user=latest_log.user,
            carehome=latest_log.carehome,
            service_user=latest_log.service_user,
            date=latest_log.date,
            shift=latest_log.shift
        )

        # Also update these entries to point to the latest_log
        log_entries.update(latest_log=latest_log)

        html_string = render_to_string('pdf_templates/log_pdf.html', {
            'latest_log': latest_log,
            'log_entries': log_entries,
        })

        # Ensure directory exists
        os.makedirs(os.path.join(settings.MEDIA_ROOT, 'log_pdfs'), exist_ok=True)

        pdf_filename = f"log_{latest_log.id}.pdf"
        pdf_path = os.path.join(settings.MEDIA_ROOT, 'log_pdfs', pdf_filename)

        HTML(string=html_string).write_pdf(pdf_path)

        latest_log.log_pdf.name = f'log_pdfs/{pdf_filename}'
        latest_log.save()
        return True
    except Exception as e:
        print(f"Error generating PDF: {str(e)}")
        return False


@login_required
def lock_log_entries(request, latest_log_id):
    try:
        # Get the log entry with proper permission checking
        latest_log = get_object_or_404(
            LatestLogEntry,
            id=latest_log_id,
            user=request.user  # Ensures user owns this log
        )

        # Start atomic transaction
        with transaction.atomic():
            # Lock all related entries
            updated = LogEntry.objects.filter(
                latest_log=latest_log,
                is_locked=False  # Only lock unlocked entries
            ).update(is_locked=True)

            # Update log status
            latest_log.status = 'locked'
            latest_log.save()

            # Generate PDF
            if not generate_log_pdf(latest_log):
                raise Exception("PDF generation failed")

            messages.success(request, f"Successfully locked log with {updated} entries")
            return redirect('staff-dashboard')

    except Exception as e:
        messages.error(request, f"Error locking log: {str(e)}")
        return redirect('staff-dashboard')


@login_required
def edit_log_entry_by_admin(request, latest_log_id):
    log = get_object_or_404(LatestLogEntry, id=latest_log_id)

    if request.user.role not in ['team_lead', 'manager'] and not request.user.is_superuser:
        return HttpResponseForbidden("Permission denied.")

    entries = LogEntry.objects.filter(latest_log=log)
    return render(request, 'forms/log_entry_form.html', {
        'log_entries': entries,
        'latest_log': log,
        'admin_edit': True
    })


@require_POST
@login_required
def save_log_entry(request, entry_id):
    entry = get_object_or_404(LogEntry, id=entry_id)
    content = request.POST.get('content', '').strip()

    if not content:
        return JsonResponse({'success': False, 'error': 'Content cannot be empty'})

    try:
        with transaction.atomic():
            # REMOVED THE is_locked CHECK
            entry.content = content
            entry.save()

            if entry.latest_log:
                # entry.latest_log.status = 'incomplete'
                # entry.latest_log.save()
                if hasattr(entry.latest_log, 'generate_pdf'):
                    entry.latest_log.generate_pdf()

        return JsonResponse({'success': True})

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def get_staff_by_carehome(request):
    carehome_id = request.GET.get('carehome_id')
    staff = User.objects.filter(carehome_id=carehome_id).values('id', 'first_name', 'last_name')
    staff_list = [{
        'id': s['id'],
        'name': f"{s['first_name']} {s['last_name']}"
    } for s in staff]
    return JsonResponse({'staff': staff_list})


@require_GET
def get_service_users_by_carehome(request):
    # Get the raw parameter value
    carehome_param = request.GET.get('carehome_id') or request.GET.get('carehome_id[]')

    if not carehome_param:
        return JsonResponse({'service_users': []}, status=400)

    try:
        # Handle both single ID and comma-separated IDs
        if ',' in carehome_param:
            carehome_ids = [int(id.strip()) for id in carehome_param.split(',')]
            service_users = ServiceUser.objects.filter(carehome_id__in=carehome_ids)
        else:
            service_users = ServiceUser.objects.filter(carehome_id=int(carehome_param))

        users_list = [{
            'id': user.id,
            'name': user.get_formatted_name()
        } for user in service_users]

        return JsonResponse({'service_users': users_list})

    except (ValueError, TypeError) as e:
        return JsonResponse({'error': 'Invalid carehome ID format'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
def fill_incident_form(request):
    if request.method == 'POST':
        form = IncidentReportForm(request.POST, request.FILES)  # Added request.FILES
        if form.is_valid():
            instance = form.save(commit=False)
            instance.staff = request.user
            instance.save()
            # Handle image resizing/validation if needed
            for i in range(1, 4):
                image_field = f'image{i}'
                if image_field in request.FILES:
                    # You could add image processing here if needed
                    setattr(instance, image_field, request.FILES[image_field])

            instance.carehome = form.cleaned_data['service_user'].carehome
            instance.save()

            # Generate HTML for PDF with images
            html_string = render_to_string('pdf_templates/incident_pdf.html', {'data': instance})

            # Generate PDF with WeasyPrint
            temp_pdf = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            temp_pdf.close()

            # Handle base_url for WeasyPrint to access media files
            base_url = request.build_absolute_uri('/')[:-1]  # Remove trailing slash
            HTML(string=html_string, base_url=base_url).write_pdf(temp_pdf.name)

            with open(temp_pdf.name, 'rb') as pdf_file:
                file_content = ContentFile(pdf_file.read())
                filename = f'incident_report_{instance.id}.pdf'
                instance.pdf_file.save(filename, file_content)

            os.unlink(temp_pdf.name)
            return redirect('incident_report_list')
    else:
        form = IncidentReportForm()
        from django.core.serializers.json import DjangoJSONEncoder
        import json
        service_users = ServiceUser.objects.all().values("id", "dob")
        service_user_dob_map = {str(u["id"]): u["dob"].strftime("%Y-%m-%d") for u in service_users}

    return render(request, 'forms/incident_form.html', {'form': form,
                                                        'service_user_dob_map': json.dumps(service_user_dob_map,
                                                                                           cls=DjangoJSONEncoder),
                                                        })


@login_required
def incident_report_list_view(request):
    user = request.user

    # Base queryset based on user role
    if user.is_superuser or user.role == 'manager':
        incidents = IncidentReport.objects.select_related('service_user')
    elif user.role == 'team_lead':
        incidents = IncidentReport.objects.filter(service_user__carehome=user.carehome)
    elif user.role == 'staff':
        incidents = IncidentReport.objects.filter(staff=user)
    else:
        incidents = IncidentReport.objects.none()

    # Get filter parameters from request
    service_user_id = request.GET.get('service_user')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    # Apply filters
    if service_user_id:
        incidents = incidents.filter(service_user_id=service_user_id)

    if date_from:
        try:
            date_from = datetime.strptime(date_from, '%Y-%m-%d').date()
            incidents = incidents.filter(incident_datetime__date__gte=date_from)
        except ValueError:
            pass

    if date_to:
        try:
            date_to = datetime.strptime(date_to, '%Y-%m-%d').date()
            incidents = incidents.filter(incident_datetime__date__lte=date_to)
        except ValueError:
            pass

    # Ordering and additional processing
    incidents = incidents.order_by('-incident_datetime')

    # Get service users based on filtered incidents
    service_users = ServiceUser.objects.filter(
        id__in=incidents.values_list('service_user', flat=True).distinct()
    ).order_by('first_name')

    # Add image preview flag
    for incident in incidents:
        incident.has_images = any([
            incident.image1,
            incident.image2,
            incident.image3
        ])

    return render(request, 'forms/incident_report_list.html', {
        'incidents': incidents,
        'service_users': service_users,
        'search_params': request.GET
    })


@login_required
def edit_incident_form(request, form_id):
    instance = get_object_or_404(IncidentReport, id=form_id)

    # Check permission - only original staff or managers can edit
    if not (request.user == instance.staff or request.user.role in ['manager', 'superuser']):
        return redirect('incident_report_list')

    if request.method == 'POST':
        form = IncidentReportForm(request.POST, request.FILES, instance=instance)
        if form.is_valid():
            instance = form.save(commit=False)
            instance.staff = request.user

            # Handle image updates
            for i in range(1, 4):
                image_field = f'image{i}'
                if image_field in request.FILES:
                    # Clear existing image if new one is uploaded
                    if getattr(instance, image_field):
                        getattr(instance, image_field).delete()
                    setattr(instance, image_field, request.FILES[image_field])
                elif f'{image_field}-clear' in request.POST:
                    # Handle image removal if clear checkbox is checked
                    if getattr(instance, image_field):
                        getattr(instance, image_field).delete()
                        setattr(instance, image_field, None)

            instance.carehome = form.cleaned_data['service_user'].carehome
            instance.save()

            # Regenerate PDF with updated images
            html_string = render_to_string('pdf_templates/incident_pdf.html', {'data': instance})
            base_url = request.build_absolute_uri('/')[:-1]
            with tempfile.NamedTemporaryFile(delete=True, suffix='.pdf') as output:
                HTML(string=html_string, base_url=base_url).write_pdf(output.name)
                with open(output.name, 'rb') as pdf_file:
                    file_content = ContentFile(pdf_file.read())
                    filename = f'incident_report_{instance.id}.pdf'
                    instance.pdf_file.save(filename, file_content)

            return redirect('incident_detail', form_id=instance.id)
    else:
        form = IncidentReportForm(instance=instance)
    from django.core.serializers.json import DjangoJSONEncoder
    import json
    service_users = ServiceUser.objects.all().values("id", "dob")
    service_user_dob_map = {str(u["id"]): u["dob"].strftime("%Y-%m-%d") for u in service_users}

    return render(request, 'forms/incident_form.html', {
        'form': form,
        'existing_images': [
            {'field': 'image1', 'url': instance.image1.url if instance.image1 else None},
            {'field': 'image2', 'url': instance.image2.url if instance.image2 else None},
            {'field': 'image3', 'url': instance.image3.url if instance.image3 else None},
        ] ,'service_user_dob_map': json.dumps(service_user_dob_map, cls=DjangoJSONEncoder),
    })


def download_incident_pdf(request, form_id):
    form_data = get_object_or_404(IncidentReport, id=form_id)

    html_string = render_to_string('pdf_templates/incident_pdf.html', {
        'data': form_data,
        'request': request  # Important for media URL resolution
    })

    base_url = request.build_absolute_uri('/')
    pdf_file = HTML(string=html_string, base_url=base_url).write_pdf()

    response = HttpResponse(pdf_file, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="incident_report_{form_id}.pdf"'
    return response


@login_required
def log_entry_form(request, latest_log_id):
    latest_log = get_object_or_404(LatestLogEntry, id=latest_log_id)
    shift = latest_log.shift.lower()
    carehome = latest_log.carehome
    service_user = latest_log.service_user
    today = latest_log.date

    # Permission check - staff can only edit their own logs
    if request.user.role == 'staff' and latest_log.user != request.user:
        messages.error(request, "You can only edit your own logs")
        return redirect('staff-dashboard')

    # For staff users - redirect to view if log is already completed
    if (request.user.role == 'staff' and
            latest_log.status == 'completed' and
            not request.GET.get('force_edit')):
        messages.info(request, "Viewing completed log. Use 'Edit' button to make changes.")
        return redirect('log-detail-view', latest_log_id=latest_log.id)

    # Dynamically choose shift start time
    if shift == "morning":
        base_start_time = carehome.morning_shift_start or time(8, 0)
    elif shift == "night":
        base_start_time = carehome.night_shift_start or time(20, 0)
    else:
        base_start_time = time(8, 0)  # fallback

    time_slots = generate_shift_times(base_start_time)

    # Get or create log entries
    log_entries = []
    for slot in time_slots:
        entry, created = LogEntry.objects.get_or_create(
            user=latest_log.user,
            carehome=latest_log.carehome,
            service_user=latest_log.service_user,
            shift=latest_log.shift,
            date=latest_log.date,
            time_slot=slot,
            defaults={'latest_log': latest_log}
        )
        log_entries.append(entry)

    # Sort entries by time slot if needed
    log_entries.sort(key=lambda x: x.time_slot)

    return render(request, 'forms/log_entry_form.html', {
        'log_entries': log_entries,
        'latest_log': latest_log,
        'shift': latest_log.shift,
        'carehome': carehome,
        'service_user': service_user,
        'today': today,
        'can_edit': True,  # Since we got here, editing is allowed
        'is_update': True,
        "user_role": request.user.role,  # Flag to show this is an update
        'force_edit_param': 'force_edit=true'  # For edit buttons in template
    })


def generate_time_slots(start_time, end_time):
    """Generate hourly time slots between start and end times"""
    time_slots = []
    current_time = start_time

    while current_time < end_time:
        time_slots.append(current_time)
        # Add one hour
        current_time = (datetime.combine(date.today(), current_time) + timedelta(hours=1)).time()

    return time_slots


@login_required
def missed_shifts_view(request):
    # Calculate date range (last 6 months)
    today = timezone.localdate()
    six_months_ago = today - timedelta(days=180)

    # Debug: Print dates to verify
    print(f"Date range: {six_months_ago} to {today}")

    # Get all unresolved missed logs in this period
    missed_logs = MissedLog.objects.filter(
        date__gte=six_months_ago,
        resolved_at__isnull=True
    ).select_related('carehome', 'service_user').order_by('-date')

    # Debug: Print count of found logs
    print(f"Found {missed_logs.count()} missed logs")

    context = {
        'missing_entries': missed_logs,
        'total_missed': missed_logs.count(),
        'date_range': f"{six_months_ago.strftime('%b %d, %Y')} to {today.strftime('%b %d, %Y')}"
    }

    return render(request, 'core/missed_logs.html', context)


def get_accessible_carehomes(user):
    if user.role == 'manager':
        return CareHome.objects.all()
    elif user.role == 'team_lead':
        return user.managed_carehomes.all()
    return CareHome.objects.none()

def serve_media(request, path):
    from urllib.parse import unquote
    path = unquote(path)
    file_path = os.path.join(settings.MEDIA_ROOT, path)
    logger.info(f"Trying to serve media file: {file_path}")
    if os.path.exists(file_path):
        return FileResponse(open(file_path, 'rb'))
    logger.error(f"File not found: {file_path}")
    raise Http404("File not found")

def get_service_users(request):
    carehome_id = request.GET.get('carehome_id')
    service_users = ServiceUser.objects.filter(carehome_id=carehome_id)
    data = [{"id": su.id, "name": f"{su.first_name} {su.last_name}"} for su in service_users]
    return JsonResponse(data, safe=False)