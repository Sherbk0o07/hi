# apps/pages/urls/homework.py
"""
Talaba uyga vazifa URL'lari.
"""
from django.urls import path

from apps.pages.views.homework import (
    StudentHomeworkListView,
    StudentHomeworkDetailView,
)


app_name = 'student_homework'

urlpatterns = [
    # ⭐ BUGUNGI UYGA VAZIFALAR RO'YXATI
    path('',StudentHomeworkListView.as_view(),name='list'),
    # Bitta uyga vazifa
    path('<int:pk>/',StudentHomeworkDetailView.as_view(),name='detail'),
]