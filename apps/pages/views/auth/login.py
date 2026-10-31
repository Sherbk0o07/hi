"""
Autentifikatsiya: Login (parol), OTP (SMS), Telegram, Logout.
========================================================================
5 QATLAMLI XAVFSIZLIK HIMOYASI:
1. Global rate limiting (DDoS)
2. IP rate limiting + blok
3. Phone rate limiting + blok
4. Kod urinish limiting
5. Bot spam himoyasi
"""
import random
import re
import logging
from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import (
    authenticate, login, logout, get_user_model,
)
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse, NoReverseMatch
from django.utils import timezone
from django.views import View

logger = logging.getLogger(__name__)
User = get_user_model()


# ═══════════════════════════════════════════════════════════════
# KONSTANTALAR
# ═══════════════════════════════════════════════════════════════

PHONE_REGEX = re.compile(r'^\+?998\d{9}$')

# OTP (SMS)
OTP_CACHE_PREFIX = 'otp_login_'
OTP_ATTEMPT_PREFIX = 'otp_attempts_'
OTP_TTL = 300
OTP_RESEND_COOLDOWN = 60
OTP_MAX_ATTEMPTS = 5

# Telegram
TG_CODE_PREFIX = 'tg_login_code_'
TG_ATTEMPT_PREFIX = 'tg_login_attempt_'
TG_RESEND_PREFIX = 'tg_login_resend_'

# Session
REMEMBER_ME_DAYS = 30

# Xavfsizlik
IP_BLOCK_PREFIX = 'block_ip_'
PHONE_BLOCK_PREFIX = 'block_phone_'
IP_RATE_PREFIX = 'rl_ip_'
GLOBAL_RATE_PREFIX = 'rl_global_'
SUSPICIOUS_PREFIX = 'suspicious_'


# ═══════════════════════════════════════════════════════════════
# XAVFSIZLIK SERVISI (INLINE — tashqi fayl kerak emas)
# ═══════════════════════════════════════════════════════════════

import hashlib


def _hash(value: str) -> str:
    """Xavfsiz hash (cache key uchun)."""
    return hashlib.sha256(str(value).encode()).hexdigest()[:16]


def get_client_ip(request) -> str:
    """Foydalanuvchi IP manzilini olish (Cloudflare, proxy-friendly)."""
    # Cloudflare
    cf_ip = request.META.get('HTTP_CF_CONNECTING_IP')
    if cf_ip:
        return cf_ip.strip()

    # X-Forwarded-For
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()

    # X-Real-IP
    xri = request.META.get('HTTP_X_REAL_IP')
    if xri:
        return xri.strip()

    return request.META.get('REMOTE_ADDR', '0.0.0.0')


def check_rate_limit(key: str, max_requests: int, window_seconds: int) -> tuple:
    """
    Rate limit tekshirish.
    Returns: (is_allowed, remaining, reset_in)
    """
    cache_key = f"rl_{key}"
    now = timezone.now()

    data = cache.get(cache_key, {'count': 0, 'start': now.timestamp()})

    # Oyna tugaganmi?
    elapsed = now.timestamp() - data['start']
    if elapsed >= window_seconds:
        data = {'count': 1, 'start': now.timestamp()}
        cache.set(cache_key, data, timeout=window_seconds)
        return True, max_requests - 1, window_seconds

    # Limit oshib ketdimi?
    if data['count'] >= max_requests:
        reset_in = int(window_seconds - elapsed)
        return False, 0, reset_in

    # Hisoblash
    data['count'] += 1
    cache.set(cache_key, data, timeout=window_seconds)

    remaining = max_requests - data['count']
    reset_in = int(window_seconds - elapsed)
    return True, remaining, reset_in


def check_ip_rate_limit(ip: str, action: str = 'telegram') -> tuple:
    """IP darajasida rate limiting."""
    limits = {
        'telegram': getattr(settings, 'IP_MAX_TELEGRAM_REQUESTS', 10),
        'login': getattr(settings, 'IP_MAX_LOGIN_ATTEMPTS', 20),
    }
    window = getattr(settings, 'IP_RATE_WINDOW_SECONDS', 60)
    max_req = limits.get(action, 10)
    return check_rate_limit(f"ip_{_hash(ip)}_{action}", max_req, window)


def check_global_limit(action: str = 'telegram') -> tuple:
    """Global limit — butun tizim uchun DDoS himoyasi."""
    limits = {
        'telegram': getattr(settings, 'GLOBAL_MAX_TELEGRAM_PER_MINUTE', 100),
    }
    max_req = limits.get(action, 100)
    return check_rate_limit(f"global_{action}", max_req, 60)


def block_ip(ip: str, minutes: int = None, reason: str = ''):
    """IP manzilni vaqtinchalik bloklash."""
    minutes = minutes or getattr(settings, 'IP_BLOCK_MINUTES', 30)
    cache.set(
        f"{IP_BLOCK_PREFIX}{_hash(ip)}",
        {'reason': reason, 'blocked_at': timezone.now().isoformat()},
        timeout=minutes * 60
    )
    logger.warning(f"[SECURITY] 🚨 IP bloklandi: {ip} | {reason} | {minutes}daq")


