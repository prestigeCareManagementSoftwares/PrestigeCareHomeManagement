import os

from django.core.exceptions import ValidationError
from django.db.models.signals import pre_save, post_delete
from django.dispatch import receiver
from django.template.loader import render_to_string
from django.utils import timezone
from datetime import timedelta

from django.contrib.auth.base_user import AbstractBaseUser
from django.db import models, transaction
from django.contrib.auth.models import AbstractUser, Group, Permission, PermissionsMixin
from django.core.validators import RegexValidator

from django.contrib.auth.base_user import BaseUserManager

from django.db import models
from weasyprint import HTML

from carehome_project import settings


class CareHome(models.Model):
    name = models.CharField(max_length=100)
    postcode = models.CharField(
        max_length=10,
        validators=[
            RegexValidator(
                regex=r'^[A-Za-z]{1,2}[0-9][A-Za-z0-9]? ?[0-9][A-Za-z]{2}$',
                message='Enter a valid UK postcode'
            )
        ]
    )
    details = models.TextField(blank=True, null=True)
    picture = models.ImageField(upload_to='carehomes/', blank=True, null=True)

    # Final: Shift-specific start times
    morning_shift_start = models.TimeField(null=True, blank=True)
    morning_shift_end = models.TimeField(null=True, blank=True)
    night_shift_start = models.TimeField(null=True, blank=True)
    night_shift_end = models.TimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    managers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='managed_carehomes',
        limit_choices_to={'role__in': ['manager', 'team_lead']},
        blank=True
    )

    @property
    def morning_shift_time(self):
        if self.morning_shift_start and self.morning_shift_end:
            return f"{self.morning_shift_start.strftime('%H:%M')}-{self.morning_shift_end.strftime('%H:%M')}"
        return "Not set"

    @property
    def night_shift_time(self):
        if self.night_shift_start and self.night_shift_end:
            return f"{self.night_shift_start.strftime('%H:%M')}-{self.night_shift_end.strftime('%H:%M')}"
        return "Not set"
    def get_staff_members(self):
        return self.customuser_set.filter(role='staff')

    def save(self, *args, **kwargs):
        if self.pk:
            try:
                old = CareHome.objects.get(pk=self.pk)
                if old.picture != self.picture:
                    old.picture.delete(save=False)
            except CareHome.DoesNotExist:
                pass
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self.picture.delete(save=False)
        super().delete(*args, **kwargs)

    def check_missed_logs(self, date=None):
        """
        Check for service users who don't have shift logs for the given date
        Only checks morning and night shifts
        """
        if date is None:
            date = timezone.now().date()

        missed_logs = []

        for service_user in self.service_users.all():
            # Check morning shift
            if not LatestLogEntry.objects.filter(
                    carehome=self,
                    service_user=service_user,
                    date=date,
                    shift='morning'
            ).exists():
                missed_logs.append(
                    MissedLog(
                        carehome=self,
                        service_user=service_user,
                        date=date,
                        shift='morning'
                    )
                )

            # Check night shift (not afternoon!)
            if not LatestLogEntry.objects.filter(
                    carehome=self,
                    service_user=service_user,
                    date=date,
                    shift='night'
            ).exists():
                missed_logs.append(
                    MissedLog(
                        carehome=self,
                        service_user=service_user,
                        date=date,
                        shift='night'
                    )
                )

        # Bulk create missed logs, ignoring duplicates
        MissedLog.objects.bulk_create(
            missed_logs,
            ignore_conflicts=True
        )

        return MissedLog.objects.filter(
            carehome=self,
            date=date,
            resolved_at__isnull=True
        )

    def get_shift_times(self, shift_type):
        """Returns formatted shift time string"""
        if shift_type == 'morning':
            return f"{self.morning_shift_start.strftime('%H:%M')}-{self.morning_shift_end.strftime('%H:%M')}"
        elif shift_type == 'night':
            return f"{self.night_shift_start.strftime('%H:%M')}-{self.night_shift_end.strftime('%H:%M')}"
        return "Shift not defined"

    def resolve_missed_logs(self, service_user, date):
        """
        Mark all missed logs for a service user on a given date as resolved
        """
        MissedLog.objects.filter(
            carehome=self,
            service_user=service_user,
            date=date,
            resolved_at__isnull=True
        ).update(resolved_at=timezone.now())

    def __str__(self):
        return self.name


