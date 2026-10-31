# apps/service/homework_scheduler.py
"""
Uyga vazifalar uchun eski APScheduler joblarini boshqarish vositalari.
Avtomatik yuborish o'chirilgan; vazifalar faqat admin tomonidan qo'lda yuboriladi.

XUSUSIYATLAR:
- ETA hisoblash (guruh jadvali bo'yicha, ma'lumot uchun)
- Eski joblarni bekor qilish va tozalash
- Statistika va debug
- Retry logikasi (DB lock uchun)
- Xato boshqaruvi
"""
import logging
import time
from datetime import datetime, timedelta, time as time_cls

from django.conf import settings
from django.db import OperationalError
from django.utils import timezone

from apps.courses.models import GroupLesson, Lesson, Homework, StudentGroup

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# KONSTANTALAR
# ═══════════════════════════════════════════════════════════════

DAY_NAMES = [
    'monday', 'tuesday', 'wednesday', 'thursday',
    'friday', 'saturday', 'sunday',
]

DEFAULT_GRACE_MINUTES = 2
DEFAULT_MISFIRE_GRACE_SECONDS = 300  # 5 daqiqa
ETA_PAST_THRESHOLD_MINUTES = 10
JOB_ID_PREFIX = 'hw_gl_'

# DB lock uchun retry
DB_MAX_RETRIES = 3
DB_RETRY_DELAY = 2  # sekund


# ═══════════════════════════════════════════════════════════════
# YORDAMCHI: DB retry
# ═══════════════════════════════════════════════════════════════

def _db_retry(func, *args, **kwargs):
    """
    DB lock bo'lganda qayta urinish.

    SQLite uchun foydali — bir vaqtda ko'p yozuv bo'lganda.
    """
    for attempt in range(DB_MAX_RETRIES):
        try:
            return func(*args, **kwargs)
        except OperationalError as e:
            if 'database is locked' in str(e).lower() and attempt < DB_MAX_RETRIES - 1:
                logger.warning(
                    f"⏳ DB locked, urinish {attempt + 1}/{DB_MAX_RETRIES}"
                )
                time.sleep(DB_RETRY_DELAY)
            else:
                raise


# ═══════════════════════════════════════════════════════════════
# APScheduler INSTANSIYASINI OLISH
# ═══════════════════════════════════════════════════════════════