def is_ip_blocked(ip: str) -> tuple:
    """IP bloklanganmi?"""
    data = cache.get(f"{IP_BLOCK_PREFIX}{_hash(ip)}")
    if data:
        try:
            blocked_at = timezone.datetime.fromisoformat(data['blocked_at'])
            elapsed = (timezone.now() - blocked_at).total_seconds()
            block_sec = getattr(settings, 'IP_BLOCK_MINUTES', 30) * 60
            remaining = int(block_sec - elapsed)
            return True, max(0, remaining)
        except Exception:
            return True, 1800
    return False, 0


def block_phone(phone: str, minutes: int = None, reason: str = ''):
    """Telefon raqamni vaqtinchalik bloklash."""
    minutes = minutes or getattr(settings, 'TELEGRAM_PHONE_BLOCK_MINUTES', 15)
    cache.set(
        f"{PHONE_BLOCK_PREFIX}{_hash(phone)}",
        {'reason': reason, 'blocked_at': timezone.now().isoformat()},
        timeout=minutes * 60
    )
    logger.warning(f"[SECURITY] 🚨 Phone bloklandi: {phone} | {reason}")


def is_phone_blocked(phone: str) -> tuple:
    """Telefon bloklanganmi?"""
    data = cache.get(f"{PHONE_BLOCK_PREFIX}{_hash(phone)}")
    if data:
        try:
            blocked_at = timezone.datetime.fromisoformat(data['blocked_at'])
            elapsed = (timezone.now() - blocked_at).total_seconds()
            block_sec = getattr(settings, 'TELEGRAM_PHONE_BLOCK_MINUTES', 15) * 60
            remaining = int(block_sec - elapsed)
            return True, max(0, remaining)
        except Exception:
            return True, 900
    return False, 0


def record_suspicious_activity(ip: str, reason: str = '') -> bool:
    """Shubhali faollikni qayd etish. True → bloklash kerak."""
    key = f"{SUSPICIOUS_PREFIX}{_hash(ip)}"
    count = cache.get(key, 0) + 1
    cache.set(key, count, timeout=3600)

    threshold = getattr(settings, 'GLOBAL_SUSPICIOUS_THRESHOLD', 50)
    if count >= threshold:
        block_ip(ip, minutes=60, reason=f"Ko‘p shubhali faollik: {reason}")
        logger.critical(f"[SECURITY] 🚨🚨 AVTOMATIK BLOK: {ip} | {count} shubhali")
        return True
    return False


def log_security_event(event_type: str, ip: str = '', phone: str = '',
                       details: str = '', severity: str = 'INFO'):
    """Xavfsizlik hodisasini log qilish."""
    prefix = {'INFO': 'ℹ️', 'WARNING': '⚠️', 'ERROR': '❌', 'CRITICAL': '🚨'}.get(severity, 'ℹ️')
    msg = f"{prefix} [{event_type}]"
    if ip:
        msg += f" IP={ip}"
    if phone:
        msg += f" PHONE={phone}"
    if details:
        msg += f" | {details}"
    if severity in ('WARNING', 'ERROR', 'CRITICAL'):
        logger.warning(msg)
    else:
        logger.info(msg)


# ═══════════════════════════════════════════════════════════════
# YORDAMCHI FUNKSIYALAR
# ═══════════════════════════════════════════════════════════════

def normalize_phone(raw: str) -> str:
    if not raw:
        return ''
    digits = re.sub(r'\D', '', str(raw))
    if digits.startswith('998'):
        digits = digits[3:]
    if len(digits) != 9:
        return ''
    return f"+998{digits}"


def is_valid_phone(phone: str) -> bool:
    return bool(PHONE_REGEX.match(phone or ''))


def generate_otp() -> str:
    return f"{random.randint(0, 999999):06d}"


def mask_phone(phone: str) -> str:
    if not phone or len(phone) < 12:
        return phone or ''
    return f"+998 ** *** ** {phone[-2:]}"


def send_sms_otp(phone: str, code: str) -> bool:
    try:
        logger.info(f"[SMS] {phone} → {code}")
        print(f"📱 [SMS MOCK] {phone} → Kod: {code}")
        return True
    except Exception as e:
        logger.exception(f"SMS xatosi: {e}")
        return False


def get_success_url_for(user) -> str:
    if not user or not user.is_authenticated:
        return reverse('login_page_view')

    role = getattr(user, 'role', None)

    if user.is_superuser or role == 'admin':
        try:
            return reverse('admin_dashboard')
        except NoReverseMatch:
            return '/boshqaruv/'

    if role == 'parent':
        try:
            return reverse('parent_dashboard')
        except NoReverseMatch:
            return '/parent/dashboard/'

    try:
        return reverse('home_page_view')
    except NoReverseMatch:
        return '/'


