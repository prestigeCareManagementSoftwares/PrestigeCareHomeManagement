from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

class Command(BaseCommand):
    help = "Generate qr_code_value and qr_code_image for existing users"

    def handle(self, *args, **options):
        User = get_user_model()
        qs = User.objects.all().order_by("id")
        total = qs.count()
        updated = 0

        for u in qs:
            before_val = u.qr_code_value
            before_img = bool(u.qr_code_image)

            # Calling save() will generate missing value/image using your model logic
            u.save()

            after_val = u.qr_code_value
            after_img = bool(u.qr_code_image)

            if (before_val != after_val) or (before_img != after_img):
                updated += 1
                self.stdout.write(f"Updated user {u.id}: {u.email}")

        self.stdout.write(self.style.SUCCESS(f"Done. {updated}/{total} users updated."))
