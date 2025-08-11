# core/templatetags/custom_filters.py
from django import template

register = template.Library()

@register.filter
def filter_service_user(logs, service_user):
    """Filter logs by service user"""
    return [log for log in logs if log.service_user == service_user]