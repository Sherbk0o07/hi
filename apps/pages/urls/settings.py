from django.urls import path

import apps.pages.views as views
urlpatterns = [
        path('',views.SettingsView.as_view(),name='settings_view')
]