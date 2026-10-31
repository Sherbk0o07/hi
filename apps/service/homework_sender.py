# apps/courses/services/homework_sender.py
"""
Faqat yuborish logikasi (side-effect'lar).
================================================
XUSUSIYATLAR:
- Talabaga WebApp link bilan xabar
- Guruh (gl) ID bilan URL — auto-login uchun
- Adminga hisobot (muvaffaqiyatli/xato)
- Admin tugmalar orqali tasdiqlash
- Har bir talaba uchun log
- Telegram bog'lanmagan talabalarni aniqlash
"""
import logging
from django.conf import settings
from django.utils import timezone

from apps.courses.models import HomeworkDeliveryLog
from apps.user.models import TelegramLink
from apps.service.telegram_bot import send_html_message, web_app_button

logger = logging.getLogger(__name__)


class HomeworkSender:
    """
    Uyga vazifani talabalarga yuborish + adminga hisobot.

    Asosiy metodlar:
        deliver(gl, homework) — barcha talabalarga yuborish
        notify_admin(gl, homework, result) — adminga hisobot
        notify_admin_approval(...) — admin tasdiqlash uchun
    """

    # ═══════════════════════════════════════════════════════════
    # ASOSIY: BARCHA TALABALARGA YUBORISH
    # ═══════════════════════════════════════════════════════════

    @classmethod
    def deliver(cls, group_lesson, homework):
        """
        Barcha talabalarga yuborish.

        Qaytaradi:
            {
                'sent_count': int,
                'failed_count': int,
                'skipped_count': int,
                'total': int,
                'details': [{'student_id', 'name', 'status', 'error'}, ...],
                'students_list': [...],  # admin report uchun
            }
        """
        students = (
            group_lesson.group.students
            .select_related('user')
            .filter(user__is_active=True)
        )

        message = cls._build_message(homework, group_lesson)
        students_count = students.count()

        logger.info(
            f"📤 Yuborish boshlandi: GL#{group_lesson.pk} "
            f"({students_count} talaba)"
        )

        sent = failed = skipped = 0
        details = []

        for student in students:
            d = cls._send_one(student, homework, group_lesson, message)
            details.append(d)

            if d['status'] == 'sent':
                sent += 1
            elif d['status'] == 'failed':
                failed += 1
            else:
                skipped += 1

        logger.info(
            f"✅ Yuborish tugadi: GL#{group_lesson.pk} — "
            f"sent={sent}, failed={failed}, skipped={skipped}, "
            f"total={students_count}"
        )

        return {
            'sent_count': sent,
            'failed_count': failed,
            'skipped_count': skipped,
            'total': students_count,
            'details': details,
        }

    # ═══════════════════════════════════════════════════════════
    # BITTA TALABAGA YUBORISH
    # ═══════════════════════════════════════════════════════════

    @classmethod
    def _send_one(cls, student, homework, gl, message):
        """
        Bitta talabaga yuborish.
        WebApp link bilan.
        """
        # ─── 1. Telegram tekshirish ───
        link = TelegramLink.objects.filter(
            user=student.user, is_active=True
        ).first()

        if not link:
            cls._log(
                gl, homework, student, 'skipped',
                error="Telegram bog'lanmagan"
            )
            return {
                'student_id': student.pk,
                'name': cls._student_name(student),
                'status': 'skipped',
                'error': "Telegram yo'q",
            }

        # ─── 2. WebApp URL (gl bilan!) ───
        homework_url = cls._build_homework_url(gl, homework)

        # ─── 3. Tugma ───
        btn = web_app_button("✍️ Vazifani bajarish", homework_url)

        # ─── 4. Yuborish ───
        try:
            ok = send_html_message(
                link.chat_id,
                message,
                buttons=[btn],
            )
        except Exception as e:
            logger.exception(f"Telegram xatosi ({student.pk}): {e}")
            ok = False

        # ─── 5. Natija ───
        status = 'sent' if ok else 'failed'
        error = '' if ok else 'Telegram API xatosi'

        cls._log(
            gl, homework, student, status,
            error=error, chat_id=link.chat_id
        )

        return {
            'student_id': student.pk,
            'name': cls._student_name(student),
            'status': status,
            'error': error,
        }

    # ═══════════════════════════════════════════════════════════
    # URL YASASH — WebApp link
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _build_homework_url(gl, homework):
        """
        WebApp URL — auto-login uchun.

        Format:
            https://site.com/homework/<homework_pk>/?gl=<group_lesson_pk>

        `gl` — qaysi guruhdan kelgani (bitta vazifa bir nechta guruhga ketishi mumkin).
        """
        base = getattr(settings, 'SITE_URL', 'https://digion.uz').rstrip('/')
        return f"{base}/homework/{homework.pk}/?gl={gl.pk}"

    # ═══════════════════════════════════════════════════════════
    # LOG
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _log(gl, hw, student, status, error='', chat_id=None):
        """HomeworkDeliveryLog ga yozish."""
        try:
            HomeworkDeliveryLog.objects.update_or_create(
                group_lesson=gl,
                student=student,
                defaults={
                    'homework': hw,
                    'status': status,
                    'error': error,
                    'chat_id': chat_id,
                    'sent_at': timezone.now() if status == 'sent' else None,
                },
            )
        except Exception:
            logger.exception("Log yozishda xato")

    # ═══════════════════════════════════════════════════════════
    # XABAR MATNI (HTML)
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _build_message(homework, gl):
        """Talabaga ketadigan xabar matni."""
        lesson = gl.lesson
        group = gl.group

        lines = [
            "📚 <b>YANGI UYGA VAZIFA!</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"📖 <b>Kurs:</b> {lesson.course.title}",
            f"📝 <b>Dars:</b> {lesson.lesson_number}-dars. {lesson.title}",
            f"👥 <b>Guruh:</b> {group.name}",
            "",
            f"📌 <b>Vazifa:</b> {homework.title}",
            f"⏱ <b>Muddat:</b> {homework.deadline_days} kun",
            f"🏆 <b>Maks. ball:</b> {homework.max_score}",
        ]

        if homework.short_description:
            lines.append(f"\n💬 {homework.short_description}")

        lines.append("")
        lines.append("👇 <i>Quyidagi tugma orqali vazifani bajarishingiz mumkin.</i>")

        return "\n".join(lines)

    # ═══════════════════════════════════════════════════════════
    # ADMINGA HISOBOT — vazifa yuborilgandan keyin
    # ═══════════════════════════════════════════════════════════

    @classmethod
    def notify_admin(cls, gl, homework, result):
        """
        Adminga hisobot: guruhga vazifa yuborildi.
        Har bir talaba holati bilan.
        """
        admin_id = getattr(settings, 'ADMIN_TELEGRAM_CHAT_ID', None)
        if not admin_id:
            logger.warning("ADMIN_TELEGRAM_CHAT_ID sozlanmagan")
            return

        now = timezone.localtime().strftime('%d.%m.%Y %H:%M')

        # ─── Talabalar ro'yxati ───
        lines = []
        for d in result['details'][:30]:
            icon = {
                'sent': '✅',
                'failed': '❌',
                'skipped': '⏭',
            }.get(d['status'], '❓')

            line = f"{icon} {d['name']}"
            if d['error']:
                line += f" — <i>{d['error'][:40]}</i>"
            lines.append(line)

        if len(result['details']) > 30:
            lines.append(f"… +{len(result['details']) - 30}")

        # ─── Umumiy status ───
        if result['failed_count'] == 0 and result['sent_count'] > 0:
            status_icon = '✅'
            status_text = 'MUVAFFAQIYATLI'
        elif result['sent_count'] > 0:
            status_icon = '⚠️'
            status_text = 'QISMAN YUBORILDI'
        else:
            status_icon = '❌'
            status_text = 'YUBORILMADI'

        # ─── Xabar matni ───
        text = (
                f"📤 <b>UYGA VAZIFA YUBORILDI</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"👥 <b>Guruh:</b> {gl.group.name}\n"
                f"📚 <b>Kurs:</b> {gl.lesson.course.title}\n"
                f"📝 <b>Dars:</b> {gl.lesson.lesson_number}. {gl.lesson.title}\n"
                f"📌 <b>Vazifa:</b> {homework.title}\n"
                f"🕐 <b>Vaqt:</b> <code>{now}</code>\n\n"
                f"{status_icon} <b>{status_text}</b>\n"
                f"  ✅ Yuborildi: <b>{result['sent_count']}</b>\n"
                f"  ❌ Xato: <b>{result['failed_count']}</b>\n"
                f"  ⏭ O'tkazildi: <b>{result['skipped_count']}</b>\n"
                f"  📊 Jami: <b>{result['total']}</b>\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                + "\n".join(lines)
        )

        try:
            send_html_message(admin_id, text)
        except Exception:
            logger.exception("Admin xabar yuborishda xato")

    # ═══════════════════════════════════════════════════════════
    # ADMINGA TASDIQLASH SO'ROVI — bitta talaba uchun
    # ═══════════════════════════════════════════════════════════

    @classmethod
    def notify_admin_for_approval(
            cls,
            submission,
            notification_type='homework_submitted',
    ):
        """
        Adminga tasdiqlash so'rovi:
        'Ali vazifani bajardi. Ota-onaga yuborilsinmi?'

        Telegram tugmalar bilan: [✅ YUBOR] [❌ BEKOR]
        """
        admin_id = getattr(settings, 'ADMIN_TELEGRAM_CHAT_ID', None)
        if not admin_id:
            logger.warning("ADMIN_TELEGRAM_CHAT_ID yo'q")
            return None

        student = submission.student
        homework = submission.homework

        now = timezone.localtime().strftime('%d.%m.%Y %H:%M')

        # ─── Type bo'yicha sarlavha ───
        if notification_type == 'homework_submitted':
            header = "🎓 <b>TALABA VAZIFANI BAJARDI</b>"
            action_text = "Ota-onaga maqtov xabari yuborilsinmi?"
        else:  # homework_missed
            header = "⚠️ <b>VAZIFA BAJARILMADI</b>"
            action_text = "Ota-onaga ogohlantirish yuborilsinmi?"

        # ─── Fayl ma'lumoti ───
        file_info = ""
        if submission.answer_file:
            try:
                size_kb = submission.answer_file.size / 1024
                file_info = (
                    f"\n📎 <b>Fayl:</b> {submission.answer_file.name} "
                    f"({size_kb:.0f} KB)"
                )
            except Exception:
                file_info = "\n📎 <b>Fayl:</b> biriktirilgan"

        # ─── Xabar ───
        text = (
            f"{header}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 <b>Talaba:</b> {cls._student_name(student)}\n"
            f"👥 <b>Guruh:</b> {submission.homework.lesson.course.title}\n"
            f"📝 <b>Dars:</b> {homework.lesson.lesson_number}. {homework.lesson.title}\n"
            f"📌 <b>Vazifa:</b> {homework.title}\n"
            f"🕐 <b>Vaqt:</b> <code>{now}</code>"
            f"{file_info}\n"
        )

        # ─── Ball (agar baholangan bo'lsa) ───
        if submission.score is not None:
            text += (
                f"🏆 <b>Ball:</b> {submission.score}/{homework.max_score} "
                f"({submission.percent}%)\n"
            )

        # ─── Kechikkan ───
        if submission.is_late:
            text += "⏰ <b>Kechikkan</b>\n"

        text += (
            f"\n━━━━━━━━━━━━━━━━━━━━━━\n"
            f"❓ <b>{action_text}</b>"
        )

        # ─── Telegram tugmalar ───
        # ⭐ MUHIM: callback_data da submission ID bo'ladi
        approve_callback = f"approve_parent:{submission.pk}:1"
        reject_callback = f"approve_parent:{submission.pk}:0"

        buttons = [
            {'text': '✅ HA, YUBOR', 'callback': approve_callback},
            {'text': "❌ YO'Q, BEKOR", 'callback': reject_callback},
        ]

        try:
            ok = send_html_message(admin_id, text, buttons=buttons)
            return {'ok': ok, 'message': text}
        except Exception as e:
            logger.exception(f"Approval xabar yuborishda xato: {e}")
            return {'ok': False, 'error': str(e)}

    # ═══════════════════════════════════════════════════════════
    # OTA-ONAGA XABAR — admin tasdiqlagandan keyin
    # ═══════════════════════════════════════════════════════════

    @classmethod
    def notify_parent(cls, submission, is_praise=True):
        """
        Ota-onaga xabar yuborish.

        is_praise=True → maqtov
        is_praise=False → ogohlantirish

        Avval TG orqali, agar yo'q bo'lsa — SMS.
        """
        from apps.user.models import TelegramLink

        student = submission.student
        homework = submission.homework

        # ─── Ota-onani topish ───
        parent_user = cls._find_parent(student)
        if not parent_user:
            logger.warning(f"Talaba {student.pk} uchun ota-ona topilmadi")
            return {'ok': False, 'reason': 'no_parent'}

        # ─── Xabar matni ───
        if is_praise:
            text = cls._build_praise_message(student, homework, submission)
        else:
            text = cls._build_warning_message(student, homework)

        # ─── 1. Telegram orqali ───
        link = TelegramLink.objects.filter(
            user=parent_user, is_active=True
        ).first()

        if link:
            try:
                ok = send_html_message(link.chat_id, text)
                if ok:
                    return {'ok': True, 'channel': 'telegram'}
            except Exception as e:
                logger.exception(f"Parent TG xatosi: {e}")

        # ─── 2. SMS orqali (zaxira) ───
        parent_phone = getattr(student, 'parent_phone', None)
        if parent_phone:
            try:
                ok = cls._send_sms(parent_phone, text)
                if ok:
                    return {'ok': True, 'channel': 'sms'}
            except Exception as e:
                logger.exception(f"Parent SMS xatosi: {e}")

        return {'ok': False, 'reason': 'no_channel'}

    # ═══════════════════════════════════════════════════════════
    # YORDAMCHI METODLAR
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _student_name(student):
        """Talabaning to'liq ismi."""
        try:
            name = student.user.get_full_name()
            return name or student.user.phone_number
        except Exception:
            return f"Talaba #{student.pk}"

    @staticmethod
    def _find_parent(student):
        """
        Talabaning ota-onasini topish.
        1. student.parent_user (agar FK bo'lsa)
        2. CustomUser role='parent' + telefon bo'yicha
        """
        # 1-usul: to'g'ridan-to'g'ri FK
        parent_user = getattr(student, 'parent_user', None)
        if parent_user:
            return parent_user

        # 2-usul: telefon raqam orqali
        from apps.user.models import CustomUser
        parent_phone = getattr(student, 'parent_phone', None)
        if parent_phone:
            return CustomUser.objects.filter(
                phone_number=parent_phone,
                role='parent',
                is_active=True,
            ).first()

        return None

    @staticmethod
    def _build_praise_message(student, homework, submission):
        """Ota-onaga maqtov xabari."""
        name = HomeworkSender._student_name(student)
        score_line = ""
        if submission.score is not None:
            score_line = (
                f"\n🏆 <b>Ball:</b> {submission.score}/{homework.max_score}"
                f" ({submission.percent}%)"
            )

        return (
            f"🎉 <b>YAXSHI XABAR!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Assalomu alaykum, hurmatli ota-ona!\n\n"
            f"Farzandingiz <b>{name}</b>\n"
            f"bugungi uyga vazifani "
            f"<b>muvaffaqiyatli bajardi</b> ✅\n\n"
            f"📚 <b>Kurs:</b> {homework.lesson.course.title}\n"
            f"📝 <b>Dars:</b> {homework.lesson.lesson_number}. {homework.lesson.title}\n"
            f"📌 <b>Vazifa:</b> {homework.title}"
            f"{score_line}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💚 <i>Farzandingizni rag'batlantiring!</i>"
        )

    @staticmethod
    def _build_warning_message(student, homework):
        """Ota-onaga ogohlantirish xabari."""
        name = HomeworkSender._student_name(student)
        return (
            f"⚠️ <b>DIQQAT!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Assalomu alaykum, hurmatli ota-ona!\n\n"
            f"Farzandingiz <b>{name}</b>\n"
            f"bugungi uyga vazifani "
            f"<b>bajarmadi</b> ❌\n\n"
            f"📚 <b>Kurs:</b> {homework.lesson.course.title}\n"
            f"📝 <b>Dars:</b> {homework.lesson.lesson_number}. {homework.lesson.title}\n"
            f"📌 <b>Vazifa:</b> {homework.title}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💬 <i>Iltimos, farzandingiz bilan gaplashing.</i>"
        )

    @staticmethod
    def _send_sms(phone, text):
        """SMS yuborish (kelajakda to'ldiriladi)."""
        # TODO: SMS provayder integratsiyasi
        logger.info(f"📱 SMS → {phone}: {text[:50]}...")
        # Hozircha False qaytaramiz
        return False