def log_activity(user, request, action='login'):
    try:
        from apps.user.models import ActivityLog
        if action == 'login':
            ActivityLog.objects.create(
                user=user,
                login_time=timezone.now(),
                ip_address=get_client_ip(request),
            )
        elif action == 'logout':
            log = ActivityLog.objects.filter(
                user=user, logout_time__isnull=True
            ).order_by('-login_time').first()
            if log:
                log.logout_time = timezone.now()
                if log.login_time:
                    log.total_seconds = int(
                        (log.logout_time - log.login_time).total_seconds()
                    )
                log.save(update_fields=['logout_time', 'total_seconds'])
    except Exception as e:
        logger.warning(f"ActivityLog xatosi: {e}")


# ═══════════════════════════════════════════════════════════════
# CUSTOM AUTHENTICATION FORM
# ═══════════════════════════════════════════════════════════════

class PhoneAuthenticationForm(AuthenticationForm):
    """Phone raqam + parol bilan autentifikatsiya."""

    phone_number = forms.CharField(
        label="Telefon raqam",
        max_length=17,
        widget=forms.TextInput(attrs={
            'autofocus': True,
            'autocomplete': 'off',
            'placeholder': '+998 90 123 45 67',
            'id': 'phone',
            'class': 'field-input',
        })
    )

    password = forms.CharField(
        label="Parol",
        strip=False,
        widget=forms.PasswordInput(attrs={
            'autocomplete': 'off',
            'placeholder': ' ',
            'id': 'password',
            'class': 'field-input',
        })
    )

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        if 'username' in self.fields:
            del self.fields['username']

    def clean(self):
        phone = self.cleaned_data.get('phone_number')
        password = self.cleaned_data.get('password')

        if phone and password:
            normalized = normalize_phone(phone)
            self.user_cache = authenticate(
                self.request,
                username=normalized,
                password=password,
            )
            if self.user_cache is None:
                raise forms.ValidationError(
                    "Telefon raqam yoki parol noto‘g‘ri.",
                    code='invalid_login',
                )
            else:
                self.confirm_login_allowed(self.user_cache)

        return self.cleaned_data


# ═══════════════════════════════════════════════════════════════
# 1. LOGIN PAGE — PAROL BILAN
# ═══════════════════════════════════════════════════════════════

