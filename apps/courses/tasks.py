# apps/courses/tasks.py
"""
Uyga vazifa yuborish — adminning qo'lda yuborish so'rovi.
================================================

XUSUSIYATLAR:
- Faqat admin yuborish so'rovi bilan ishga tushadi
- Retry logikasi (DB lock uchun)
- Xato boshqaruvi (har xil holatlar)
- To'liq logging (har bosqichda)
- Statistika (sent/failed/skipped)
- Adminga hisobot
- Homework statistikasi yangilash
- Idempotentlik (ikki marta yubormaslik)

MUHIM:
- `group` — `user.StudentGroup` (course maydoni YO'Q!)
- Faqat `group.teacher` bor
"""
import logging
import time
from datetime import timedelta

from django.conf import settings
from django.db import OperationalError, DatabaseError
from django.utils import timezone

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# KONSTANTALAR
# ═══════════════════════════════════════════════════════════════

# DB lock uchun retry
DB_MAX_RETRIES = 3
DB_RETRY_DELAY = 2  # sekund

# Status choices
STATUS_SCHEDULED = 'scheduled'
STATUS_SENDING = 'sending'
STATUS_SENT = 'sent'
STATUS_FAILED = 'failed'
STATUS_PARTIAL = 'partial'
STATUS_CANCELLED = 'cancelled'


# ═══════════════════════════════════════════════════════════════
# YORDAMCHI: DB retry
# ═══════════════════════════════════════════════════════════════

def _db_retry(func, *args, **kwargs):
    """
    DB lock bo'lganda qayta urinish.
    SQLite uchun foydali — bir vaqtda ko'p yozuv bo'lganda.
    """
    last_error = None
    for attempt in range(DB_MAX_RETRIES):
        try:
            return func(*args, **kwargs)
        except OperationalError as e:
            last_error = e
            if 'database is locked' in str(e).lower() and attempt < DB_MAX_RETRIES - 1:
                logger.warning(
                    f"⏳ DB locked, urinish {attempt + 1}/{DB_MAX_RETRIES}"
                )
                time.sleep(DB_RETRY_DELAY)
            else:
                raise
    if last_error:
        raise last_error


# ═══════════════════════════════════════════════════════════════
# ASOSIY JOB: GURUHGA UYGA VAZIFA YUBORISH
# ═══════════════════════════════════════════════════════════════

