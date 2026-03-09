from django.contrib import admin
from django.urls import path
from django.views.generic import TemplateView  # 1. Import this
from api.views import ChatAPI

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/chat/', ChatAPI.as_view()),
    
    # 2. Add this line for the empty path
    path('', TemplateView.as_view(template_name="index.html"), name='home'),
]