class LoginPageView(LoginView):
    template_name = 'login.html'
    authentication_form = PhoneAuthenticationForm
    redirect_authenticated_user = True

    def get_success_url(self):
        next_url = self.get_redirect_url()
        if next_url:
            return next_url
        return get_success_url_for(self.request.user)

    def get_redirect_url(self, *args, **kwargs):
        url = super().get_redirect_url(*args, **kwargs)
        if url and url.startswith('/'):
            return url
        return ''

    def form_invalid(self, form):
        messages.error(self.request, "Telefon raqam yoki parol noto‘g‘ri.")
        return super().form_invalid(form)

    def post(self, request, *args, **kwargs):
        ip = get_client_ip(request)

        # ═══ XAVFSIZLIK: IP blok ═══
        blocked, remaining = is_ip_blocked(ip)
        if blocked:
            log_security_event('IP_BLOCKED_LOGIN', ip=ip,
                               details=f"{remaining}s qoldi", severity='WARNING')
            messages.error(request, f"IP bloklangan. {remaining} sekunddan so‘ng urinib ko‘ring.")
            return self.render_to_response(self.get_context_data())

        # ═══ XAVFSIZLIK: IP rate limit ═══
        allowed, rem, reset_in = check_ip_rate_limit(ip, 'login')
        if not allowed:
            is_abuser = record_suspicious_activity(ip, 'login rate limit')
            if is_abuser:
                block_ip(ip, minutes=60, reason="Login rate limit abuse")
            log_security_event('IP_RATE_LIMIT_LOGIN', ip=ip,
                               details=f"{reset_in}s kutilmoqda", severity='WARNING')
            messages.error(request, f"Juda ko‘p urinish. {reset_in} sekund kuting.")
            return self.render_to_response(self.get_context_data())

        response = super().post(request, *args, **kwargs)

        if request.user.is_authenticated:
            remember = request.POST.get('remember_me') in ('on', 'true', '1')
            if remember:
                request.session.set_expiry(timedelta(days=REMEMBER_ME_DAYS))
            else:
                request.session.set_expiry(0)
            log_activity(request.user, request, 'login')

            # ⚡ ADMIN XABARI
            try:
                from apps.service.notification_service import notify_admin_about_login
                notify_admin_about_login(request.user, 'password', request)
            except Exception as e:
                logger.warning(f"Admin xabar xatosi: {e}")

            # ⚡ QAYTIB KELGAN XABARI
            try:
                from apps.service.notification_service import send_welcome_back
                send_welcome_back(request.user, request)
            except Exception as e:
                logger.warning(f"Welcome back xatosi: {e}")

        return response

    # ═══ KONTEKST ═══
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['telegram_bot_username'] = getattr(
            settings, 'TELEGRAM_BOT_USERNAME', 'digion_bot'
        )

        # Greeting
        hour = timezone.localtime().hour
        if 5 <= hour < 12:
            ctx['greeting'] = {'text': 'Xayrli tong', 'emoji': '🌅', 'sub': 'Yangi kun yangi imkoniyat'}
        elif 12 <= hour < 18:
            ctx['greeting'] = {'text': 'Xayrli kun', 'emoji': '☀️', 'sub': 'Bugun nimalar o‘rganamiz?'}
        elif 18 <= hour < 22:
            ctx['greeting'] = {'text': 'Xayrli kech', 'emoji': '🌆', 'sub': 'Kechki bilim olish sessiyasi'}
        else:
            ctx['greeting'] = {'text': 'Xayrli tun', 'emoji': '🌙', 'sub': 'Tungi bilim — eng kuchli'}

        ctx['brand'] = {
            'name': 'DIGION',
            'tagline': 'Zamonaviy ta’lim platformasi',
            'logo_icon': 'fas fa-bolt',
            'showcase_title_line1': 'Bilim olish —',
            'showcase_accent': 'san’at',
            'showcase_description': 'Platformamiz orqali o‘qish jarayonini o‘yin, tajriba va haqiqiy natijaga aylantiring.',
        }

        ctx['tag'] = {'text': 'Yangi avlod platformasi', 'dot_color': '#4ade80'}

        ctx['features'] = [
            {'icon': 'fas fa-rocket', 'gradient': 'linear-gradient(135deg,#8b5cf6,#6366f1)',
             'title': 'Tezkor o‘rganish', 'subtitle': 'Interaktiv darslar va testlar',
             'metric': '1200+', 'metric_label': 'Testlar'},
            {'icon': 'fas fa-trophy', 'gradient': 'linear-gradient(135deg,#ec4899,#f43f5e)',
             'title': 'Mukofotlar', 'subtitle': 'Coinlar, ligalar va yutuqlar',
             'metric': '50+', 'metric_label': 'Yutuqlar'},
            {'icon': 'fas fa-chart-line', 'gradient': 'linear-gradient(135deg,#06b6d4,#0891b2)',
             'title': 'Statistika', 'subtitle': 'Natijalarni kuzatib boring',
             'metric': '24/7', 'metric_label': 'Monitoring'},
            {'icon': 'fas fa-users', 'gradient': 'linear-gradient(135deg,#10b981,#059669)',
             'title': 'Hamjamiyat', 'subtitle': 'Do‘stlar bilan bellashing',
             'metric': '12K+', 'metric_label': 'A’zolar'},
        ]

        ctx['stats'] = self._get_stats()

        ctx['form_header'] = {
            'title': 'Xush kelibsiz',
            'emoji': '👋',
            'subtitle': 'Hisobingizga kirish uchun ma’lumotlarni kiriting',
        }

        ctx['login_modes'] = [
            {'key': 'password', 'label': 'Parol', 'icon': 'fas fa-lock'},
            {'key': 'otp', 'label': 'SMS kod', 'icon': 'fas fa-comment-sms'},
        ]

        ctx['fields'] = {
            'phone_label': 'Telefon raqam',
            'phone_placeholder': '+998 90 123 45 67',
            'password_label': 'Parol',
            'password_placeholder': 'Kamida 6 belgi',
            'forgot_link_text': 'Unutdingizmi?',
            'remember_text': 'Eslab qolish',
            'submit_text': 'Kirish',
        }

        ctx['otp'] = {
            'send_text': 'Kod yuborish',
            'heading': 'Tasdiqlash kodi',
            'resend_text': 'Qayta yuborish',
            'change_phone_text': 'O‘zgartirish',
            'verify_text': 'Tasdiqlash',
            'seconds': OTP_RESEND_COOLDOWN,
        }

        ctx['divider_text'] = 'yoki'

        ctx['social_providers'] = [
            {'key': 'google', 'icon': 'fab fa-google', 'color': '#ea4335', 'url': '#'},
            {'key': 'telegram', 'icon': 'fab fa-telegram', 'color': '#229ed9', 'url': '#'},
            {'key': 'apple', 'icon': 'fab fa-apple', 'color': '#000', 'url': '#'},
        ]

        ctx['footer'] = {
            'text': 'Hisobingiz yo‘qmi?',
            'link_text': 'Ro‘yxatdan o‘tish',
            'link_url': '/',
        }

        ctx['trust_badges'] = [
            {'icon': 'fas fa-shield-halved', 'text': 'SSL himoya'},
            {'icon': 'fas fa-lock', 'text': 'Maxfiy'},
            {'icon': 'fas fa-headset', 'text': '24/7 yordam'},
        ]

        ctx['theme'] = {
            'brand_1': '#6366f1', 'brand_2': '#8b5cf6',
            'brand_3': '#ec4899', 'brand_4': '#06b6d4', 'brand_5': '#10b981',
        }

        ctx['meta'] = {
            'title': 'Kirish · DIGION',
            'description': 'DIGION — zamonaviy ta’lim platformasi.',
            'keywords': 'ta’lim, testlar, kurslar, online',
        }

        return ctx

    def _get_stats(self):
        try:
            from apps.user.models import StudentProfile, Course
            students = StudentProfile.objects.filter(status='active').count()
            courses = Course.objects.filter(is_active=True).count()
            return [
                {'value': max(students, 12450), 'suffix': '+', 'label': 'O‘quvchilar', 'icon': 'fas fa-user-graduate'},
                {'value': max(courses, 512), 'suffix': '+', 'label': 'Kurslar', 'icon': 'fas fa-book'},
                {'value': 98, 'suffix': '%', 'label': 'Mamnunlik', 'icon': 'fas fa-heart'},
            ]
        except Exception as e:
            logger.warning(f"Stats xatosi: {e}")
            return [
                {'value': 12450, 'suffix': '+', 'label': 'O‘quvchilar', 'icon': 'fas fa-user-graduate'},
                {'value': 512, 'suffix': '+', 'label': 'Kurslar', 'icon': 'fas fa-book'},
                {'value': 98, 'suffix': '%', 'label': 'Mamnunlik', 'icon': 'fas fa-heart'},
            ]


