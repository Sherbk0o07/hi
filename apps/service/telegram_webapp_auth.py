# apps/service/telegram_webapp_auth.py
"""
Telegram WebApp initData ni tekshirish.
================================================
Telegram Mini App dan kelgan `initData` string ni tekshiradi.
Rasmiy docs:
https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

XUSUSIYATLAR:
- HMAC-SHA256 hash tekshiruvi
- auth_date muddati (24 soat)
- User ma'lumotlarini parse qilish
- Xatolarni boshqarish
"""
import hmac
import hashlib
import json
import logging
from urllib.parse import parse_qsl

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# 24 soat — initData shu vaqtdan keyin eskiradi
AUTH_DATE_MAX_AGE = 86400


class TelegramWebAppAuth:
    """Telegram WebApp initData verifikatsiya."""

    @staticmethod
    def verify(init_data: str, bot_token: str = None) -> dict | None:
        """
        initData ni tekshirish va user ma'lumotlarini qaytarish.
        
        Args:
            init_data: Telegram dan kelgan initData string
            bot_token: Bot token (default: settings.TELEGRAM_BOT_TOKEN)
            
        Returns:
            {
                'id': int,
                'first_name': str,
                'last_name': str,
                'username': str,
                'language_code': str,
                'is_premium': bool,
                ...
            }
            yoki None (xato bo'lsa)
        """
        if not init_data:
            logger.warning("initData bo'sh")
            return None

        if not bot_token:
            bot_token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
        
        if not bot_token:
            logger.error("TELEGRAM_BOT_TOKEN sozlanmagan!")
            return None

        # ─── 1. Parse qilish ───
        try:
            parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        except Exception as e:
            logger.warning(f"initData parse xatosi: {e}")
            return None

        received_hash = parsed.pop('hash', None)
        if not received_hash:
            logger.warning("initData'da hash yo'q")
            return None

        # ─── 2. data_check_string tuzish ───
        data_check = '\n'.join(
            f"{k}={v}" for k, v in sorted(parsed.items())
        )

        # ─── 3. Secret key = HMAC_SHA256(bot_token, "WebAppData") ───
        secret_key = hmac.new(
            b"WebAppData",
            bot_token.encode(),
            hashlib.sha256,
        ).digest()

        # ─── 4. Hisoblangan hash ───
        calc_hash = hmac.new(
            secret_key,
            data_check.encode(),
            hashlib.sha256,
        ).hexdigest()

        # ─── 5. Solishtirish ───
        if not hmac.compare_digest(calc_hash, received_hash):
            logger.warning("Telegram initData hash mos kelmadi")
            return None

        # ─── 6. auth_date tekshirish (24 soat) ───
        try:
            auth_date = int(parsed.get('auth_date', 0))
        except (ValueError, TypeError):
            auth_date = 0

        if auth_date:
            age = timezone.now().timestamp() - auth_date
            if age > AUTH_DATE_MAX_AGE:
                logger.warning(
                    f"Telegram initData eskirgan: {age:.0f} sek"
                )
                return None

        # ─── 7. User JSON ───
        user_json = parsed.get('user')
        if not user_json:
            logger.warning("initData'da user yo'q")
            return None

        try:
            user = json.loads(user_json)
        except json.JSONDecodeError as e:
            logger.warning(f"User JSON parse xatosi: {e}")
            return None

        if not user.get('id'):
            logger.warning("User'da id yo'q")
            return None

        logger.info(
            f"✅ Telegram WebApp auth OK: "
            f"id={user['id']}, username={user.get('username', '-')}"
        )
        return user

    @staticmethod
    def get_user_from_init_data(init_data: str) -> 'CustomUser | None':
        """
        initData dan CustomUser topish.
        
        Strategiya:
        1. TelegramLink.chat_id == tg_id → user
        2. TelegramLink.username == username → user (fallback)
        """
        tg_user = TelegramWebAppAuth.verify(init_data)
        if not tg_user:
            return None

        tg_id = tg_user.get('id')
        username = tg_user.get('username')

        from apps.user.models import TelegramLink

        # 1. chat_id orqali
        link = TelegramLink.objects.filter(
            chat_id=tg_id, is_active=True
        ).select_related('user').first()

        if link:
            return link.user

        # 2. username orqali (fallback)
        if username:
            link = TelegramLink.objects.filter(
                username__iexact=username, is_active=True
            ).select_related('user').first()
            if link:
                return link.user

        logger.warning(f"Telegram user {tg_id} topilmadi")
        return None


def auto_login_from_request(request):
    """
    So'rovdan initData olib, userni topib, login qilish.
    
    initData qayerdan olinadi:
    1. request.POST['init_data']
    2. request.GET['init_data']
    3. request.headers['X-Telegram-Init-Data']
    
    Agar allaqachon autentifikatsiya qilingan bo'lsa — o'sha user qaytariladi.
    """
    from django.contrib.auth import login

    # Allaqachon login qilganmi?
    if request.user.is_authenticated:
        return request.user

    # initData ni olish
    init_data = (
        request.POST.get('init_data')
        or request.GET.get('init_data')
        or request.headers.get('X-Telegram-Init-Data')
        or ''
    )

    if not init_data:
        logger.debug("initData topilmadi")
        return None

    # Userni topish
    user = TelegramWebAppAuth.get_user_from_init_data(init_data)
    if not user:
        return None

    # Login qilish
    login(
        request, user,
        backend='django.contrib.auth.backends.ModelBackend',
    )
    logger.info(f"✅ Auto-login: {user.phone_number}")
    return user