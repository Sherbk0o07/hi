"""
Telegram Bot servisi — xabar yuborish, rich format, tugmalar, Web App.
========================================================================
YANGI:
- Web App tugmalari (sayt ilova sifatida ochiladi)
- send_motivational_message() da extra_buttons
- send_study_question() da extra_buttons
- send_admin_reply() da extra_buttons
"""
import logging
import random
from typing import Optional, List, Dict

import telebot
from telebot import types
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

_bot = None


# ═══════════════════════════════════════════════════════════════
# BOT INSTANSIYASI
# ═══════════════════════════════════════════════════════════════

def get_bot() -> telebot.TeleBot:
    global _bot
    if _bot is None:
        token = getattr(settings, 'TELEGRAM_BOT_TOKEN', None)
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN sozlanmagan!")
        _bot = telebot.TeleBot(token, parse_mode='HTML')
    return _bot


# ═══════════════════════════════════════════════════════════════
# ASOSIY XABAR YUBORISH — WEB APP TUGMALARI BILAN
# ═══════════════════════════════════════════════════════════════

def send_html_message(
    chat_id: int,
    text: str,
    buttons: Optional[List[Dict]] = None,
    disable_preview: bool = True,
) -> bool:
    """
    HTML formatlangan xabar yuborish.

    Tugma turlari:
    - {'text': 'Nomi', 'url': 'https://...'}       → oddiy URL
    - {'text': 'Nomi', 'web_app': 'https://...'}   → Web App (sayt)
    - {'text': 'Nomi', 'callback': 'data'}         → Callback
    """
    try:
        bot = get_bot()
        markup = None

        if buttons:
            markup = types.InlineKeyboardMarkup(row_width=1)
            for b in buttons:
                # ⚡ 1. WEB APP TUGMASI (sayt ilova sifatida)
                if b.get('web_app'):
                    btn = types.InlineKeyboardButton(
                        text=b['text'],
                        web_app=types.WebAppInfo(url=b['web_app'])
                    )
                # 2. ODDIY URL
                elif b.get('url'):
                    btn = types.InlineKeyboardButton(
                        text=b['text'], url=b['url']
                    )
                # 3. CALLBACK
                else:
                    btn = types.InlineKeyboardButton(
                        text=b['text'],
                        callback_data=b.get('callback', 'noop')
                    )
                markup.add(btn)

        bot.send_message(
            chat_id, text,
            reply_markup=markup,
            disable_web_page_preview=disable_preview,
        )
        return True
    except telebot.apihelper.ApiTelegramException as e:
        logger.error(f"[TG] API xatosi: {e}")
        return False
    except Exception as e:
        logger.exception(f"[TG] Xatosi: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
# WEB APP YORDAMCHI
# ═══════════════════════════════════════════════════════════════

def get_web_app_url(path: str = '/testlar/') -> str:
    """Web App URL ini qaytarish (HTTPS bo‘lishi shart)."""
    base = getattr(settings, 'SITE_URL', 'https://digion.uz').rstrip('/')
    path = path if path.startswith('/') else f'/{path}'
    return f"{base}{path}"


def web_app_button(text: str = "🚀 Kirish", path: str = '/testlar/') -> dict:
    """Web App tugmasi yaratish."""
    return {'text': text, 'web_app': get_web_app_url(path)}


# ═══════════════════════════════════════════════════════════════
# KIRISH KODI
# ═══════════════════════════════════════════════════════════════

def send_login_code(chat_id: int, code: str, full_name: str = '') -> bool:
    """1 daqiqalik kirish kodini yuborish."""
    name = full_name or 'Foydalanuvchi'
    text = (
        f"🔐 <b>DIGION kirish kodi</b>\n\n"
        f"Salom, <b>{name}</b>!\n\n"
        f"Sizning kodingiz:\n\n"
        f"<code>{code}</code>\n\n"
        f"⏱ <b>Diqqat!</b> Kod <b>1 daqiqa</b> amal qiladi.\n"
        f"⚠️ Kodni hech kimga bermang.\n\n"
        f"🛡️ <i>3 marta noto‘g‘ri kiritsangiz, bloklanadi.</i>"
    )
    return send_html_message(chat_id, text)


# ═══════════════════════════════════════════════════════════════
# ADMIN LOGIN XABARLARI
# ═══════════════════════════════════════════════════════════════

def send_admin_login_alert(
    admin_chat_id: int,
    user_full_name: str,
    phone: str,
    login_method: str,
    ip_address: str = '',
    user_agent: str = '',
) -> bool:
    """Adminga login haqida xabar."""
    method_icons = {
        'password': '🔑 Parol',
        'otp': '📱 SMS',
        'telegram': '✈️ Telegram',
    }
    method_text = method_icons.get(login_method, login_method)
    now = timezone.localtime().strftime('%d.%m.%Y %H:%M:%S')

    text = (
        f"🔔 <b>YANGI LOGIN</b>\n"
        f"{'━' * 25}\n\n"
        f"👤 <b>{user_full_name}</b>\n"
        f"📱 <code>{phone}</code>\n"
        f"🔐 Kirish usuli: <b>{method_text}</b>\n"
        f"🕐 Vaqt: <code>{now}</code>\n"
    )

    if ip_address:
        text += f"🌐 IP: <code>{ip_address}</code>\n"
    if user_agent:
        ua_short = user_agent[:60] + '…' if len(user_agent) > 60 else user_agent
        text += f"💻 Qurilma: <code>{ua_short}</code>\n"

    text += f"\n{'━' * 25}\n✅ Tizim ishlayapti"

    buttons = [
        web_app_button('👥 Foydalanuvchini ko‘rish', '/admin/oquvchilar/'),
        web_app_button('📊 Dashboard', '/boshqaruv/'),
    ]

    return send_html_message(admin_chat_id, text, buttons=buttons)


def send_admin_telegram_login_alert(
    admin_chat_id: int,
    user_full_name: str,
    phone: str,
    telegram_username: str = '',
) -> bool:
    """Adminga Telegram orqali kirish haqida xabar."""
    now = timezone.localtime().strftime('%d.%m.%Y %H:%M:%S')

    text = (
        f"✈️ <b>TELEGRAM ORQALI KIRISH</b>\n"
        f"{'━' * 25}\n\n"
        f"👤 <b>{user_full_name}</b>\n"
        f"📱 <code>{phone}</code>\n"
    )

    if telegram_username:
        text += f"💬 @{telegram_username}\n"

    text += (
        f"🕐 Vaqt: <code>{now}</code>\n\n"
        f"<i>Foydalanuvchi Telegram bot orqali tizimga kirdi.</i>"
    )

    buttons = [
        web_app_button('👤 Profilni ko‘rish', '/admin/oquvchilar/'),
    ]

    return send_html_message(admin_chat_id, text, buttons=buttons)


# ═══════════════════════════════════════════════════════════════
# MOTIVATSION XABAR — WEB APP TUGMA BILAN
# ═══════════════════════════════════════════════════════════════

def send_motivational_message(
    chat_id: int,
    user_name: str,
    template,
    extra_context: dict = None,
    extra_buttons: list = None,
) -> bool:
    """
    Motivatsion xabar yuborish.
    extra_buttons — Web App tugmalari (ixtiyoriy).
    """
    if not template or not template.is_active:
        return False

    # O‘zgaruvchilarni almashtirish
    message = template.message
    context = {
        'name': user_name,
        'date': timezone.localtime().strftime('%d.%m.%Y'),
        'time': timezone.localtime().strftime('%H:%M'),
    }
    if extra_context:
        context.update(extra_context)

    for key, value in context.items():
        message = message.replace(f'{{{key}}}', str(value))

    text = f"{template.emoji} <b>{template.title}</b>\n\n{message}"

    # ⚡ Tugmalar
    buttons = []

    # Shablon tugmasi (agar bo‘lsa)
    if template.button_text and template.button_url:
        buttons.append({
            'text': template.button_text,
            'web_app': template.button_url,  # Web App sifatida
        })

    # Qo‘shimcha tugmalar
    if extra_buttons:
        buttons.extend(extra_buttons)

    # Agar tugma bo‘lmasa — default Web App tugma
    if not buttons:
        buttons.append(web_app_button('🚀 Saytga kirish', '/testlar/'))

    return send_html_message(chat_id, text, buttons=buttons)


# ═══════════════════════════════════════════════════════════════
# O‘QUV SAVOLI
# ═══════════════════════════════════════════════════════════════

def send_study_question(
    chat_id: int,
    question,
    user_name: str = '',
    extra_buttons: list = None,
) -> bool:
    """O‘quv savolini yuborish."""
    if not question or not question.is_active:
        return False

    text = f"❓ <b>Savol</b>\n\n"
    if user_name:
        text += f"<i>{user_name},</i>\n\n"
    text += question.question

    buttons = []

    if question.options:
        for idx, opt in enumerate(question.options):
            text += f"\n\n<b>{idx + 1}.</b> {opt}"
            buttons.append({
                'text': f"{idx + 1}",
                'callback': f'answer:{question.id}:{idx}',
            })
    else:
        text += "\n\n<i>Javobingizni yozib yuboring.</i>"

    if question.hint:
        text += f"\n\n💡 <i>{question.hint}</i>"

    # Web App tugmalar
    if extra_buttons:
        buttons.extend(extra_buttons)

    sent = send_html_message(chat_id, text, buttons=buttons or None)

    if sent:
        from apps.user.models import StudyQuestion
        StudyQuestion.objects.filter(pk=question.pk).update(
            used_count=question.used_count + 1
        )

    return sent


# ═══════════════════════════════════════════════════════════════
# ADMIN QO‘LDA XABAR
# ═══════════════════════════════════════════════════════════════

def send_admin_reply(
    chat_id: int,
    admin_name: str,
    message_text: str,
    extra_buttons: list = None,
) -> bool:
    """Admin qo‘lda yozgan xabar."""
    text = (
        f"💬 <b>Xabar admin panelidan</b>\n"
        f"{'━' * 25}\n\n"
        f"{message_text}\n\n"
        f"{'━' * 25}\n"
        f"<i>Yuboruvchi: {admin_name}</i>"
    )

    # Web App tugmalar
    buttons = []
    if extra_buttons:
        buttons.extend(extra_buttons)

    return send_html_message(chat_id, text, buttons=buttons or None)


# ═══════════════════════════════════════════════════════════════
# YORDAMCHI XABARLAR
# ═══════════════════════════════════════════════════════════════

def send_text_message(chat_id: int, text: str) -> bool:
    """Oddiy matnli xabar yuborish."""
    try:
        bot = get_bot()
        bot.send_message(chat_id, text)
        return True
    except Exception as e:
        logger.exception(f"[TG] Xabar yuborilmadi: {e}")
        return False


def send_welcome_message(chat_id: int, linked: bool = False) -> bool:
    """Botga /start bosilganda."""
    if linked:
        text = (
            "✅ <b>Hisobingiz allaqachon bog‘langan!</b>\n\n"
            "Endi saytda <b>Telegram</b> tugmasini bosib, shu yerdan "
            "kod olishingiz mumkin."
        )
        buttons = [
            web_app_button('🚀 Saytga kirish', '/testlar/'),
        ]
    else:
        text = (
            "👋 <b>DIGION botiga xush kelibsiz!</b>\n\n"
            "Hisobingizni bog‘lash uchun <b>telefon raqamingizni</b> "
            "yuboring.\n\n"
            "👇 Pastdagi tugmani bosing."
        )
        buttons = None  # ReplyKeyboardMarkup ishlatiladi

    return send_html_message(chat_id, text, buttons=buttons)


def send_code_expired_message(chat_id: int) -> bool:
    """Kod muddati tugaganda."""
    return send_html_message(
        chat_id,
        "⏱ <b>Kod muddati tugadi!</b>\n\nSaytdan yangi kod so‘rang."
    )