# ═══════════════════════════════════════════════════════════════
# 2. OTP (SMS) — YUBORISH + TEKSHIRISH
# ═══════════════════════════════════════════════════════════════

class LoginOTPView(View):
    """SMS orqali kod yuborish."""

    def post(self, request, *args, **kwargs):
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        ip = get_client_ip(request)

        # ═══ XAVFSIZLIK: IP blok ═══
        blocked, remaining = is_ip_blocked(ip)
        if blocked:
            return self._error(request, is_ajax,
                               f"IP bloklangan. {remaining} sekund kuting.", 429)

        # ═══ XAVFSIZLIK: Global limit ═══
        allowed, rem, reset_in = check_global_limit('telegram')
        if not allowed:
            log_security_event('GLOBAL_LIMIT', ip=ip, severity='CRITICAL')
            return self._error(request, is_ajax,
                               "Tizim juda band. Birozdan so‘ng.", 429)

        # ═══ XAVFSIZLIK: IP rate limit ═══
        allowed, rem, reset_in = check_ip_rate_limit(ip, 'telegram')
        if not allowed:
            record_suspicious_activity(ip, 'otp rate limit')
            return self._error(request, is_ajax,
                               f"Juda ko‘p so‘rov. {reset_in}s kuting.", 429)

        phone_raw = request.POST.get('phone_number', '').strip()
        phone = normalize_phone(phone_raw)

        if not is_valid_phone(phone):
            return self._error(request, is_ajax, "Telefon raqam noto‘g‘ri.", 400)

        # ═══ XAVFSIZLIK: Phone blok ═══
        blocked, remaining = is_phone_blocked(phone)
        if blocked:
            minutes = remaining // 60
            return self._error(request, is_ajax,
                               f"Bu raqam {minutes} daqiqaga bloklangan.", 429)

        try:
            user = User.objects.get(phone_number=phone)
        except User.DoesNotExist:
            return self._error(request, is_ajax, "Bu raqam tizimda yo‘q.", 404)

        if not user.is_active:
            return self._error(request, is_ajax, "Hisobingiz bloklangan.", 403)

        # Rate limit (30 sek)
        rate_key = f"otp_send_{phone}"
        last_sent = cache.get(rate_key)
        if last_sent:
            elapsed = (timezone.now() - last_sent).total_seconds()
            if elapsed < OTP_RESEND_COOLDOWN:
                remaining = int(OTP_RESEND_COOLDOWN - elapsed)
                return self._error(request, is_ajax,
                                   f"{remaining} sekunddan so‘ng qayta yuboring.", 429)

        code = generate_otp()
        cache.set(f"{OTP_CACHE_PREFIX}{phone}", {
            'code': code, 'user_id': user.id,
            'created_at': timezone.now().isoformat(),
        }, timeout=OTP_TTL)
        cache.delete(f"{OTP_ATTEMPT_PREFIX}{phone}")

        if not send_sms_otp(phone, code):
            cache.delete(f"{OTP_CACHE_PREFIX}{phone}")
            return self._error(request, is_ajax, "SMS yuborishda xatolik.", 500)

        cache.set(rate_key, timezone.now(), timeout=OTP_RESEND_COOLDOWN)
        request.session['otp_phone'] = phone

        if is_ajax:
            return JsonResponse({
                'ok': True, 'message': "SMS kod yuborildi.",
                'masked_phone': mask_phone(phone),
                'expires_in': OTP_TTL, 'cooldown': OTP_RESEND_COOLDOWN,
            })

        messages.success(request, "SMS kod yuborildi.")
        return redirect('login_page_view')

    @staticmethod
    def _error(request, is_ajax, message, status=400):
        if is_ajax:
            return JsonResponse({'ok': False, 'error': message}, status=status)
        messages.error(request, message)
        return redirect('login_page_view')


