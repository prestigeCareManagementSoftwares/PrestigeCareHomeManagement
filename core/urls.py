# core/urls.py
from django.conf.urls.static import static
from django.http import HttpResponseForbidden
from django.urls import path, re_path

from carehome_project import settings
from . import views
from .views import create_log_view, log_entry_form, save_log_entry, lock_log_entries, staff_latest_logs_view, \
    staff_mapping_view, delete_mapping

urlpatterns = ([
                   path('', views.login_view, name='login'),
                   path('dashboard/', views.dashboard, name='admin-dashboard'),
                   path('logout/', views.logout_view, name='logout'),
                   path('active-users/', views.active_users_view, name='active-users'),
                   path('missed-logs/', views.missed_shifts_view, name='missed-logs'),
                   path('staff/create/', views.create_staff, name='create-staff'),

                   # Carehomes URLs
                   path('carehomes/dashboard/', views.carehomes_dashboard, name='carehomes-dashboard'),
                   path('carehomes/create/', views.create_carehome, name='create-carehome'),

                   # Service Users URLs
                   path('service-users/dashboard/', views.service_users_dashboard, name='service-users-dashboard'),
                   path('service-users/create/', views.create_service_user, name='create-service-user'),
                   path('validate-postcode/', views.validate_postcode, name='validate-postcode'),
                   path('carehomes/edit/<int:id>/', views.edit_carehome, name='edit-carehome'),
                   path('carehomes/delete/<int:id>/', views.delete_carehome, name='delete-carehome'),
                   path('service-users/', views.service_users_dashboard, name='service-users-dashboard'),
                   path('service-users/create/', views.create_service_user, name='create-service-user'),
                   path('service-users/edit/<int:id>/', views.edit_service_user, name='edit-service-user'),
                   path('service-users/delete/<int:id>/', views.delete_service_user, name='delete-service-user'),
                   path('staff/', views.staff_dashboard, name='staff-dashboard'),
                   path('staff/create/', views.create_staff, name='create-staff'),
                   path('staff/edit/<int:pk>/', views.edit_staff, name='edit-staff'),
                   path('staff/toggle-status/<int:pk>/', views.toggle_staff_status, name='toggle-staff-status'),
                   path('abc/new/', views.fill_abc_form, name='fill_abc_form'),
                   path('abc/', views.abc_form_list, name='abc_form_list'),
                   path('abc/<int:form_id>/edit/', views.edit_abc_form, name='edit_abc_form'),
                   path('abc/<int:form_id>/', views.view_abc_form, name='view_abc_form'),
                   path('abc/<int:form_id>/pdf/', views.download_abc_pdf, name='download_abc_pdf'),
                   path('fill-incident/', views.fill_incident_form, name='fill_incident_form'),
                   path('incident-pdf/<int:form_id>/', views.download_incident_pdf, name='download_incident_pdf'),
                   path('create-log/', create_log_view, name='create-log'),
                   path('log-entry/<int:latest_log_id>/', log_entry_form, name='log-entry-form'),
                   path('save-log/<int:entry_id>/', save_log_entry, name='save-log'),
                   path('lock-log/<int:latest_log_id>/', lock_log_entries, name='lock-log'),
                   path('log/<int:pk>/', views.log_detail_view, name='log_detail_view'),
                   path('my-logs/', staff_latest_logs_view, name='staff_latest_logs_view'),
                   path('dashboard/staff-mapping/', views.staff_mapping_view, name='staff_mapping'),
                   path('ajax/fetch-service-users/', views.fetch_service_users, name='fetch_service_users'),
                   path('staff-mapping/', views.staff_mapping_view, name='staff-mapping'),
                   path('ajax/load-service-users/', views.load_service_users, name='ajax_load_service_users'),
                   path('incident-reports/', views.incident_report_list_view, name='incident_report_list'),
                   path('edit-incident/<int:form_id>/', views.edit_incident_form, name='edit_incident_form'),
                   path('incident/<int:pk>/', views.view_incident_report, name='view_incident_report'),
                   path('get-staff-by-carehome/', views.get_staff_by_carehome, name='get-staff-by-carehome'),
                   path('get-service-users-by-carehome/', views.get_service_users_by_carehome,
                        name='get-service-users-by-carehome'),
                   path('staff-mapping/', staff_mapping_view, name='staff-mapping'),
                   path('delete-mapping/<int:pk>/', delete_mapping, name='delete-mapping'),
                   re_path(r'^\.(git|svn|env)/', lambda r: HttpResponseForbidden()),
                   re_path(r'@fs/', lambda r: HttpResponseForbidden()),
               ]
               + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT))
