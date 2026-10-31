from django.urls import path

import apps.pages.views as views
urlpatterns = [
        path('',views.LoginPageView.as_view(),name='login_page_view'),
        path('login-img/view/',views.LoginImgView.as_view(),name='login_img_view'),
        path('create/img/view',views.CreateImgView.as_view(),name='create_img'),
        path('delete/login/img/<int:pk>/',views.delete_login_img,name="delete_login_img_view")
]