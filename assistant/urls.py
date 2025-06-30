from django.urls import path
from . import views

app_name = 'assistant'

urlpatterns = [
    path('', views.home, name='home'),
    path('api/chat/', views.chat_api, name='chat_api'),
    path('api/voice-chat/', views.voice_chat_api, name='voice_chat_api'),
    path('api/history/', views.chat_history, name='chat_history'),
] 