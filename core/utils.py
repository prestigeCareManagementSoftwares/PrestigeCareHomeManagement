from datetime import time, datetime, timedelta

from django.core.files.storage import default_storage
from django.utils.timezone import now
from django.core.files import File
from .models import LatestLogEntry
import os
from django.template.loader import render_to_string
from django.conf import settings
from weasyprint import HTML
from django.utils import timezone
from .models import CustomUser, LatestLogEntry, LogEntry, IncidentReport, ABCForm, ServiceUser

def get_filtered_queryset(model, user, *, filter_today=False):
    """
    Reusable filter for team lead / manager role-based carehome filtering.
    Example: model = LatestLogEntry or IncidentReport
    """
    qs = model.objects.all()

    if user.is_superuser or user.role == CustomUser.Manager:
        return qs

    if user.role == CustomUser.TEAM_LEAD:
        if hasattr(model, 'carehome'):
            qs = qs.filter(carehome=user.carehome)
        elif hasattr(model, 'service_user'):
            qs = qs.filter(service_user__carehome=user.carehome)
        elif model == CustomUser:
            qs = qs.filter(carehome=user.carehome, role=CustomUser.STAFF)

    elif user.role == CustomUser.STAFF:
        if hasattr(model, 'staff'):
            qs = qs.filter(staff=user)
        elif hasattr(model, 'user'):
            qs = qs.filter(user=user)
        elif model == CustomUser:
            qs = qs.filter(id=user.id)

    if filter_today and hasattr(model, 'date'):
        qs = qs.filter(date=timezone.localdate())

    return qs


def get_or_create_latest_log(user, carehome, service_user, shift):
    today = now().date()
    log, created = LatestLogEntry.objects.get_or_create(
        user=user,
        carehome=carehome,
        service_user=service_user,
        shift=shift,
        date=today,
        defaults={'status': 'incomplete'}
    )
    return log

def complete_log(latest_log):
    latest_log.status = 'locked'
    pdf_path = generate_pdf(latest_log)  # ← You define this function
    latest_log.log_pdf.save('log.pdf', File(open(pdf_path, 'rb')))
    latest_log.save()
def generate_pdf(latest_log):
    from .models import LogEntry  # Import here to avoid circular import

    log_entries = LogEntry.objects.filter(
        user=latest_log.user,
        carehome=latest_log.carehome,
        shift=latest_log.shift,
        service_user=latest_log.service_user,
        date=latest_log.date
    )

    html = render_to_string('pdf/log_template.html', {
        'log_entries': log_entries,
        'log_info': latest_log,
    })

    filename = f"log_{latest_log.id}.pdf"
    output_path = os.path.join(settings.MEDIA_ROOT, 'log_pdfs', filename)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    HTML(string=html).write_pdf(output_path)

    return output_path  # So you can open and attach the file later

def generate_shift_times(base_time: time, total_slots: int = 12) -> list[time]:
    times = []
    current = datetime.combine(datetime.today(), base_time)
    for _ in range(total_slots):
        times.append(current.time())
        current += timedelta(minutes=60)  # 1-hour intervals
    return times

def delete_image_file(image_field):
    """Safely delete an image file from storage"""
    if image_field:
        try:
            if default_storage.exists(image_field.name):
                default_storage.delete(image_field.name)
                print(f"Deleted image: {image_field.name}")
        except Exception as e:
            print(f"Error deleting image {image_field.name}: {e}")