from django.urls import path, include

urlpatterns = [
    path('', include('apps.pages.urls.home')),
    path('login/', include('apps.pages.urls.login')),
    path('logout/', include('apps.pages.urls.logout')),
    path('settings/', include('apps.pages.urls.settings')),
    path('boshqaruv/kurslar/', include('apps.courses.admin_urls')),
    path('talaba/uyga-vazifalar/', include('apps.pages.urls.homework')),

]