"""
Sozlamalar sahifasi.
"""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView
from django.shortcuts import get_object_or_404
from apps.user.models import CustomUser


class SettingsView(LoginRequiredMixin, TemplateView):
    template_name = 's/settings.html'
import json
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from apps.service.notification_service import send_manual_sms


@require_POST
def admin_send_telegram_sms(request, user_id):
    """Admin foydalanuvchiga Telegram orqali qo‘lda xabar yuborish."""
    if not (request.user.is_authenticated and
            (request.user.is_superuser or request.user.role == 'admin')):
        return JsonResponse({'ok': False, 'error': 'Ruxsat yo‘q'}, status=403)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Noto‘g‘ri format'}, status=400)

    message = (data.get('message') or '').strip()
    if not message:
        return JsonResponse({'ok': False, 'error': 'Xabar bo‘sh'}, status=400)

    user = get_object_or_404(CustomUser, pk=user_id)

    success = send_manual_sms(user, message, request.user)

    if success:
        return JsonResponse({'ok': True, 'message': 'Xabar yuborildi'})
    return JsonResponse({'ok': False, 'error': 'Yuborishda xatolik'}, status=500)