from datetime import timedelta

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from .models import LatestLogEntry, MissedLog, CareHome


@receiver(post_save, sender=LatestLogEntry)
def update_missed_logs(sender, instance, created, **kwargs):
    """
    When a new log is created, check if it resolves any missed logs
    """
    if created:
        # Check if there was a missed log for this service user, date, and shift
        MissedLog.objects.filter(
            carehome=instance.carehome,
            service_user=instance.service_user,
            date=instance.date,
            shift=instance.shift,
            resolved_at__isnull=True
        ).update(resolved_at=timezone.now())

        # Check if both shifts are now complete
        morning_exists = LatestLogEntry.objects.filter(
            carehome=instance.carehome,
            service_user=instance.service_user,
            date=instance.date,
            shift='morning'
        ).exists()

        afternoon_exists = LatestLogEntry.objects.filter(
            carehome=instance.carehome,
            service_user=instance.service_user,
            date=instance.date,
            shift='night'
        ).exists()

        if morning_exists and afternoon_exists:
            # Both shifts are logged, resolve any remaining missed logs
            instance.carehome.resolve_missed_logs(
                service_user=instance.service_user,
                date=instance.date
            )


@receiver(post_save, sender=CareHome)
def check_existing_missed_logs(sender, instance, created, **kwargs):
    """Check for missed logs when carehome is updated"""
    if not created:
        # Check for service users without logs in the last 6 months
        six_months_ago = timezone.now() - timedelta(days=180)
        for service_user in instance.service_users.all():
            for shift in ['morning', 'night']:
                has_log = service_user.latest_log_entries.filter(
                    date__gte=six_months_ago,
                    shift=shift,
                    status__in=['complete', 'locked']
                ).exists()

                if not has_log:
                    MissedLog.objects.get_or_create(
                        carehome=instance,
                        service_user=service_user,
                        date=timezone.now().date(),
                        shift=shift
                    )
