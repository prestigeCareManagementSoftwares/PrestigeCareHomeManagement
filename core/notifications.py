from .models import Notification

def send_notification(user, title, message, payload=None):
    Notification.objects.create(
        user=user,
        title=title,
        message=message,
        payload=payload or {}
    )
