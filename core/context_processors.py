from .models import Notification


def notification_context(request):
    if request.user.is_authenticated:
        unread_count = Notification.objects.filter(user=request.user, is_read=False).count()
        latest_notifications = Notification.objects.filter(user=request.user)[:5]
    else:
        unread_count = 0
        latest_notifications = []

    return {
        'notif_count': unread_count,
        'notif_list': latest_notifications
    }