class VerifyOTPView(View):
    """SMS kodni tekshirish."""

    def post(self, request, *args, **kwargs):
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        ip = get_client_ip(request)

        # ═══ XAVFSIZLIK ═══
        blocked, remaining = is_ip_blocked(ip)
        if blocked:
            return self._error(request, is_ajax,
                               f"IP bloklangan. {remaining}s kuting.", 429)

        allowed, rem, reset_in = check_ip_rate_limit(ip, 'login')
        if not allowed:
            record_suspicious_activity(ip, 'verify rate limit')
            return self._error(request, is_ajax,
                               f"Juda ko‘p urinish. {reset_in}s kuting.", 429)

        code = (request.POST.get('otp_code') or request.POST.get('code') or '').strip()
        phone = request.POST.get('phone_number') or request.session.get('otp_phone') or ''
        phone = normalize_phone(phone)
        next_url = request.POST.get('next') or request.GET.get('next') or ''

        if not phone or not is_valid_phone(phone):
            return self._error(request, is_ajax, "Telefon raqam topilmadi.", 400)
        if not code or len(code) != 6 or not code.isdigit():
            return self._error(request, is_ajax, "Kod 6 xonali bo‘lishi kerak.", 400)

        attempt_key = f"{OTP_ATTEMPT_PREFIX}{phone}"
        attempts = cache.get(attempt_key, 0)

        if attempts >= OTP_MAX_ATTEMPTS:
            cache.delete(f"{OTP_CACHE_PREFIX}{phone}")
            block_phone(phone, minutes=15, reason="SMS OTP 5 marta noto‘g‘ri")
            return self._error(request, is_ajax,
                               "Juda ko‘p urinish. 15 daqiqaga bloklandingiz.", 429)

        cached = cache.get(f"{OTP_CACHE_PREFIX}{phone}")
        if not cached:
            return self._error(request, is_ajax, "Kod muddati tugagan.", 410)

        if cached['code'] != code:
            cache.set(attempt_key, attempts + 1, timeout=OTP_TTL)
            remaining = OTP_MAX_ATTEMPTS - attempts - 1
            log_security_event('WRONG_OTP', ip=ip, phone=phone,
                               details=f"{attempts+1}/{OTP_MAX_ATTEMPTS}", severity='WARNING')

            if attempts + 1 >= OTP_MAX_ATTEMPTS:
                block_phone(phone, minutes=15, reason="5 noto‘g‘ri OTP")
                block_ip(ip, minutes=30, reason="OTP brute-force")
                log_security_event('PHONE_IP_BLOCKED', ip=ip, phone=phone,
                                   details="OTP brute-force", severity='CRITICAL')
                return self._error(request, is_ajax,
                                   "Juda ko‘p noto‘g‘ri. 15 daqiqaga blok.", 429)

            return self._error(request, is_ajax,
                               f"Kod noto‘g‘ri. {remaining} ta urinish qoldi.", 400)

        try:
            user = User.objects.get(id=cached['user_id'])
        except User.DoesNotExist:
            return self._error(request, is_ajax, "Foydalanuvchi topilmadi.", 404)

        if not user.is_active:
            return self._error(request, is_ajax, "Hisobingiz bloklangan.", 403)

        cache.delete(f"{OTP_CACHE_PREFIX}{phone}")
        cache.delete(attempt_key)
        request.session.pop('otp_phone', None)

        login(request, user)
        request.session.set_expiry(timedelta(days=REMEMBER_ME_DAYS))
        log_activity(user, request, 'login')

        try:
            from apps.service.notification_service import notify_admin_about_login
            notify_admin_about_login(user, 'otp', request)
        except Exception as e:
            logger.warning(f"Admin xabar: {e}")

        redirect_url = next_url or get_success_url_for(user)

        if is_ajax:
            return JsonResponse({'ok': True, 'message': "Muvaffaqiyatli kirdingiz!", 'redirect': redirect_url})

        messages.success(request, f"Xush kelibsiz, {user.get_full_name() or user.phone_number}!")
        return redirect(redirect_url)

    @staticmethod
    def _error(request, is_ajax, message, status=400):
        if is_ajax:
            return JsonResponse({'ok': False, 'error': message}, status=status)
        messages.error(request, message)
        return redirect('login_page_view')


# ═══════════════════════════════════════════════════════════════
# 3. TELEGRAM LOGIN — YUBORISH + TEKSHIRISH
# ═══════════════════════════════════════════════════════════════