def _get_scheduler():
    """Global APScheduler instance ni olish."""
    try:
        from config import scheduler as sched_module
        scheduler = getattr(sched_module, '_scheduler', None)
        if scheduler is None:
            logger.debug("Scheduler instance topilmadi (None)")
        return scheduler
    except Exception as e:
        logger.exception(f"Scheduler import xatosi: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# ASOSIY KLASS
# ═══════════════════════════════════════════════════════════════

class HomeworkScheduler:
    """
    Eski homework joblarini boshqarish va diagnostika yordamchisi.

    XUSUSIYAT: `group` FK `user.StudentGroup` ga ishora qiladi
    (u yerda `is_deleted` maydoni YO'Q, faqat `is_active`).
    Shuning uchun `group__is_deleted` ishlatilmaydi.
    """

    # ═══════════════════════════════════════════════════════════
    # 1. ETA HISOBLASH
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def calculate_eta(group_lesson):
        """Aniq yuborish vaqtini hisoblash."""
        if not group_lesson.lesson_date:
            return None

        # ⭐ XAVFSIZ — schedule yo'q bo'lsa {} qaytaradi
        schedule = getattr(group_lesson.group, 'schedule', None) or {}

        if not schedule:
            logger.debug(
                f"GL#{group_lesson.pk}: guruhda schedule yo'q "
                f"(type={type(group_lesson.group).__name__})"
            )
            return None

        day_name = DAY_NAMES[group_lesson.lesson_date.weekday()]
        time_str = schedule.get(day_name)

        if not time_str:
            logger.debug(
                f"GL#{group_lesson.pk}: {day_name} jadvalda yo'q"
            )
            return None

        try:
            hh, mm = map(int, str(time_str).split(':'))
            if not (0 <= hh < 24 and 0 <= mm < 60):
                logger.warning(
                    f"GL#{group_lesson.pk}: noto'g'ri vaqt {time_str}"
                )
                return None
        except (ValueError, AttributeError, TypeError):
            logger.warning(
                f"GL#{group_lesson.pk}: vaqt parse xatosi: {time_str}"
            )
            return None

        grace = getattr(
            settings, 'HOMEWORK_GRACE_MINUTES', DEFAULT_GRACE_MINUTES
        )

        naive = datetime.combine(
            group_lesson.lesson_date,
            time_cls(hour=hh, minute=mm),
        ) + timedelta(minutes=grace)

        try:
            eta = timezone.make_aware(
                naive, timezone.get_current_timezone()
            )
        except Exception as e:
            logger.exception(f"GL#{group_lesson.pk}: timezone xatosi: {e}")
            return None

        return eta
    # ═══════════════════════════════════════════════════════════
    # 2. REJALASHTIRISH
    # ═══════════════════════════════════════════════════════════

    @classmethod
    def schedule_homework(cls, group_lesson, force=False):
        """Avtomatik jo'natish o'chirilgan; vazifa faqat qo'lda yuboriladi."""
        logger.info(
            "GL#%s uchun avtomatik homework rejalashtirilmadi: manual-only",
            group_lesson.pk,
        )
        return {'scheduled': False, 'reason': 'manual_only'}

    # ═══════════════════════════════════════════════════════════
    # 3. BEKOR QILISH
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def cancel_scheduled(group_lesson):
        """Rejalashtirilgan APScheduler jobni bekor qilish."""
        if not group_lesson.scheduled_task_id:
            return False

        scheduler = _get_scheduler()
        if not scheduler:
            return False

        job_id = group_lesson.scheduled_task_id

        try:
            scheduler.remove_job(job_id)
            logger.info(f"❌ Job bekor qilindi: {job_id}")
            return True
        except Exception as e:
            logger.warning(f"Job bekor qilishda ogohlantirish ({job_id}): {e}")
            return False

    # ═══════════════════════════════════════════════════════════
    # 4. QAYTA REJALASHTIRISH
    # ═══════════════════════════════════════════════════════════

    @classmethod
    def reschedule(cls, group_lesson):
        """Eski jobni bekor qilib, yangi ETA bilan qayta rejalashtirish."""
        logger.info(f"🔄 Reschedule: GL#{group_lesson.pk}")
        cls.cancel_scheduled(group_lesson)
        return cls.schedule_homework(group_lesson, force=True)

    # ═══════════════════════════════════════════════════════════
    # 5. GURUH UCHUN HAMMASINI BEKOR QILISH
    # ═══════════════════════════════════════════════════════════

    @classmethod
    def cancel_all_for_group(cls, group):
        """Guruhning barcha kelajakdagi joblarini bekor qilish."""
        pending = GroupLesson.objects.filter(
            group=group,
            homework_status='scheduled',
        ).exclude(
            scheduled_task_id__isnull=True
        ).exclude(
            scheduled_task_id=''
        )

        cancelled = 0
        for gl in pending:
            if cls.cancel_scheduled(gl):
                cancelled += 1

            def _save():
                gl.scheduled_task_id = None
                gl.homework_status = 'cancelled'
                gl.save(update_fields=[
                    'scheduled_task_id', 'homework_status', 'updated_at'
                ])

            try:
                _db_retry(_save)
            except Exception as e:
                logger.exception(f"GL#{gl.pk} save xatosi: {e}")

        logger.info(
            f"🛑 Guruh {group.name}: {cancelled} ta job bekor qilindi"
        )
        return cancelled

    # ═══════════════════════════════════════════════════════════
    # 6. KURS UCHUN BULK REJALASHTIRISH
    # ═══════════════════════════════════════════════════════════

    @classmethod
    def bulk_schedule_for_course(cls, course, from_date=None):
        """
        Kursning barcha guruhlari uchun kelajakdagi darslarni rejalashtirish.

        ⚠️ `group__is_deleted` ISHLATILMAYDI — `user.StudentGroup` da
        bu maydon yo'q (u `is_active` ishlatadi).
        """
        if from_date is None:
            from_date = timezone.now().date()

        # ⭐ `group__is_deleted` OLIB TASHLANDI
        gls = GroupLesson.objects.filter(
            lesson__course=course,
            lesson_date__gte=from_date,
            homework_status__in=['scheduled', 'pending'],
        ).select_related(
            'lesson', 'lesson__homework',
            'group', 'group__course',
        )

        scheduled = 0
        failed = 0
        skipped = 0

        for gl in gls:
            # Guruh aktivmi? — Python darajasida tekshiramiz
            if getattr(gl.group, 'is_active', True) is False:
                skipped += 1
                continue

            try:
                result = cls.schedule_homework(gl, force=True)
                if result.get('scheduled'):
                    scheduled += 1
                else:
                    skipped += 1
                    logger.debug(
                        f"GL#{gl.pk} skip: {result.get('reason')}"
                    )
            except Exception as e:
                logger.exception(f"GL#{gl.pk} xato: {e}")
                failed += 1

        logger.info(
            f"📊 Bulk schedule [{course.title}]: "
            f"scheduled={scheduled} failed={failed} skipped={skipped}"
        )

        return {
            'scheduled': scheduled,
            'failed': failed,
            'skipped': skipped,
            'total': scheduled + failed + skipped,
        }

    # ═══════════════════════════════════════════════════════════
    # 7. GURUH UCHUN BULK REJALASHTIRISH
    # ═══════════════════════════════════════════════════════════

    @classmethod
    def bulk_schedule_for_group(cls, group, from_date=None):
        """Bitta guruh uchun kelajakdagi darslarni rejalashtirish."""
        if from_date is None:
            from_date = timezone.now().date()

        gls = GroupLesson.objects.filter(
            group=group,
            lesson_date__gte=from_date,
            homework_status__in=['scheduled', 'pending'],
        ).select_related('lesson', 'lesson__homework')

        scheduled = 0
        failed = 0
        skipped = 0

        for gl in gls:
            try:
                result = cls.schedule_homework(gl, force=True)
                if result.get('scheduled'):
                    scheduled += 1
                else:
                    skipped += 1
            except Exception as e:
                logger.exception(f"GL#{gl.pk} xato: {e}")
                failed += 1

        logger.info(
            f"📊 Bulk schedule [{group.name}]: "
            f"scheduled={scheduled} failed={failed} skipped={skipped}"
        )

        return {
            'scheduled': scheduled,
            'failed': failed,
            'skipped': skipped,
            'total': scheduled + failed + skipped,
        }

    # ═══════════════════════════════════════════════════════════
    # 8. VAQTI O'TGANLARNI TOPISH (missed detection)
    # ═══════════════════════════════════════════════════════════

    @classmethod
    def find_missed_homework(cls, minutes_after=3):
        """
        Vaqti o'tgan lekin hali yuborilmagan GroupLesson larni topish.

        ⚠️ `group__is_deleted` ISHLATILMAYDI.
        """
        now = timezone.now()
        threshold = now - timedelta(minutes=minutes_after)
        today = now.date()

        # ⭐ `group__is_deleted` OLIB TASHLANDI
        candidates = GroupLesson.objects.filter(
            homework_status='scheduled',
            lesson_date__lte=today,
        ).select_related(
            'lesson', 'lesson__homework', 'group'
        )

        missed = []
        for gl in candidates:
            # Guruh aktivmi? — Python darajasida tekshiramiz
            if getattr(gl.group, 'is_active', True) is False:
                continue

            eta = cls.calculate_eta(gl)
            if eta and eta < threshold:
                missed.append(gl)

        logger.info(f"🔍 Missed homework topildi: {len(missed)} ta")
        return missed

    @classmethod
    def trigger_missed_homework(cls, minutes_after=3):
        """Vaqti o'tgan lekin yuborilmaganlarni DARHOL yuborish."""
        from apps.courses.tasks import send_homework_to_group_job

        missed = cls.find_missed_homework(minutes_after=minutes_after)

        triggered = 0
        for gl in missed:
            try:
                logger.warning(
                    f"⚠️ GL#{gl.pk} vaqti o'tgan — zaxira yuborish"
                )
                send_homework_to_group_job(gl.pk)
                triggered += 1
            except Exception as e:
                logger.exception(f"Zaxira yuborishda xato (GL#{gl.pk}): {e}")

        return triggered

    # ═══════════════════════════════════════════════════════════
    # 9. STATISTIKA VA DEBUG
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def get_scheduler_stats():
        """APScheduler statistikasi."""
        scheduler = _get_scheduler()
        if not scheduler:
            return {'error': 'no_scheduler'}

        try:
            jobs = scheduler.get_jobs()
            hw_jobs = [j for j in jobs if j.id.startswith(JOB_ID_PREFIX)]

            return {
                'total_jobs': len(jobs),
                'homework_jobs': len(hw_jobs),
                'running': scheduler.running,
                'state': str(scheduler.state) if scheduler.running else 'stopped',
                'jobs': [
                    {
                        'id': j.id,
                        'name': j.name,
                        'next_run': (
                            j.next_run_time.isoformat()
                            if j.next_run_time else None
                        ),
                    }
                    for j in hw_jobs[:20]
                ],
            }
        except Exception as e:
            logger.exception(f"Stats xatosi: {e}")
            return {'error': str(e)}

    @classmethod
    def get_gl_info(cls, group_lesson):
        """Bitta GroupLesson haqida to'liq ma'lumot."""
        eta = cls.calculate_eta(group_lesson)
        now = timezone.now()

        scheduler = _get_scheduler()
        job_info = None
        if scheduler and group_lesson.scheduled_task_id:
            try:
                job = scheduler.get_job(group_lesson.scheduled_task_id)
                if job:
                    job_info = {
                        'id': job.id,
                        'name': job.name,
                        'next_run': (
                            job.next_run_time.isoformat()
                            if job.next_run_time else None
                        ),
                    }
            except Exception:
                pass

        return {
            'gl_id': group_lesson.pk,
            'group': group_lesson.group.name,
            'lesson': str(group_lesson.lesson),
            'lesson_date': (
                group_lesson.lesson_date.isoformat()
                if group_lesson.lesson_date else None
            ),
            'schedule': group_lesson.group.schedule,
            'status': group_lesson.homework_status,
            'scheduled_task_id': group_lesson.scheduled_task_id,
            'eta': eta.isoformat() if eta else None,
            'now': now.isoformat(),
            'is_past': bool(eta and eta < now),
            'time_until_eta': (
                str(eta - now) if eta and eta > now else None
            ),
            'job': job_info,
        }

    # ═══════════════════════════════════════════════════════════
    # 10. TOZALASH (cleanup)
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def cleanup_old_jobs():
        """O'tib ketgan va cancelled bo'lgan joblarni tozalash."""
        scheduler = _get_scheduler()
        if not scheduler:
            return 0

        now = timezone.now()
        removed = 0

        try:
            for job in scheduler.get_jobs():
                if not job.id.startswith(JOB_ID_PREFIX):
                    continue
                if job.next_run_time and job.next_run_time < now - timedelta(days=1):
                    scheduler.remove_job(job.id)
                    removed += 1
        except Exception as e:
            logger.exception(f"Cleanup xatosi: {e}")

        logger.info(f"🧹 Cleanup: {removed} ta eski job o'chirildi")
        return removed

    # ═══════════════════════════════════════════════════════════
    # 11. VALIDATSIYA
    # ═══════════════════════════════════════════════════════════

    @classmethod
    def validate_schedule(cls, group_lesson):
        """GroupLesson ni rejalashtirish uchun tayyorligini tekshirish."""
        errors = []
        warnings = []

        if not group_lesson.lesson_date:
            errors.append("lesson_date yo'q")

        homework = getattr(group_lesson.lesson, 'homework', None)
        if not homework:
            errors.append("Homework yo'q")
        elif not homework.is_approved:
            errors.append("Homework tasdiqlanmagan")

        schedule = group_lesson.group.schedule or {}
        if not schedule:
            errors.append("Guruh jadvali bo'sh")

        eta = cls.calculate_eta(group_lesson)
        if not eta:
            errors.append("ETA hisoblanmadi")
        else:
            now = timezone.now()
            if eta < now - timedelta(hours=1):
                warnings.append(
                    f"ETA juda eski: {eta.isoformat()} "
                    f"({(now - eta).total_seconds() / 60:.0f} daqiqa o'tgan)"
                )

        if group_lesson.homework_status in ('sent', 'sending'):
            warnings.append(
                f"Allaqachon yuborilgan: {group_lesson.homework_status}"
            )

        if not _get_scheduler():
            errors.append("APScheduler mavjud emas")

        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings,
            'eta': eta,
        }