class ServiceUser(models.Model):
    carehome = models.ForeignKey(CareHome, on_delete=models.CASCADE,related_name='service_users')
    image = models.ImageField(upload_to='service_users/', blank=True, null=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(
        max_length=20,
        validators=[
            RegexValidator(
                regex=r'^(\+44\s?7\d{3}|\(?07\d{3}\)?)\s?\d{3}\s?\d{3}$',
                message='Enter a valid UK phone number'
            )
        ]
    )
    email = models.EmailField(blank=True, null=True)
    emergency_contact = models.CharField(max_length=20)
    address = models.TextField()
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def get_formatted_name(self):
        initials = f"{self.first_name[0]}{self.last_name[0]}".upper()
        return f"{self.first_name} {self.last_name} ({initials})"

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class ABCForm(models.Model):
    TARGET_BEHAVIOUR_CHOICES = [
        ('physical_aggression', 'Physical aggressive behaviour towards other people'),
        ('property_destruction', 'Property destruction e.g., ripping clothes'),
        ('self_injury', 'Self-injurious behaviours e.g., hitting the wall'),
        ('verbal_aggression', 'Verbal aggression'),
        ('other', 'Other / stereotyped behaviours e.g., screaming'),
    ]

    # User relationships
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_abc_forms',
        verbose_name="Form Creator"
    )
    # models.py
    staff = models.CharField(
        max_length=100,
        null=True,  # Keep this temporarily
        blank=False  # But don't allow blank in forms
    )
    # Form content
    service_user = models.ForeignKey(
        ServiceUser,
        on_delete=models.CASCADE,
        verbose_name="Service User",
        related_name='abc_forms'
    )
    date_of_birth = models.DateField()
    date_time = models.DateTimeField(verbose_name="DATE/TIME Behavior started", default=timezone.now)

    target_behaviours = models.JSONField(
        default=list,
        help_text="List of selected target behaviours"
    )

    setting = models.TextField(blank=True)
    antecedent = models.TextField(blank=True)
    behaviour = models.TextField(blank=True)
    consequences = models.TextField(blank=True)
    reflection = models.TextField(blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_abc_forms',
        verbose_name="Last Updated By"
    )
    # File and timestamps
    pdf_file = models.FileField(upload_to='abc_pdfs/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"ABC Form - {self.service_user} ({self.date_time.date()})"


class IncidentReport(models.Model):
    staff = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)
    service_user = models.ForeignKey('ServiceUser', on_delete=models.CASCADE)
    carehome = models.ForeignKey('CareHome', on_delete=models.CASCADE, null=True, blank=True)

    incident_datetime = models.DateTimeField()
    location = models.CharField(max_length=255)
    dob = models.DateField()
    staff_involved = models.CharField(max_length=255)
    prior_description = models.TextField()
    incident_description = models.TextField()
    user_response = models.TextField()

    contacted_manager = models.BooleanField(default=False)
    manager_contact_date = models.DateTimeField(null=True, blank=True)
    manager_contact_comment = models.TextField(blank=True)

    contacted_police = models.BooleanField(default=False)
    police_contact_date = models.DateTimeField(null=True, blank=True)
    police_contact_comment = models.TextField(blank=True)

    contacted_paramedics = models.BooleanField(default=False)
    paramedics_contact_date = models.DateTimeField(null=True, blank=True)
    paramedics_contact_comment = models.TextField(blank=True)

    contacted_other = models.BooleanField(default=False)
    other_contact_name = models.CharField(max_length=255, blank=True)
    other_contact_date = models.DateTimeField(null=True, blank=True)
    other_contact_comment = models.TextField(blank=True)

    prn_administered = models.BooleanField(default=False)
    prn_by_whom = models.CharField(max_length=255, blank=True)
    injuries_detail = models.TextField(blank=True)
    property_damage = models.TextField(blank=True)
    image1 = models.ImageField(upload_to='incident_images/', blank=True, null=True)
    image2 = models.ImageField(upload_to='incident_images/', blank=True, null=True)
    image3 = models.ImageField(upload_to='incident_images/', blank=True, null=True)

    # ✅ PDF file field
    pdf_file = models.FileField(upload_to='incident_reports/', blank=True, null=True)

    # created_at = models.DateTimeField(auto_now_add=True)
    def get_images(self):
        """Return a list of non-empty images"""
        images = []
        if self.image1:
            images.append(self.image1)
        if self.image2:
            images.append(self.image2)
        if self.image3:
            images.append(self.image3)
        return images

    def __str__(self):
        return f"Incident - {self.service_user} - {self.incident_datetime.strftime('%Y-%m-%d %H:%M')}"


class CustomUserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email, password, **extra_fields)


class CustomUser:
    pass


