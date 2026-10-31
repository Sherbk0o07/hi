from django.urls import path

import apps.pages.views as views


urlpatterns = [
    path('',views.logout_view,name='logout_view'),
]