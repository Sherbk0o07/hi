"""
Notification Service — avtomatik xabarlar yuborish logikasi.
========================================================================
XUSUSIYATLAR:
- Faol bo‘lmagan foydalanuvchilarga xabar
- Admin nusxasi (kimga, nima, qachon)
- Telegram Web App tugmasi (saytni ilova sifatida ochish)
"""
import logging
import random
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.user.models import (
    CustomUser, TelegramLink,
    TelegramNotificationTemplate, StudyQuestion,
    TelegramNotificationLog,
)
from apps.service.telegram_bot import (
    send_admin_login_alert, send_admin_telegram_login_alert,
    send_motivational_message, send_study_question,
    send_html_message,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# YANGI: TELEGRAM WEB APP TUGMASI
# ═══════════════════════════════════════════════════════════════

def get_web_app_url(path: str = '/testlar/') -> str:
    """
    Telegram Web App URL ini qaytarish.
    Sayt HTTPS bo‘lishi shart!
    """
    base_url = getattr(settings, 'SITE_URL', 'https://digion.uz')
    # Bo‘sh joylarni olib tashlash
    base_url = base_url.rstrip('/')
    path = path if path.startswith('/') else f'/{path}'
    return f"{base_url}{path}"


def get_web_app_button(text: str = "🚀 Kirish", path: str = '/testlar/'):
    """
    Telegram Web App tugmasini yaratish.
    Bosilganda sayt ilova sifatida ochiladi.
    """
    return {
        'text': text,
        'web_app': get_web_app_url(path),
    }


# ═══════════════════════════════════════════════════════════════
# ADMINGA NUSXA YUBORISH
# ═══════════════════════════════════════════════════════════════

def notify_admin_about_message(
    recipient_user,
    trigger_name: str,
    message_text: str,
    status: str = 'sent',
) -> bool:
    """
    Adminga xabar nusxasini yuborish.
    Kimga yuborildi, nima yuborildi, qachon.
    """
    admin_chat_id = getattr(settings, 'ADMIN_TELEGRAM_CHAT_ID', None)
    if not admin_chat_id:
        return False

    # Trigger nomlari va ranglari
    trigger_info = {
        'welcome_back': {'emoji': '🎉', 'name': 'Qaytib kelish'},
        'inactive_4h': {'emoji': '☕', 'name': '4 soat kirmadi'},
        'inactive_7h': {'emoji': '🥺', 'name': '7 soat kirmadi'},
        'inactive_1d': {'emoji': '⏰', 'name': '1 kun kirmadi'},
        'inactive_3d': {'emoji': '💔', 'name': '3 kun kirmadi'},
        'late_night': {'emoji': '🌙', 'name': 'Tungi xabar'},
        'morning_boost': {'emoji': '🌅', 'name': 'Ertalabki xabar'},
        'achievement': {'emoji': '🏆', 'name': 'Yutuq'},
        'admin_custom_sms': {'emoji': '💬', 'name': 'Admin xabari'},
        'login_telegram': {'emoji': '✈️', 'name': 'Telegram login'},
    }

    info = trigger_info.get(
        trigger_name,
        {'emoji': '📩', 'name': trigger_name}
    )

    status_icon = {
        'sent': '✅ Yuborildi',
        'failed': '❌ Xato',
        'pending': '⏳ Kutilmoqda',
        'delivered': '📬 Yetkazildi',
    }.get(status, status)

    now = timezone.localtime().strftime('%d.%m.%Y %H:%M:%S')

    # Xabar matnini qisqartirish
    msg_preview = message_text[:500]
    if len(message_text) > 500:
        msg_preview += '…'

    text = (
        f"📤 <b>XABAR YUBORILDI</b>\n"
        f"{'━' * 28}\n\n"
        f"👤 <b>Kimga:</b> {recipient_user.get_full_name() or recipient_user.phone_number}\n"
        f"📱 <b>Telefon:</b> <code>{recipient_user.phone_number}</code>\n"
        f"{info['emoji']} <b>Turi:</b> {info['name']}\n"
        f"📊 <b>Holat:</b> {status_icon}\n"
        f"🕐 <b>Vaqt:</b> <code>{now}</code>\n\n"
        f"{'━' * 28}\n"
        f"💬 <b>Xabar matni:</b>\n\n"
        f"<blockquote>{msg_preview}</blockquote>"
    )

    buttons = [
        {'text': '👥 Foydalanuvchini ko‘rish',
         'url': get_web_app_url('/admin/oquvchilar/')},
        {'text': '📊 Barcha xabarlar',
         'url': get_web_app_url('/admin/telegram-xabarlar/')},
    ]

    return send_html_message(admin_chat_id, text, buttons=buttons)


# ═══════════════════════════════════════════════════════════════
# ADMIN LOGIN XABARLARI
# ═══════════════════════════════════════════════════════════════

def notify_admin_about_login(user, method: str, request=None) -> bool:
    """Adminga login haqida xabar yuborish."""
    admin_chat_id = getattr(settings, 'ADMIN_TELEGRAM_CHAT_ID', None)
    if not admin_chat_id:
        logger.warning("ADMIN_TELEGRAM_CHAT_ID sozlanmagan!")
        return False

    ip = ''
    ua = ''
    if request:
        xff = request.META.get('HTTP_X_FORWARDED_FOR')
        ip = xff.split(',')[0].strip() if xff else request.META.get('REMOTE_ADDR', '')
        ua = request.META.get('HTTP_USER_AGENT', '')

    full_name = user.get_full_name() or user.phone_number

    if method == 'telegram':
        try:
            link = TelegramLink.objects.get(user=user, is_active=True)
            success = send_admin_telegram_login_alert(
                admin_chat_id, full_name, user.phone_number,
                telegram_username=link.username or '',
            )
        except TelegramLink.DoesNotExist:
            success = send_admin_login_alert(
                admin_chat_id, full_name, user.phone_number,
                'telegram', ip, ua,
            )
    else:
        success = send_admin_login_alert(
            admin_chat_id, full_name, user.phone_number,
            method, ip, ua,
        )

    TelegramNotificationLog.objects.create(
        recipient=user,
        trigger='admin_telegram_login' if method == 'telegram' else 'admin_login_alert',
        message=f"Login ({method}) - {full_name}",
        chat_id=admin_chat_id,
        status='sent' if success else 'failed',
    )

    return success


# ═══════════════════════════════════════════════════════════════
# FAOL BO‘LMAGAN FOYDALANUVCHILAR
# ═══════════════════════════════════════════════════════════════

def get_inactive_users(hours: int = 4):
    """N soatdan ortiq kirmagan foydalanuvchilar."""
    threshold = timezone.now() - timedelta(hours=hours)
    return CustomUser.objects.filter(
        is_active=True,
        role='student',
        telegram_link__is_active=True,
    ).filter(
        activity_logs__login_time__lt=threshold,
    ).exclude(
        activity_logs__login_time__gte=threshold,
    ).distinct()


def send_to_inactive_users(trigger: str, hours: int) -> dict:
    """
    N soatdan ortiq kirmagan foydalanuvchilarga xabar yuborish.
    Admin ham nusxa oladi.
    """
    try:
        template = TelegramNotificationTemplate.objects.get(
            trigger=trigger, is_active=True
        )
    except TelegramNotificationTemplate.DoesNotExist:
        logger.warning(f"Shablon topilmadi: {trigger}")
        return {'sent': 0, 'failed': 0, 'skipped': 0, 'error': 'no_template'}

    users = get_inactive_users(hours)
    sent, failed, skipped = 0, 0, 0

    for user in users:
        try:
            link = TelegramLink.objects.get(user=user, is_active=True)
        except TelegramLink.DoesNotExist:
            skipped += 1
            continue

        # Yaqinda shu trigger bilan xabar yuborilganmi?
        recent = TelegramNotificationLog.objects.filter(
            recipient=user,
            trigger=trigger,
            sent_at__gte=timezone.now() - timedelta(hours=hours),
        ).exists()

        if recent:
            skipped += 1
            continue

        full_name = user.get_full_name() or user.phone_number
        extra = {
            'hours': hours,
            'last_seen': get_last_seen(user),
        }

        # ⚡ Telegram Web App tugmasi
        web_app_btn = get_web_app_button(
            text="🚀 O‘qishni davom ettirish",
            path='/testlar/'
        )

        success = send_motivational_message(
            link.chat_id, full_name, template, extra,
            extra_buttons=[web_app_btn]
        )

        TelegramNotificationLog.objects.create(
            recipient=user,
            trigger=trigger,
            message=template.message,
            chat_id=link.chat_id,
            status='sent' if success else 'failed',
        )

        # ⚡⚡ ADMINGA NUSXA
        try:
            notify_admin_about_message(
                user, trigger, template.message,
                status='sent' if success else 'failed',
            )
        except Exception as e:
            logger.warning(f"Admin nusxa xatosi: {e}")

        if success:
            sent += 1
        else:
            failed += 1

    return {'sent': sent, 'failed': failed, 'skipped': skipped}


def send_welcome_back(user, request=None) -> bool:
    """Foydalanuvchi uzoq tanaffusdan keyin qaytganida xabar."""
    try:
        template = TelegramNotificationTemplate.objects.get(
            trigger='welcome_back', is_active=True
        )
    except TelegramNotificationTemplate.DoesNotExist:
        return False

    try:
        link = TelegramLink.objects.get(user=user, is_active=True)
    except TelegramLink.DoesNotExist:
        return False

    # Oxirgi kirishdan 6 soatdan ko‘p o‘tganmi?
    last_log = user.activity_logs.order_by('-login_time').first()
    if last_log and last_log.login_time:
        elapsed = timezone.now() - last_log.login_time
        if elapsed.total_seconds() < 6 * 3600:
            return False

    full_name = user.get_full_name() or user.phone_number

    # ⚡ Web App tugma
    web_app_btn = get_web_app_button(
        text="📚 Hoziroq boshlash",
        path='/testlar/'
    )

    success = send_motivational_message(
        link.chat_id, full_name, template,
        extra_buttons=[web_app_btn]
    )

    TelegramNotificationLog.objects.create(
        recipient=user,
        trigger='welcome_back',
        message=template.message,
        chat_id=link.chat_id,
        status='sent' if success else 'failed',
    )

    # ⚡ Admin nusxa
    try:
        notify_admin_about_message(
            user, 'welcome_back', template.message,
            status='sent' if success else 'failed',
        )
    except Exception as e:
        logger.warning(f"Admin nusxa xatosi: {e}")

    return success


def send_random_study_question(user) -> bool:
    """Foydalanuvchiga random savol yuborish."""
    try:
        link = TelegramLink.objects.get(user=user, is_active=True)
    except TelegramLink.DoesNotExist:
        return False

    questions = list(StudyQuestion.objects.filter(
        is_active=True
    ).order_by('used_count', '?')[:5])

    if not questions:
        return False

    question = random.choice(questions)
    full_name = user.get_full_name() or user.phone_number

    web_app_btn = get_web_app_button(
        text="✍️ Javob berish", path='/testlar/'
    )

    success = send_study_question(
        link.chat_id, question, full_name,
        extra_buttons=[web_app_btn]
    )

    if success:
        TelegramNotificationLog.objects.create(
            recipient=user,
            trigger='custom',
            message=f"Savol: {question.question[:100]}",
            chat_id=link.chat_id,
            status='sent',
        )

        # ⚡ Admin nusxa
        try:
            notify_admin_about_message(
                user, 'custom',
                f"Savol: {question.question[:200]}",
                status='sent',
            )
        except Exception as e:
            logger.warning(f"Admin nusxa xatosi: {e}")

    return success


def send_late_night_message(user) -> bool:
    """Kechqurun (22:00+) xabar."""
    try:
        template = TelegramNotificationTemplate.objects.get(
            trigger='late_night', is_active=True
        )
        link = TelegramLink.objects.get(user=user, is_active=True)
    except (TelegramNotificationTemplate.DoesNotExist,
            TelegramLink.DoesNotExist):
        return False

    full_name = user.get_full_name() or user.phone_number

    web_app_btn = get_web_app_button(
        text="🌙 Tungi darsni boshlash",
        path='/testlar/'
    )

    success = send_motivational_message(
        link.chat_id, full_name, template,
        extra_buttons=[web_app_btn]
    )

    TelegramNotificationLog.objects.create(
        recipient=user,
        trigger='late_night',
        message=template.message,
        chat_id=link.chat_id,
        status='sent' if success else 'failed',
    )

    # ⚡ Admin nusxa
    try:
        notify_admin_about_message(
            user, 'late_night', template.message,
            status='sent' if success else 'failed',
        )
    except Exception as e:
        logger.warning(f"Admin nusxa xatosi: {e}")

    return success


def send_morning_boost() -> dict:
    """Ertalab barcha aktiv foydalanuvchilarga xabar."""
    try:
        template = TelegramNotificationTemplate.objects.get(
            trigger='morning_boost', is_active=True
        )
    except TelegramNotificationTemplate.DoesNotExist:
        return {'sent': 0, 'failed': 0}

    links = TelegramLink.objects.filter(
        is_active=True,
        user__is_active=True,
        user__role='student',
    ).select_related('user')

    sent, failed = 0, 0
    total = links.count()

    # ⚡ Admin — boshlanish xabari
    admin_chat_id = getattr(settings, 'ADMIN_TELEGRAM_CHAT_ID', None)
    if admin_chat_id and total > 0:
        send_html_message(
            admin_chat_id,
            f"🌅 <b>Morning Boost boshlandi</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 Jami: <b>{total}</b> o‘quvchi\n"
            f"🕐 Vaqt: <code>{timezone.localtime().strftime('%H:%M')}</code>"
        )

    # ⚡ Web App tugmasi
    web_app_btn = get_web_app_button(
        text="☀️ Bugungi darsni boshlash",
        path='/testlar/'
    )

    for link in links:
        full_name = link.user.get_full_name() or link.user.phone_number
        success = send_motivational_message(
            link.chat_id, full_name, template,
            extra_buttons=[web_app_btn]
        )

        TelegramNotificationLog.objects.create(
            recipient=link.user,
            trigger='morning_boost',
            message=template.message,
            chat_id=link.chat_id,
            status='sent' if success else 'failed',
        )

        # ⚡ Admin nusxa
        try:
            notify_admin_about_message(
                link.user, 'morning_boost', template.message,
                status='sent' if success else 'failed',
            )
        except Exception as e:
            logger.warning(f"Admin nusxa xatosi: {e}")

        if success:
            sent += 1
        else:
            failed += 1

    # ⚡ Admin — yakuniy xabar
    if admin_chat_id and total > 0:
        send_html_message(
            admin_chat_id,
            f"✅ <b>Morning Boost yakunlandi</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"✅ Yuborildi: <b>{sent}</b>\n"
            f"❌ Xato: <b>{failed}</b>\n"
            f"📊 Jami: <b>{total}</b>"
        )

    return {'sent': sent, 'failed': failed}


# ═══════════════════════════════════════════════════════════════
# ADMIN QO‘LDA XABAR
# ═══════════════════════════════════════════════════════════════

def send_manual_sms(user, message_text: str, admin_user) -> bool:
    """Admin qo‘lda yozgan xabarni Telegramga yuborish."""
    try:
        link = TelegramLink.objects.get(user=user, is_active=True)
    except TelegramLink.DoesNotExist:
        return False

    admin_name = admin_user.get_full_name() or admin_user.phone_number

    from apps.service.telegram_bot import send_admin_reply

    # ⚡ Web App tugmasi
    web_app_btn = get_web_app_button(
        text="🚀 Saytga kirish",
        path='/testlar/'
    )

    success = send_admin_reply(
        link.chat_id, admin_name, message_text,
        extra_buttons=[web_app_btn]
    )

    TelegramNotificationLog.objects.create(
        recipient=user,
        trigger='admin_custom_sms',
        message=message_text,
        chat_id=link.chat_id,
        status='sent' if success else 'failed',
        sent_by=admin_user,
    )

    # ⚡ Admin tasdiq
    admin_chat_id = getattr(settings, 'ADMIN_TELEGRAM_CHAT_ID', None)
    if admin_chat_id:
        now = timezone.localtime().strftime('%d.%m.%Y %H:%M')
        send_html_message(
            admin_chat_id,
            f"✅ <b>Xabar yuborildi</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Kimga: <b>{user.get_full_name() or user.phone_number}</b>\n"
            f"📱 {user.phone_number}\n"
            f"🕐 {now}\n\n"
            f"💬 <blockquote>{message_text[:300]}</blockquote>",
        )

    return success


# ═══════════════════════════════════════════════════════════════
# YORDAMCHI
# ═══════════════════════════════════════════════════════════════

def get_last_seen(user) -> str:
    """Foydalanuvchi oxirgi marta qachon kirgan."""
    log = user.activity_logs.order_by('-login_time').first()
    if log and log.login_time:
        delta = timezone.now() - log.login_time
        hours = int(delta.total_seconds() // 3600)
        if hours < 1:
            minutes = int(delta.total_seconds() // 60)
            return f"{minutes} daqiqa oldin"
        if hours < 24:
            return f"{hours} soat oldin"
        days = hours // 24
        return f"{days} kun oldin"
    return "hech qachon"



# ═══════════════════════════════════════════════════════════════
# HOMEWORK VA SUBMISSION BILDIRISHNOMALARI
# ═══════════════════════════════════════════════════════════════

import logging
from django.utils import timezone

logger = logging.getLogger(__name__)


def send_homework_to_group(homework, group, user=None):
    """
    Uyga vazifani guruh talabalariga yuborish.
    
    Returns:
        dict: {
            'success': bool,
            'sent_count': int,
            'failed_count': int,
            'errors': list,
        }
    """
    from apps.user.models import CustomUser, TelegramLink
    from apps.user.models import TelegramNotificationLog

    result = {
        'success': True,
        'sent_count': 0,
        'failed_count': 0,
        'errors': [],
    }

    # Guruh talabalari (Telegram bog‘langan)
    try:
        students = group.students.select_related('user').all()
    except Exception as e:
        logger.exception(f"Guruh talabalarini olishda xato: {e}")
        result['success'] = False
        result['errors'].append(str(e))
        return result

    # Xabar matni
    message = (
        f"📚 <b>Yangi uyga vazifa!</b>\n\n"
        f"<b>Kurs:</b> {homework.lesson.course.title}\n"
        f"<b>Dars:</b> {homework.lesson.title}\n"
        f"<b>Vazifa:</b> {homework.title}\n"
        f"<b>Muddat:</b> {homework.deadline_days} kun\n"
        f"<b>Maksimal ball:</b> {homework.max_score}\n"
    )
    if homework.short_description:
        message += f"\n{homework.short_description}\n"

    # Har bir talabaga yuborish
    for student in students:
        user_obj = student.user

        # Telegram bog‘langanini tekshirish
        try:
            link = TelegramLink.objects.filter(user=user_obj, is_active=True).first()
        except Exception:
            link = None

        if not link:
            result['failed_count'] += 1
            continue

        # Telegramga yuborishga urinish
        try:
            success = _send_telegram_message(link.chat_id, message)

            TelegramNotificationLog.objects.create(
                recipient=user_obj,
                trigger='custom',
                message=message,
                chat_id=link.chat_id,
                status='sent' if success else 'failed',
                sent_by=user,
                error_message='' if success else 'Telegram API xatosi',
            )

            if success:
                result['sent_count'] += 1
            else:
                result['failed_count'] += 1

        except Exception as e:
            logger.exception(f"Telegram yuborishda xato ({user_obj}): {e}")
            result['failed_count'] += 1
            result['errors'].append(str(e))

    # Homework statusini yangilash
    try:
        homework.is_sent = True
        homework.sent_at = timezone.now()
        homework.save(update_fields=['is_sent', 'sent_at'])
    except Exception:
        pass

    return result


def notify_admin_about_submission(submission):
    """
    Adminlarga yangi topshiriq haqida xabar yuborish.
    """
    from apps.user.models import CustomUser, TelegramLink
    from apps.user.models import TelegramNotificationLog

    try:
        admins = CustomUser.objects.filter(role='admin', is_active=True)
        if not admins.exists():
            admins = CustomUser.objects.filter(is_superuser=True, is_active=True)

        student_name = submission.student.user.get_full_name()
        homework_title = submission.homework.title

        message = (
            f"📥 <b>Yangi topshiriq!</b>\n\n"
            f"<b>Talaba:</b> {student_name}\n"
            f"<b>Telefon:</b> {submission.student.user.phone_number}\n"
            f"<b>Vazifa:</b> {homework_title}\n"
            f"<b>Topshirilgan:</b> {submission.submitted_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"<b>Kechikkan:</b> {'Ha' if submission.is_late else 'Yo‘q'}\n"
        )

        for admin in admins:
            link = TelegramLink.objects.filter(user=admin, is_active=True).first()
            if not link:
                continue

            try:
                success = _send_telegram_message(link.chat_id, message)
                TelegramNotificationLog.objects.create(
                    recipient=admin,
                    trigger='custom',
                    message=message,
                    chat_id=link.chat_id,
                    status='sent' if success else 'failed',
                    sent_by=None,
                )
            except Exception as e:
                logger.exception(f"Adminga xabar yuborishda xato: {e}")

    except Exception as e:
        logger.exception(f"notify_admin_about_submission xatosi: {e}")


def notify_admin_about_login(user, ip_address=None):
    """
    Adminlarga foydalanuvchi kirishi haqida xabar yuborish.
    """
    from apps.user.models import CustomUser, TelegramLink
    from apps.user.models import TelegramNotificationLog

    try:
        admins = CustomUser.objects.filter(
            role='admin', is_active=True,
        ).exclude(pk=user.pk)

        if not admins.exists():
            return

        message = (
            f"🔔 <b>Tizimga kirish</b>\n\n"
            f"<b>Foydalanuvchi:</b> {user.get_full_name() or user.phone_number}\n"
            f"<b>Telefon:</b> {user.phone_number}\n"
            f"<b>Rol:</b> {user.get_role_display()}\n"
            f"<b>IP:</b> {ip_address or '—'}\n"
            f"<b>Vaqt:</b> {timezone.now().strftime('%d.%m.%Y %H:%M')}\n"
        )

        for admin in admins:
            link = TelegramLink.objects.filter(user=admin, is_active=True).first()
            if not link:
                continue

            try:
                success = _send_telegram_message(link.chat_id, message)
                TelegramNotificationLog.objects.create(
                    recipient=admin,
                    trigger='admin_login_alert',
                    message=message,
                    chat_id=link.chat_id,
                    status='sent' if success else 'failed',
                    sent_by=None,
                )
            except Exception as e:
                logger.exception(f"Login xabarida xato: {e}")

    except Exception as e:
        logger.exception(f"notify_admin_about_login xatosi: {e}")


# ═══════════════════════════════════════════════════════════════
# ICHKI YORDAMCHI — Telegramga yuborish
# ═══════════════════════════════════════════════════════════════

def _send_telegram_message(chat_id, text, parse_mode='HTML'):
    """
    Telegram bot orqali xabar yuborish.
    
    Bot tokenini settings.py dan oladi:
        TELEGRAM_BOT_TOKEN = '123456:ABC...'
    """
    try:
        from django.conf import settings
        import requests

        bot_token = getattr(settings, 'TELEGRAM_BOT_TOKEN', None)

        if not bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN sozlanmagan")
            return False

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': parse_mode,
            'disable_web_page_preview': True,
        }

        response = requests.post(url, data=payload, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return data.get('ok', False)

        logger.warning(f"Telegram API {response.status_code}: {response.text[:200]}")
        return False

    except ImportError:
        logger.warning("'requests' kutubxonasi o‘rnatilmagan: pip install requests")
        return False
    except Exception as e:
        logger.exception(f"Telegram xabar yuborishda xato: {e}")
        return False