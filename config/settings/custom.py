from django.conf.global_settings import LOGIN_REDIRECT_URL

from .base import  *
LOCAL_APP = [
    # 'apps.core.apps.CoreConfig',
    'apps.user.apps.UserConfig',
    'django_apscheduler',
    'apps.courses',
    'django.contrib.humanize',

]
EXTERNAL_APPS = [

]
SITE_URL = 'https://digion.uz'  # HTTPS bo‘lishi shart!

# settings.py
AUTH_USER_MODEL = 'user.CustomUser' # masalan, 'users.CustomUser'
INSTALLED_APPS.extend(LOCAL_APP)
INSTALLED_APPS.extend(EXTERNAL_APPS)

DEBUG = True

STATIC_ROOT = 'assents/'
STATICFILES_DIRS = [BASE_DIR / 'static']
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


LOGOUT_ON_GET = True
LOGIN_URL = 'login_page_view'
LOGIN_REDIRECT_URL = '/'

# ✅ YANGI (siz xohlagan):
SESSION_COOKIE_AGE = 60 * 60 * 8           # 8 soat (ish kuni uchun)
SESSION_EXPIRE_AT_BROWSER_CLOSE = True     # ⭐ Brauzer yopilsa qulf
SESSION_SAVE_EVERY_REQUEST = True          # Har so'rovda yangilash
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_HTTPONLY = True
SESSION_ENGINE = 'django.contrib.sessions.backends.db'

SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SMS_PROVIDER = 'eskiz'
SMS_API_URL = 'https://notify.eskiz.uz/api/message/sms/send'
SMS_API_KEY = 'sizning_api_kalitiniz'
SMS_SENDER = '4546'
# Email (dev uchun — terminalda ko‘rinadi)
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
DEFAULT_FROM_EMAIL = 'noreply@learncraft.uz'

# ═══════════════════════════════════════════════════════════════
# TELEGRAM BOT
# ═══════════════════════════════════════════════════════════════

TELEGRAM_BOT_TOKEN = '8931733840:AAFuIIVJ0Hi61ZYWaWq-RttxDUvQNvyK7ZQ'  # BotFather dan
TELEGRAM_BOT_USERNAME = 'digion_bot'  # @ belgisisiz

# ═══ ADMIN TELEGRAM ═══
ADMIN_TELEGRAM_CHAT_ID = 7981290942  # Sizning shaxsiy chat_id
# Trigger vaqtlari (soatlarda)
INACTIVE_4H_THRESHOLD = 4
INACTIVE_7H_THRESHOLD = 7
INACTIVE_1D_THRESHOLD = 24
INACTIVE_3D_THRESHOLD = 72


# ═══════════════════════════════════════════════════════════════
# XAVFSIZLIK LIMITLARI
# ═══════════════════════════════════════════════════════════════

# ─── Telegram kod ───
TELEGRAM_CODE_TTL = 60                    # Kod 60 sek amal qiladi
TELEGRAM_MAX_ATTEMPTS = 3                 # 3 ta noto‘g‘ri kod → o‘chirish
TELEGRAM_RESEND_COOLDOWN = 30             # 30 sek qayta yuborish
TELEGRAM_PHONE_BLOCK_MINUTES = 15         # 15 daqiqa phone blok
TELEGRAM_PHONE_MAX_PER_HOUR = 5           # 1 soatda 5 ta kod

# ─── IP cheklov ───
IP_MAX_TELEGRAM_REQUESTS = 10             # IP daqiqada max 10
IP_MAX_LOGIN_ATTEMPTS = 20                # IP daqiqada max 20
IP_BLOCK_MINUTES = 30                     # IP blok vaqti
IP_RATE_WINDOW_SECONDS = 60               # Oyna (1 daqiqa)

# ─── Global himoya ───
GLOBAL_MAX_TELEGRAM_PER_MINUTE = 100      # Butun tizim 1 daqiqada
GLOBAL_MAX_TELEGRAM_PER_HOUR = 1000       # 1 soatda
GLOBAL_SUSPICIOUS_THRESHOLD = 50          # Shubhali faollik

# ─── Cloudflare (agar ishlatilsa) ───
USE_CLOUDFLARE = True
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file_security': {
            'class': 'logging.FileHandler',
            'filename': 'logs/security.log',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'apps.pages.views.auth.login': {
            'handlers': ['console', 'file_security'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
SCHEDULER_DEFAULT = True
APSCHEDULER_DATETIME_FORMAT = "N j, Y, f:s a"
APSCHEDULER_RUN_NOW_TIMEOUT = 25