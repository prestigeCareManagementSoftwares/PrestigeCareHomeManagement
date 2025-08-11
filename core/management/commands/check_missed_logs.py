from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import CareHome


class Command(BaseCommand):
    help = 'Checks for missed logs across all carehomes'

    def handle(self, *args, **options):
        date = timezone.now().date()
        self.stdout.write(f"Checking for missed logs on {date}")

        for carehome in CareHome.objects.all():
            missed_count = carehome.check_missed_logs(date).count()
            if missed_count > 0:
                self.stdout.write(f"Found {missed_count} missed logs for {carehome.name}")

        self.stdout.write(self.style.SUCCESS("Completed missed logs check"))