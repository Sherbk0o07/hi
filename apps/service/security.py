"""
Xavfsizlik servisi — Rate limiting, IP blocking, DDoS himoyasi.
"""
import logging
import hashlib
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# IP MANZIL
# ═══════════════════════════════════════════════════════════════

def get_client_ip(request) -> str:
    """Foydalanuvchi IP manzilini olish (Cloudflare, proxy)."""
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


def hash_ip(ip: str) -> str:
    """IP ni hash qilish (cache key uchun xavfsiz)."""
    return hashlib.sha256(f"ip_{ip}".encode()).hexdigest()[:16]


def hash_phone(phone: str) -> str:
    """Phone ni hash qilish."""
    return hashlib.sha256(f"ph_{phone}".encode()).hexdigest()[:16]


# ═══════════════════════════════════════════════════════════════
# RATE LIMITING (so‘rovlar soni cheklash)
# ═══════════════════════════════════════════════════════════════

def check_rate_limit(key: str, max_requests: int, window_seconds: int) -> tuple:
    """
    Rate limit tekshirish.

    Returns: (is_allowed: bool, remaining: int, reset_in: int)
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

    return check_rate_limit(f"ip_{hash_ip(ip)}_{action}", max_req, window)


# ═══════════════════════════════════════════════════════════════
# BLOKLASH (vaqtinchalik taqiqlash)
# ═══════════════════════════════════════════════════════════════

def block_ip(ip: str, minutes: int = None, reason: str = ''):
    """IP manzilni vaqtinchalik bloklash."""
    minutes = minutes or getattr(settings, 'IP_BLOCK_MINUTES', 30)
    key = f"block_ip_{hash_ip(ip)}"
    cache.set(key, {
        'reason': reason,
        'blocked_at': timezone.now().isoformat(),
    }, timeout=minutes * 60)
    logger.warning(f"[SECURITY] IP bloklandi: {ip} | Sabab: {reason} | {minutes} daqiqa")


def is_ip_blocked(ip: str) -> tuple:
    """IP bloklanganmi?"""
    key = f"block_ip_{hash_ip(ip)}"
    data = cache.get(key)
    if data:
        try:
            blocked_at = timezone.datetime.fromisoformat(data['blocked_at'])
            elapsed = (timezone.now() - blocked_at).total_seconds()
            block_seconds = getattr(settings, 'IP_BLOCK_MINUTES', 30) * 60
            remaining = int(block_seconds - elapsed)
            return True, max(0, remaining)
        except Exception:
            return True, 1800
    return False, 0


def block_phone(phone: str, minutes: int = None, reason: str = ''):
    """Telefon raqamni vaqtinchalik bloklash."""
    minutes = minutes or getattr(settings, 'TELEGRAM_PHONE_BLOCK_MINUTES', 15)
    key = f"block_phone_{hash_phone(phone)}"
    cache.set(key, {
        'reason': reason,
        'blocked_at': timezone.now().isoformat(),
    }, timeout=minutes * 60)
    logger.warning(f"[SECURITY] Phone bloklandi: {phone} | Sabab: {reason}")


def is_phone_blocked(phone: str) -> tuple:
    """Telefon bloklanganmi?"""
    key = f"block_phone_{hash_phone(phone)}"
    data = cache.get(key)
    if data:
        try:
            blocked_at = timezone.datetime.fromisoformat(data['blocked_at'])
            elapsed = (timezone.now() - blocked_at).total_seconds()
            block_seconds = getattr(settings, 'TELEGRAM_PHONE_BLOCK_MINUTES', 15) * 60
            remaining = int(block_seconds - elapsed)
            return True, max(0, remaining)
        except Exception:
            return True, 900
    return False, 0


# ═══════════════════════════════════════════════════════════════
# GLOBAL HIMOYA (DDoS)
# ═══════════════════════════════════════════════════════════════

def check_global_limit(action: str = 'telegram') -> tuple:
    """Global limit — butun tizim uchun."""
    limits = {
        'telegram': getattr(settings, 'GLOBAL_MAX_TELEGRAM_PER_MINUTE', 100),
    }
    max_req = limits.get(action, 100)
    return check_rate_limit(f"global_{action}", max_req, 60)


def record_suspicious_activity(ip: str, reason: str = ''):
    """Shubhali faollikni qayd etish."""
    key = f"suspicious_{hash_ip(ip)}"
    count = cache.get(key, 0) + 1
    cache.set(key, count, timeout=3600)  # 1 soat

    threshold = getattr(settings, 'GLOBAL_SUSPICIOUS_THRESHOLD', 50)

    if count >= threshold:
        # Avtomatik blok
        block_ip(ip, minutes=60, reason=f"Ko‘p shubhali faollik: {reason}")
        logger.critical(f"[SECURITY] AVTOMATIK BLOK: {ip} | {count} ta shubhali")
        return True
    return False


def log_security_event(event_type: str, ip: str = '', phone: str = '',
                        details: str = '', severity: str = 'INFO'):
    """Xavfsizlik hodisasini log qilish."""
    prefix = {
        'INFO': 'ℹ️',
        'WARNING': '⚠️',
        'ERROR': '❌',
        'CRITICAL': '🚨',
    }.get(severity, 'ℹ️')

    msg = f"{prefix} [{event_type}]"
    if ip:
        msg += f" IP={ip}"
    if phone:
        msg += f" PHONE={phone}"
    if details:
        msg += f" | {details}"

    logger.warning(msg) if severity in ('WARNING', 'ERROR', 'CRITICAL') else logger.info(msg)


# ═══════════════════════════════════════════════════════════════
# BOT TOKEN HIMOYASI
# ═══════════════════════════════════════════════════════════════

def check_bot_spam(chat_id: int) -> bool:
    """Botga spam bo‘lyaptimi?"""
    key = f"bot_spam_{chat_id}"
    count = cache.get(key, 0) + 1
    cache.set(key, count, timeout=60)

    if count > 20:  # 1 daqiqada 20+ xabar
        logger.critical(f"[SECURITY] Bot spam: chat_id={chat_id}, count={count}")
        return False
    return True