from django.contrib import admin
from django.urls import path
from django.views.generic import TemplateView
from api.views import (
    ChatAPI,
    GoogleAuthView,
    LoginView,
    LogoutView,
    MeView,
    RegisterView,
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/chat/', ChatAPI.as_view()),

    # Auth endpoints — match Flutter's AuthService exactly
    path('api/auth/register/', RegisterView.as_view()),
    path('api/auth/login/', LoginView.as_view()),
    path('api/auth/google/', GoogleAuthView.as_view()),
    path('api/auth/me/', MeView.as_view()),
    path('api/auth/logout/', LogoutView.as_view()),

    path('', TemplateView.as_view(template_name="index.html"), name='home'),
]
