"""
URL configuration for pastor_ai project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin # Keep this to access the UI
from django.urls import path, re_path
from core.views import ChatAPIView, IngestedDocumentsAPIView, IngestedDocumentFileAPIView, SermonPdfByNameAPIView
from .frontend import serve_frontend

urlpatterns = [
    # This lets you go to http://localhost:8001/admin/ to see your database
    path('admin/', admin.site.urls), 

    # This is what your Flutter app will hit
    path('api/chat/', ChatAPIView.as_view(), name='chat_api'),
    path('api/ingested-documents/', IngestedDocumentsAPIView.as_view(), name='ingested_documents_api'),
    path('api/ingested-documents/<int:document_id>/file/', IngestedDocumentFileAPIView.as_view(), name='ingested_document_file_api'),
    # Backward-compatible route for existing Flutter builds that open /sermons/<name>.pdf directly.
    path('sermons/<str:sermon_name>.pdf', SermonPdfByNameAPIView.as_view(), name='sermon_pdf_by_name'),
    # Legacy alias: older Flutter builds POST to /chat/; route here so CSRF does not hit serve_frontend.
    path('chat/', ChatAPIView.as_view(), name='chat_api_legacy'),

    # Serve Flutter web build and client-side routes from /
    path("", serve_frontend, name="home"),
    re_path(r"^(?!admin/|api/|static/|chat/|admin/core/ingested-documents/)(?P<path>.*)$", serve_frontend, name="frontend"),
# If this breaks remove |sermons/
]