def send_homework_to_group_job(
    group_lesson_id: int, force: bool = False, manual: bool = False
):
    """
    Guruhga uyga vazifani faqat qo'lda berilgan so'rov bilan yuborish.

    Args:
        group_lesson_id: GroupLesson primary key
        force: True bo'lsa, allaqachon yuborilgan bo'lsa ham qayta yuboradi
        manual: True bo'lsa, adminning aniq qo'lda yuborish so'rovi

    Returns:
        dict: {
            'ok': bool,
            'sent': int,
            'failed': int,
            'total': int,
            'status': str,
            'error': str (xato bo'lsa),
            'reason': str (skip bo'lsa),
        }
    """
    from apps.courses.models import GroupLesson
    from apps.service.homework_sender import HomeworkSender

    start_time = time.time()
    gl_id = group_lesson_id

    if not manual:
        logger.warning(
            f"⏭ GL#{gl_id}: avtomatik yuborish o'chirilgan; "
            "faqat qo'lda yuborish ruxsat etilgan"
        )
        return {'ok': False, 'reason': 'manual_only'}

    logger.info(f"🚀 Job boshlandi: GL#{gl_id}")

    # ═══════════════════════════════════════════════════════════
    # 1. GL NI OLISH
    # ═══════════════════════════════════════════════════════════
    try:
        # ⚠️ MUHIM: `group__course` YO'Q!
        # `group` — user.StudentGroup, unda faqat `teacher` bor
        gl = GroupLesson.objects.select_related(
            'group',
            'lesson',
            'lesson__homework',
            'lesson__course',
        ).get(pk=gl_id)
    except GroupLesson.DoesNotExist:
        logger.error(f"❌ GL#{gl_id} topilmadi")
        return {'ok': False, 'error': 'not_found', 'reason': 'not_found'}
    except Exception as e:
        logger.exception(f"❌ GL#{gl_id} olishda xato: {e}")
        return {'ok': False, 'error': str(e), 'reason': 'fetch_error'}

    # ═══════════════════════════════════════════════════════════
    # 2. ALLAQACHON YUBORILGANMI?
    # ═══════════════════════════════════════════════════════════
    if not force and gl.homework_status in (STATUS_SENT, STATUS_SENDING):
        logger.warning(
            f"⏭ GL#{gl.pk} allaqachon yuborilgan: {gl.homework_status}"
        )
        return {
            'ok': False,
            'reason': 'already_sent',
            'status': gl.homework_status,
        }

    # ═══════════════════════════════════════════════════════════
    # 3. HOMEWORK TEKSHIRISH
    # ═══════════════════════════════════════════════════════════
    homework = getattr(gl.lesson, 'homework', None)

    if not homework:
        logger.warning(f"⚠️ GL#{gl.pk} — homework yo'q")
        try:
            _db_retry(
                lambda: gl.save(update_fields=['homework_status', 'updated_at'])
                if setattr(gl, 'homework_status', STATUS_FAILED) is None
                else None
            )
            gl.homework_status = STATUS_FAILED
            gl.save(update_fields=['homework_status', 'updated_at'])
        except Exception as e:
            logger.exception(f"Save xatosi: {e}")
        return {'ok': False, 'reason': 'no_homework'}

    if not homework.is_approved:
        logger.warning(
            f"⏭ GL#{gl.pk} — homework tasdiqlanmagan: {homework.pk}"
        )
        return {'ok': False, 'reason': 'not_approved'}

    # ═══════════════════════════════════════════════════════════
    # 4. STATUS: YUBORILMOQDA
    # ═══════════════════════════════════════════════════════════
    try:
        def _set_sending():
            queryset = GroupLesson.objects.filter(pk=gl.pk)
            if not force:
                queryset = queryset.exclude(
                    homework_status__in=[STATUS_SENT, STATUS_SENDING]
                )
            updated = queryset.update(homework_status=STATUS_SENDING)
            if updated:
                gl.homework_status = STATUS_SENDING
            return updated

        claimed = _db_retry(_set_sending)
    except Exception as e:
        logger.exception(f"GL#{gl.pk} status yangilashda xato: {e}")
        return {'ok': False, 'error': str(e), 'reason': 'status_error'}
    if not claimed:
        return {
            'ok': False,
            'reason': 'already_sent',
            'status': gl.homework_status,
        }

    # ═══════════════════════════════════════════════════════════
    # 5. YUBORISH
    # ═══════════════════════════════════════════════════════════
    try:
        result = HomeworkSender.deliver(gl, homework)
    except Exception as e:
        logger.exception(f"❌ GL#{gl.pk} yuborishda xato: {e}")
        try:
            gl.homework_status = STATUS_FAILED
            gl.save(update_fields=['homework_status', 'updated_at'])
        except Exception:
            pass
        return {'ok': False, 'error': str(e), 'reason': 'deliver_error'}

    # ═══════════════════════════════════════════════════════════
    # 6. NATIJANI TEKSHIRISH
    # ═══════════════════════════════════════════════════════════
    sent = result.get('sent_count', 0)
    failed = result.get('failed_count', 0)
    skipped = result.get('skipped_count', 0)
    total = result.get('total', 0)

    # Status aniqlash
    if sent == 0 and failed == 0 and skipped == 0:
        status = STATUS_FAILED
    elif sent == 0 and failed > 0:
        status = STATUS_FAILED
    elif failed > 0:
        status = STATUS_PARTIAL
    elif sent > 0:
        status = STATUS_SENT
    else:
        status = STATUS_FAILED

    # ═══════════════════════════════════════════════════════════
    # 7. GL STATUS YANGILASH
    # ═══════════════════════════════════════════════════════════
    try:
        def _update_gl():
            gl.homework_status = status
            gl.homework_sent_at = timezone.now()
            gl.homework_recipients_count = sent
            gl.homework_failed_count = failed
            gl.is_sent = True
            gl.sent_at = timezone.now()
            gl.scheduled_task_id = None
            gl.save(update_fields=[
                'homework_status', 'homework_sent_at',
                'homework_recipients_count', 'homework_failed_count',
                'is_sent', 'sent_at', 'scheduled_task_id', 'updated_at',
            ])

        _db_retry(_update_gl)
    except Exception as e:
        logger.exception(f"GL#{gl.pk} status saqlashda xato: {e}")

    # ═══════════════════════════════════════════════════════════
    # 8. HOMEWORK STATISTIKASI
    # ═══════════════════════════════════════════════════════════
    if status in (STATUS_SENT, STATUS_PARTIAL):
        try:
            def _update_hw():
                homework.is_sent = True
                if not homework.sent_at:
                    homework.sent_at = timezone.now()
                homework.save(update_fields=['is_sent', 'sent_at'])
                try:
                    homework.sent_to_groups.add(gl.group)
                except Exception as e:
                    logger.warning(f"sent_to_groups xatosi: {e}")

            _db_retry(_update_hw)
        except Exception as e:
            logger.exception(f"Homework stats yangilashda xato: {e}")

    # ═══════════════════════════════════════════════════════════
    # 9. LOG
    # ═══════════════════════════════════════════════════════════
    elapsed = (time.time() - start_time) * 1000
    logger.info(
        f"{'✅' if status == STATUS_SENT else '⚠️' if status == STATUS_PARTIAL else '❌'} "
        f"GL#{gl.pk} — status={status} "
        f"sent={sent} failed={failed} skipped={skipped} total={total} "
        f"({elapsed:.0f}ms)"
    )

    # ═══════════════════════════════════════════════════════════
    # 10. ADMINGA HISOBOT
    # ═══════════════════════════════════════════════════════════
    try:
        HomeworkSender.notify_admin(gl, homework, result)
        logger.debug(f"📤 Admin notify yuborildi: GL#{gl.pk}")
    except Exception as e:
        logger.exception(f"Admin notify xatosi (GL#{gl.pk}): {e}")

    # ═══════════════════════════════════════════════════════════
    # 11. NATIJA
    # ═══════════════════════════════════════════════════════════
    return {
        'ok': True,
        'sent': sent,
        'failed': failed,
        'skipped': skipped,
        'total': total,
        'status': status,
        'group_lesson_id': gl.pk,
        'homework_id': homework.pk,
    }


