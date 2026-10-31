"""
Telegram botni ishga tushuruvchi management command.
Ishlatish: python manage.py run_telegram_bot
"""
import logging
import telebot
from django.conf import settings
from django.core.management.base import BaseCommand
from telebot import types

from apps.user.models import CustomUser, TelegramLink
from apps.service.telegram_bot import (
    get_bot, send_welcome_message, send_text_message,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Telegram botni ishga tushirish (polling)'

    def handle(self, *args, **options):
        token = getattr(settings, 'TELEGRAM_BOT_TOKEN', None)
        if not token:
            self.stdout.write(self.style.ERROR("❌ TELEGRAM_BOT_TOKEN sozlanmagan!"))
            return

        bot = telebot.TeleBot(token, parse_mode='HTML')
        self.stdout.write(self.style.SUCCESS("🤖 Bot ishga tushdi..."))

        # ═══ /start ═══
        @bot.message_handler(commands=['start'])
        def cmd_start(message):
            chat_id = message.chat.id
            try:
                link = TelegramLink.objects.get(chat_id=chat_id, is_active=True)
                send_welcome_message(chat_id, linked=True)
            except TelegramLink.DoesNotExist:
                send_welcome_message(chat_id, linked=False)
                self._send_contact_button(bot, chat_id)

        # ═══ /help ═══
        @bot.message_handler(commands=['help'])
        def cmd_help(message):
            send_text_message(
                message.chat.id,
                "🆘 <b>Yordam</b>\n\n"
                "• /start — Hisobni bog‘lash\n"
                "• /status — Bog‘lanish holati\n"
                "• /unlink — Hisobni uzish"
            )

        # ═══ /status ═══
        @bot.message_handler(commands=['status'])
        def cmd_status(message):
            try:
                link = TelegramLink.objects.select_related('user').get(
                    chat_id=message.chat.id, is_active=True
                )
                send_text_message(
                    message.chat.id,
                    f"✅ <b>Bog‘langan</b>\n\n"
                    f"📱 {link.user.phone_number}\n"
                    f"👤 {link.user.get_full_name() or '—'}\n"
                    f"📅 {link.linked_at.strftime('%d.%m.%Y %H:%M')}"
                )
            except TelegramLink.DoesNotExist:
                send_text_message(message.chat.id, "❌ Hisob bog‘lanmagan.")

        # ═══ /unlink ═══
        @bot.message_handler(commands=['unlink'])
        def cmd_unlink(message):
            deleted, _ = TelegramLink.objects.filter(
                chat_id=message.chat.id
            ).delete()
            if deleted:
                send_text_message(message.chat.id, "✅ Hisob uzildi.")
            else:
                send_text_message(message.chat.id, "❌ Hisob bog‘lanmagan.")

        # ═══ Contact yuborilsa ═══
        @bot.message_handler(content_types=['contact'])
        def handle_contact(message):
            contact = message.contact
            chat_id = message.chat.id

            # Faqat o‘z raqami
            if contact.user_id != message.from_user.id:
                send_text_message(chat_id, "❌ Faqat <b>o‘z</b> raqamingizni yuboring.")
                return

            phone_raw = contact.phone_number or ''
            phone = self._normalize(phone_raw)

            if not phone:
                send_text_message(chat_id, "❌ Telefon raqam noto‘g‘ri.")
                return

            try:
                user = CustomUser.objects.get(phone_number=phone)
            except CustomUser.DoesNotExist:
                send_text_message(
                    chat_id,
                    f"❌ <b>{phone}</b> raqami tizimda ro‘yxatdan o‘tmagan.\n\n"
                    f"Iltimos, administratorga murojaat qiling."
                )
                return

            if not user.is_active:
                send_text_message(chat_id, "❌ Hisobingiz bloklangan.")
                return

            # Bog‘lash yoki yangilash
            link, created = TelegramLink.objects.update_or_create(
                user=user,
                defaults={
                    'chat_id': chat_id,
                    'username': message.from_user.username or '',
                    'first_name': message.from_user.first_name or '',
                    'is_active': True,
                }
            )

            send_text_message(
                chat_id,
                f"✅ <b>Muvaffaqiyatli bog‘landi!</b>\n\n"
                f"📱 {phone}\n"
                f"👤 {user.get_full_name() or '—'}\n\n"
                f"Endi saytda <b>Telegram</b> tugmasini bosib, "
                f"shu yerdan <b>1 daqiqalik</b> kod olishingiz mumkin."
            )
            self.stdout.write(self.style.SUCCESS(
                f"[TG] Bog‘landi: {phone} → {chat_id}"
            ))

        # ═══ Noma’lum xabarlar ═══
        @bot.message_handler(func=lambda m: True)
        def fallback(message):
            send_text_message(
                message.chat.id,
                "🤖 Buyruqni tushunmadim.\n\n"
                "Yordam uchun /help yozing."
            )

        # ═══ Ishga tushirish ═══
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=20)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\n⏹ Bot to‘xtatildi."))

    @staticmethod
    def _normalize(raw: str) -> str:
        import re
        if not raw:
            return ''
        digits = re.sub(r'\D', '', str(raw))
        if digits.startswith('998'):
            digits = digits[3:]
        if len(digits) != 9:
            return ''
        return f"+998{digits}"

    @staticmethod
    def _send_contact_button(bot, chat_id):
        """Telefon raqam so‘rash tugmasi."""
        kb = types.ReplyKeyboardMarkup(
            resize_keyboard=True, one_time_keyboard=True
        )
        button = types.KeyboardButton(
            text="📱 Telefon raqamni yuborish",
            request_contact=True,
        )
        kb.add(button)
        bot.send_message(
            chat_id,
            "👇 Telefon raqamingizni yuboring:",
            reply_markup=kb,
        )