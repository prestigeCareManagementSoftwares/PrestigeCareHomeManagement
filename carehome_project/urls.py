from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include

from carehome_project import settings

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
]
# Always serve media (dev + prod)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
