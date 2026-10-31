from django.contrib import admin

# Register your models here.

from .models import  *


admin.site.register([])

from .models import LoginModel
from apps.service.login_service import LoginService
import apps.user.models as m
from django.contrib import admin
from .models import LoginModel


@admin.register(LoginModel)
class LoginAdmin(admin.ModelAdmin):

    def save_model(self, request, obj, form, change):
        # 1️⃣ Avval obj ni saqlaymiz, pk hosil bo‘lsin
        if not obj.pk:
            obj.save()

        # 2️⃣ Keyin service orqali activate qilamiz
        if obj.is_active:
            LoginService.activate(obj)