"""
N soatdan ortiq kirmagan foydalanuvchilarni tekshirib, xabar yuborish.
Cron: har soatda bir marta ishga tushirish.
"""
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone

from apps.service.notification_service import (
    send_to_inactive_users, send_morning_boost,
)


class Command(BaseCommand):
    help = 'Faol bo‘lmagan foydalanuvchilarga Telegram xabar yuborish'

    def handle(self, *args, **options):
        now = timezone.localtime()
        hour = now.hour

        self.stdout.write(f"⏰ Vaqt: {now.strftime('%H:%M')}")

        # ═══ Ertalab (07:00) ═══
        if hour == 7:
            result = send_morning_boost()
            self.stdout.write(
                self.style.SUCCESS(
                    f"🌅 Morning boost: {result['sent']} yuborildi, "
                    f"{result['failed']} xato"
                )
            )

        # ═══ 4 soatlik ═══
        result_4h = send_to_inactive_users(
            'inactive_4h',
            getattr(settings, 'INACTIVE_4H_THRESHOLD', 4)
        )
        self.stdout.write(
            self.style.WARNING(
                f"⏱ 4 soat: {result_4h['sent']} yuborildi, "
                f"{result_4h['failed']} xato, "
                f"{result_4h['skipped']} o‘tkazildi"
            )
        )

        # ═══ 7 soatlik ═══
        result_7h = send_to_inactive_users(
            'inactive_7h',
            getattr(settings, 'INACTIVE_7H_THRESHOLD', 7)
        )
        self.stdout.write(
            self.style.WARNING(
                f"⏱ 7 soat: {result_7h['sent']} yuborildi, "
                f"{result_7h['failed']} xato"
            )
        )

        # ═══ 1 kunlik ═══
        result_1d = send_to_inactive_users(
            'inactive_1d',
            getattr(settings, 'INACTIVE_1D_THRESHOLD', 24)
        )
        self.stdout.write(
            self.style.ERROR(
                f"📅 1 kun: {result_1d['sent']} yuborildi, "
                f"{result_1d['failed']} xato"
            )
        )

        # ═══ 3 kunlik ═══
        result_3d = send_to_inactive_users(
            'inactive_3d',
            getattr(settings, 'INACTIVE_3D_THRESHOLD', 72)
        )
        self.stdout.write(
            self.style.ERROR(
                f"📅 3 kun: {result_3d['sent']} yuborildi, "
                f"{result_3d['failed']} xato"
            )
        )

        self.stdout.write(self.style.SUCCESS("✅ Tekshirish yakunlandi"))