class CustomUser(AbstractBaseUser, PermissionsMixin):
    # Staff-related fields
    STAFF = 'staff'
    TEAM_LEAD = 'team_lead'
    Manager = 'manager'
    ROLE_CHOICES = [
        (Manager, 'Manager'),
        (STAFF, 'Staff'),
        (TEAM_LEAD, 'Team Lead'),
    ]

    # Personal Info
    image = models.ImageField(upload_to='staff/', blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    additional_info = models.TextField(blank=True, null=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=STAFF)
    carehome = models.ForeignKey('CareHome', on_delete=models.SET_NULL, null=True, blank=True)
    last_active = models.DateTimeField(null=True, blank=True)

    # Authentication fields
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=30, blank=True)
    last_name = models.CharField(max_length=150, blank=True)

    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(default=timezone.now)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    objects = CustomUserManager()

    def __str__(self):
        return f"{self.get_full_name()} ({self.get_role_display() if self.role else 'User'})"

    @property
    def availability_status(self):
        if not self.is_active:
            return "Inactive"
        if self.last_active and (timezone.now() - self.last_active) < timedelta(minutes=5):
            return "Available"
        return "Offline"

    def get_full_name(self):
        full_name = f"{self.first_name} {self.last_name}".strip()
        return full_name if full_name else self.email

    def get_short_name(self):
        return self.first_name

    def get_managed_carehomes(self):
        if self.role == 'team_lead':
            return CareHome.objects.filter(id=self.carehome_id) if self.carehome else CareHome.objects.none()
        elif self.role == 'manager':
            return CareHome.objects.all()
        return CareHome.objects.none()

    @receiver(pre_save, sender=CustomUser)
    def delete_old_image(sender, instance, **kwargs):
        if instance.pk:
            try:
                old_instance = CustomUser.objects.get(pk=instance.pk)
                if old_instance.image and old_instance.image != instance.image:
                    # Delete the old file if it exists
                    if os.path.isfile(old_instance.image.path):
                        os.remove(old_instance.image.path)
            except CustomUser.DoesNotExist:
                pass

    # Signal to delete image file when user is deleted
    @receiver(post_delete, sender=CustomUser)
    def delete_user_image(sender, instance, **kwargs):
        if instance.image:
            if os.path.isfile(instance.image.path):
                os.remove(instance.image.path)

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'


class Mapping(models.Model):
    staff = models.ForeignKey(CustomUser, on_delete=models.CASCADE, limit_choices_to={'role': 'staff'})
    carehomes = models.ManyToManyField(CareHome)
    service_users = models.ManyToManyField(ServiceUser)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Mapping for {self.staff.get_full_name()}"

    def get_mapped_details(self):
        details = []
        for carehome in self.carehomes.all():
            service_users = self.service_users.filter(carehome=carehome)
            if service_users.exists():
                su_names = ", ".join([su.first_name for su in service_users])
                details.append(f"{carehome.name} ({su_names})")
            else:
                details.append(f"{carehome.name} (No service users)")
        return "; ".join(details)


class LogEntry(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='custom_log_entries'
    )
    carehome = models.ForeignKey('CareHome', on_delete=models.CASCADE)
    shift = models.CharField(max_length=50)  # e.g., Morning, Evening
    service_user = models.ForeignKey('ServiceUser', on_delete=models.CASCADE)
    date = models.DateField(auto_now_add=True)
    time_slot = models.TimeField()  # For each hour slot (e.g., 08:00, 09:00)
    content = models.TextField(blank=True)
    latest_log = models.ForeignKey(
        'LatestLogEntry',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='log_entries'
    )
    is_locked = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.date} - {self.service_user} - {self.time_slot}"

    class Meta:
        ordering = ['date', 'time_slot']
        verbose_name_plural = "Log Entries"