# ═══════════════════════════════════════════════════════════════
# BULK REJALASHTIRISH
# ═══════════════════════════════════════════════════════════════

def bulk_schedule_homework_for_group(group_id: int):
    """
    Bitta guruh uchun barcha kelajakdagi GL larni rejalashtirish.

    Bu funksiya admin panelidan qo'lda chaqirilishi mumkin.
    """
    from apps.user.models import StudentGroup
    from apps.service.homework_scheduler import HomeworkScheduler

    try:
        group = StudentGroup.objects.get(pk=group_id)
    except StudentGroup.DoesNotExist:
        logger.error(f"Guruh #{group_id} topilmadi")
        return {'ok': False, 'error': 'not_found'}

    result = HomeworkScheduler.bulk_schedule_for_group(group)
    logger.info(f"📊 Bulk schedule: {group.name} — {result}")
    return {'ok': True, **result}


# ═══════════════════════════════════════════════════════════════
# DEBUG: JOB TEST
# ═══════════════════════════════════════════════════════════════

def debug_job_info(group_lesson_id: int):
    """
    GL haqida to'liq debug ma'lumot.
    Faqat DEBUG=True da ishlatiladi.
    """
    if not getattr(settings, 'DEBUG', False):
        return {'error': 'Debug mode kerak'}

    from apps.courses.models import GroupLesson
    from apps.service.homework_scheduler import HomeworkScheduler

    try:
        gl = GroupLesson.objects.select_related(
            'group', 'lesson', 'lesson__homework', 'lesson__course',
        ).get(pk=group_lesson_id)
    except GroupLesson.DoesNotExist:
        return {'error': 'not_found'}

    info = HomeworkScheduler.get_gl_info(gl)
    return info


# ═══════════════════════════════════════════════════════════════
# EXPORTS
# ═══════════════════════════════════════════════════════════════

__all__ = [
    'send_homework_to_group_job',
    'bulk_schedule_homework_for_group',
    'debug_job_info',
]