from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include, re_path

from carehome_project import settings
from core.views import serve_media

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls'))
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    # Production: use the custom view
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', serve_media),
    ]