class LatestLogEntry(models.Model):
    STATUS_CHOICES = [
        ('incomplete', 'Incomplete'),
        ('locked', 'Locked')
    ]

    SHIFT_CHOICES = [
        ('morning', 'Morning'),
        ('night', 'Night'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='latest_log_entries'
    )
    carehome = models.ForeignKey(
        'CareHome',
        on_delete=models.CASCADE,
        related_name='latest_log_entries'
    )
    service_user = models.ForeignKey(
        'ServiceUser',
        on_delete=models.CASCADE,
        related_name='latest_log_entries'
    )
    shift = models.CharField(
        max_length=50,
        choices=SHIFT_CHOICES
    )
    date = models.DateField(auto_now_add=True)
    staff_name = models.CharField(max_length=100, blank=True)
    day_of_week = models.CharField(max_length=10, blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='incomplete'
    )
    log_pdf = models.FileField(
        upload_to='log_pdfs/',
        blank=True,
        null=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.date} - {self.service_user} - {self.get_shift_display()} ({self.status})"

    def save(self, *args, **kwargs):
        # Auto-set day of week if not provided
        if not self.pk:  # Only for new entries, not updates
            existing_log = LatestLogEntry.objects.filter(
                user=self.user,
                carehome=self.carehome,
                service_user=self.service_user,
                date=self.date,
                shift=self.shift
            ).exists()

            if existing_log:
                raise ValidationError(
                    "A log already exists for this user, carehome, service user, date and shift combination.")
        if not self.day_of_week and self.date:
            self.day_of_week = self.date.strftime('%A')

        # Auto-set staff name if not provided
        if not self.staff_name and self.user:
            self.staff_name = self.user.get_full_name() or self.user.username

        with transaction.atomic():
            super().save(*args, **kwargs)

            # Ensure all related log entries point to this LatestLogEntry
            self._update_related_log_entries()

    def _update_related_log_entries(self):
        """Update all related log entries to point to this LatestLogEntry"""
        from .models import LogEntry  # Avoid circular import

        LogEntry.objects.filter(
            user=self.user,
            carehome=self.carehome,
            service_user=self.service_user,
            date=self.date,
            shift=self.shift
        ).update(latest_log=self)

    def generate_pdf(self):
        """Generate PDF document for this log entry"""
        try:
            # Get all related log entries
            log_entries = self.log_entries.all().order_by('time_slot')

            if not log_entries.exists():
                raise ValueError("No log entries found for this shift")

            context = {
                'latest_log': self,
                'log_entries': log_entries,
            }

            # Render HTML template
            html_string = render_to_string('pdf_templates/log_pdf.html', context)

            # Ensure PDF directory exists
            pdf_dir = os.path.join(settings.MEDIA_ROOT, 'log_pdfs')
            os.makedirs(pdf_dir, exist_ok=True)

            # Generate unique filename with timestamp
            timestamp = self.updated_at.strftime('%Y%m%d_%H%M%S')
            pdf_filename = f"log_{self.id}_{timestamp}.pdf"
            pdf_path = os.path.join(pdf_dir, pdf_filename)

            # Generate PDF
            HTML(string=html_string).write_pdf(pdf_path)

            # Delete old PDF if exists
            if self.log_pdf:
                try:
                    os.remove(self.log_pdf.path)
                except (ValueError, OSError):
                    pass

            # Save new PDF reference
            self.log_pdf.name = f'log_pdfs/{pdf_filename}'
            self.save()

            return True
        except Exception as e:
            print(f"Error generating PDF for log {self.id}: {str(e)}")
            return False

    @property
    def staff_initials(self):
        """Returns the staff initials (first letters of first and last name)"""
        if not hasattr(self.user, 'first_name'):
            return self.user.username[0].upper()  # fallback to username

        first_initial = self.user.first_name[0].upper() if self.user.first_name else ''
        last_initial = self.user.last_name[0].upper() if self.user.last_name else ''

        # If both initials exist, combine them (e.g., "JD")
        if first_initial and last_initial:
            return f"{first_initial}{last_initial}"

        # If only one exists, use that
        if first_initial or last_initial:
            return first_initial or last_initial

        # Final fallback to username
        return self.user.username[0].upper()

    def lock(self):
        """Lock this log entry and all related entries"""
        with transaction.atomic():
            self.log_entries.all().update(is_locked=True)
            self.status = 'locked'
            self.save()
            self.generate_pdf()

    class Meta:
        unique_together = ['user', 'service_user', 'date', 'shift']
        verbose_name_plural = "Latest Log Entries"
        ordering = ['-date', '-created_at']
        indexes = [
            models.Index(fields=['user', 'date']),
            models.Index(fields=['carehome', 'date']),
            models.Index(fields=['service_user', 'date']),
        ]


class MissedLog(models.Model):
    SHIFT_CHOICES = [
        ('morning', 'Morning'),
        ('night', 'Night'),
    ]

    carehome = models.ForeignKey(CareHome, on_delete=models.CASCADE)
    service_user = models.ForeignKey(ServiceUser, on_delete=models.CASCADE)
    date = models.DateField()
    shift = models.CharField(max_length=20, choices=SHIFT_CHOICES)
    is_notified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.date} - {self.carehome} - {self.get_shift_display()} - {self.service_user}"

    class Meta:
        verbose_name = "Missed Shift"
        verbose_name_plural = "Missed Shifts"