class TelegramSendCodeView(View):
    """Telegram orqali 1 daqiqalik kod yuborish."""

    def post(self, request, *args, **kwargs):
        from apps.service.telegram_bot import send_login_code
        from apps.user.models import TelegramLink

        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        ip = get_client_ip(request)

        # ═══ 1. IP blok ═══
        blocked, remaining = is_ip_blocked(ip)
        if blocked:
            log_security_event('IP_BLOCKED_TG', ip=ip, severity='WARNING')
            return self._err(request, is_ajax,
                             f"IP bloklangan. {remaining}s kuting.", 429)

        # ═══ 2. Global DDoS limit ═══
        allowed, rem, reset_in = check_global_limit('telegram')
        if not allowed:
            log_security_event('GLOBAL_LIMIT_TG', ip=ip,
                               details=f"{reset_in}s", severity='CRITICAL')
            return self._err(request, is_ajax,
                             "Tizim juda band. Birozdan so‘ng urinib ko‘ring.", 429)

        # ═══ 3. IP rate limit ═══
        allowed, rem, reset_in = check_ip_rate_limit(ip, 'telegram')
        if not allowed:
            is_abuser = record_suspicious_activity(ip, 'telegram rate limit')
            if is_abuser:
                block_ip(ip, minutes=60, reason="Telegram rate limit abuse")
            log_security_event('IP_RATE_TG', ip=ip, details=f"{reset_in}s", severity='WARNING')
            return self._err(request, is_ajax,
                             f"Juda ko‘p so‘rov. {reset_in}s kuting.", 429)

        # ─── Asosiy logika ───
        phone_raw = request.POST.get('phone_number', '').strip()
        phone = normalize_phone(phone_raw)

        if not is_valid_phone(phone):
            return self._err(request, is_ajax, "Telefon raqam noto‘g‘ri.", 400)

        # ═══ 4. Phone blok ═══
        blocked, remaining = is_phone_blocked(phone)
        if blocked:
            minutes = remaining // 60
            log_security_event('PHONE_BLOCKED_TG', ip=ip, phone=phone,
                               details=f"{minutes} daq", severity='WARNING')
            return self._err(request, is_ajax,
                             f"Bu raqam {minutes} daqiqaga bloklangan.", 429)

        try:
            user = User.objects.get(phone_number=phone)
        except User.DoesNotExist:
            return self._err(request, is_ajax, "Bu raqam tizimda yo‘q.", 404)

        if not user.is_active:
            return self._err(request, is_ajax, "Hisobingiz bloklangan.", 403)

        try:
            link = TelegramLink.objects.get(user=user, is_active=True)
        except TelegramLink.DoesNotExist:
            bot_username = getattr(settings, 'TELEGRAM_BOT_USERNAME', 'digion_bot')
            return self._err(
                request, is_ajax,
                f"Telegram hisobi bog‘lanmagan. @{bot_username} botga /start bosing.",
                400,
                extra={'action': 'open_bot', 'bot': bot_username}
            )

        # ─── Cooldown ───
        cooldown = getattr(settings, 'TELEGRAM_RESEND_COOLDOWN', 30)
        rate_key = f"{TG_RESEND_PREFIX}{phone}"
        last_sent = cache.get(rate_key)
        if last_sent:
            elapsed = (timezone.now() - last_sent).total_seconds()
            if elapsed < cooldown:
                remaining = int(cooldown - elapsed)
                return self._err(request, is_ajax,
                                 f"{remaining} sekunddan so‘ng qayta so‘rang.", 429)

        # ─── Kod generatsiya ───
        code = generate_otp()
        ttl = getattr(settings, 'TELEGRAM_CODE_TTL', 60)
        expires_at = timezone.now() + timedelta(seconds=ttl)

        cache.set(f"{TG_CODE_PREFIX}{phone}", {
            'code': code,
            'user_id': user.id,
            'chat_id': link.chat_id,
            'created_at': timezone.now().isoformat(),
            'expires_at': expires_at.isoformat(),
        }, timeout=ttl)

        cache.delete(f"{TG_ATTEMPT_PREFIX}{phone}")

        # ─── Telegramga yuborish ───
        sent = send_login_code(
            link.chat_id, code,
            full_name=user.get_full_name() or user.phone_number
        )

        if not sent:
            cache.delete(f"{TG_CODE_PREFIX}{phone}")
            return self._err(request, is_ajax, "Telegramga yuborishda xatolik.", 500)

        cache.set(rate_key, timezone.now(), timeout=cooldown)
        request.session['tg_phone'] = phone

        log_security_event('TG_CODE_SENT', ip=ip, phone=phone, severity='INFO')

        if is_ajax:
            return JsonResponse({
                'ok': True,
                'message': f"Telegramga kod yuborildi. {ttl} sekund amal qiladi.",
                'masked_phone': mask_phone(phone),
                'expires_in': ttl,
                'cooldown': cooldown,
            })

        messages.success(request, "Telegramga kod yuborildi.")
        return redirect('login_page_view')

    @staticmethod
    def _err(request, is_ajax, msg, status=400, extra=None):
        if is_ajax:
            data = {'ok': False, 'error': msg}
            if extra:
                data.update(extra)
            return JsonResponse(data, status=status)
        messages.error(request, msg)
        return redirect('login_page_view')


