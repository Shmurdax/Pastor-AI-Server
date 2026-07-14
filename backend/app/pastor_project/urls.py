from django.contrib import admin
from django.urls import path, re_path
from django.views.generic import TemplateView
from django.views.static import serve
from django.conf import settings
import os

# 1. The API import (Make sure 'api' has an __init__.py file)
from api.views import ChatAPI, PrayerRequestAPI 

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/chat/', ChatAPI.as_view()),
    path('api/prayer-requests/', PrayerRequestAPI.as_view()),
    
    # 2. Redirect root requests to the 'static' folder
    # This specifically catches the service worker and manifest that Flutter looks for at /
    re_path(r'^(?P<path>(flutter_service_worker.js|manifest.json|flutter.js.map))$', serve, {
        'document_root': os.path.join(settings.BASE_DIR, 'static'),
    }),

    # 3. Serve the index.html from your templates or static folder
    # If index.html is in your 'static' folder, use 'static/index.html'
    path('', TemplateView.as_view(template_name="index.html"), name='home'),

    # 4. Fallback: Catch-all for other flutter assets (main.dart.js, etc.)
    re_path(r'^(?P<path>.*)$', serve, {
        'document_root': os.path.join(settings.BASE_DIR, 'static'),
    }),
]