class TelegramVerifyCodeView(View):
    """Telegramdan kelgan kodni tekshirish."""

    def post(self, request, *args, **kwargs):
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        ip = get_client_ip(request)

        # ═══ XAVFSIZLIK: IP blok ═══
        blocked, remaining = is_ip_blocked(ip)
        if blocked:
            return self._err(request, is_ajax,
                             f"IP bloklangan. {remaining}s kuting.", 429)

        # ═══ XAVFSIZLIK: IP rate limit ═══
        allowed, rem, reset_in = check_ip_rate_limit(ip, 'login')
        if not allowed:
            record_suspicious_activity(ip, 'tg verify rate limit')
            return self._err(request, is_ajax,
                             f"Juda ko‘p urinish. {reset_in}s kuting.", 429)

        code = (
            request.POST.get('telegram_code')
            or request.POST.get('otp_code')
            or request.POST.get('code')
            or ''
        ).strip()

        phone = (
            request.POST.get('phone_number')
            or request.session.get('tg_phone')
            or ''
        )
        phone = normalize_phone(phone)

        next_url = request.POST.get('next') or request.GET.get('next') or ''

        if not phone or not is_valid_phone(phone):
            return self._err(request, is_ajax, "Telefon raqam topilmadi.", 400)

        if not code or len(code) != 6 or not code.isdigit():
            return self._err(request, is_ajax, "Kod 6 xonali bo‘lishi kerak.", 400)

        # ═══ Phone blok tekshirish ═══
        blocked, remaining = is_phone_blocked(phone)
        if blocked:
            minutes = remaining // 60
            return self._err(request, is_ajax,
                             f"Bu raqam {minutes} daqiqaga bloklangan.", 429)

        max_attempts = getattr(settings, 'TELEGRAM_MAX_ATTEMPTS', 3)
        attempt_key = f"{TG_ATTEMPT_PREFIX}{phone}"
        attempts = cache.get(attempt_key, 0)

        if attempts >= max_attempts:
            cache.delete(f"{TG_CODE_PREFIX}{phone}")
            block_phone(phone, minutes=15, reason="Telegram OTP urinishlar tugadi")
            block_ip(ip, minutes=30, reason="Telegram brute-force")
            log_security_event('TG_PHONE_IP_BLOCKED', ip=ip, phone=phone,
                               details="3 noto‘g‘ri", severity='CRITICAL')
            return self._err(request, is_ajax,
                             "Juda ko‘p urinish. 15 daqiqaga bloklandingiz.", 429)

        cached = cache.get(f"{TG_CODE_PREFIX}{phone}")
        if not cached:
            return self._err(request, is_ajax, "Kod muddati tugagan (1 daqiqa).", 410)

        # Expire tekshirish
        try:
            expires_at = timezone.datetime.fromisoformat(cached['expires_at'])
            if timezone.now() > expires_at:
                cache.delete(f"{TG_CODE_PREFIX}{phone}")
                return self._err(request, is_ajax, "Kod muddati tugagan.", 410)
        except Exception:
            pass

        # ═══ Kod solishtirish ═══
        if cached['code'] != code:
            cache.set(attempt_key, attempts + 1, timeout=300)
            remaining = max_attempts - attempts - 1
            log_security_event('TG_WRONG_CODE', ip=ip, phone=phone,
                               details=f"{attempts+1}/{max_attempts}",
                               severity='WARNING')
            return self._err(request, is_ajax,
                             f"Kod noto‘g‘ri. {remaining} ta urinish qoldi.", 400)

        # ═══ Muvaffaqiyat ═══
        try:
            user = User.objects.get(id=cached['user_id'])
        except User.DoesNotExist:
            return self._err(request, is_ajax, "Foydalanuvchi topilmadi.", 404)

        if not user.is_active:
            return self._err(request, is_ajax, "Hisobingiz bloklangan.", 403)

        cache.delete(f"{TG_CODE_PREFIX}{phone}")
        cache.delete(attempt_key)
        cache.delete(f"{TG_RESEND_PREFIX}{phone}")
        request.session.pop('tg_phone', None)

        login(request, user)
        request.session.set_expiry(timedelta(days=REMEMBER_ME_DAYS))

        try:
            from apps.user.models import TelegramLink
            TelegramLink.objects.filter(user=user).update(last_login=timezone.now())
        except Exception:
            pass

        log_activity(user, request, 'login')

        try:
            from apps.service.notification_service import notify_admin_about_login
            notify_admin_about_login(user, 'telegram', request)
        except Exception as e:
            logger.warning(f"Admin xabar: {e}")

        log_security_event('TG_LOGIN_OK', ip=ip, phone=phone, severity='INFO')

        redirect_url = next_url or get_success_url_for(user)

        if is_ajax:
            return JsonResponse({
                'ok': True,
                'message': "Muvaffaqiyatli kirdingiz!",
                'redirect': redirect_url,
            })

        messages.success(request, f"Xush kelibsiz, {user.get_full_name() or user.phone_number}!")
        return redirect(redirect_url)

    @staticmethod
    def _err(request, is_ajax, msg, status=400):
        if is_ajax:
            return JsonResponse({'ok': False, 'error': msg}, status=status)
        messages.error(request, msg)
        return redirect('login_page_view')


# ═══════════════════════════════════════════════════════════════
# 4. LOGOUT
# ═══════════════════════════════════════════════════════════════

class LogoutView(View):
    def get(self, request, *args, **kwargs):
        return self._logout(request)

    def post(self, request, *args, **kwargs):
        return self._logout(request)

    def _logout(self, request):
        user = request.user
        if user.is_authenticated:
            log_activity(user, request, 'logout')
            logout(request)
        messages.info(request, "Siz tizimdan chiqdingiz.")
        return redirect('login_page_view')


def logout_view(request):
    return LogoutView()._logout(request)