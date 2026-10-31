# config/scheduler.py
"""
APScheduler — avtomatik vazifalar.
================================================
XUSUSIYATLAR:
- Faol bo'lmagan foydalanuvchilarni tekshirish (har 30 daqiqada)
- Morning boost (har kuni 07:00)
- Eski loglarni tozalash (har dushanba 03:00)
- Uyga vazifa job cleanup (har kuni 02:00)
- Deadline detection (har 15 daqiqada)
"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from django_apscheduler.jobstores import DjangoJobStore
from django_apscheduler.models import DjangoJobExecution
from django_apscheduler import util

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# GLOBAL SCHEDULER INSTANSIYASI
# ═══════════════════════════════════════════════════════════════

_scheduler = None


def get_scheduler():
    """Global scheduler instance ni qaytarish."""
    global _scheduler
    return _scheduler


# ═══════════════════════════════════════════════════════════════
# 1. MAVJUD JOBLAR
# ═══════════════════════════════════════════════════════════════

def check_inactive_job():
    """Faol bo'lmaganlarni tekshirish."""
    from django.core.management import call_command
    try:
        call_command('check_inactive')
        logger.info("✅ check_inactive ishga tushdi")
    except Exception as e:
        logger.exception(f"❌ check_inactive xato: {e}")


def morning_boost_job():
    """Ertalab 07:00 da xabar."""
    from apps.service.notification_service import send_morning_boost
    try:
        result = send_morning_boost()
        logger.info(f"🌅 Morning boost: {result}")
    except Exception as e:
        logger.exception(f"❌ Morning xato: {e}")


@util.close_old_connections
def delete_old_jobs(max_age=604_800):
    """Eski loglarni o'chirish (1 haftadan eski)."""
    DjangoJobExecution.objects.delete_old_job_executions(max_age)


# ═══════════════════════════════════════════════════════════════
# 2. UYGA VAZIFA ESKI JOBLARINI TOZALASH
# ═══════════════════════════════════════════════════════════════

@util.close_old_connections
def cleanup_homework_jobs():
    """O'tib ketgan joblarni tozalash (02:00)."""
    try:
        from apps.service.homework_scheduler import HomeworkScheduler
        removed = HomeworkScheduler.cleanup_old_jobs()
        logger.info(f"🧹 Homework cleanup: {removed} ta o'chirildi")
    except Exception as e:
        logger.exception(f"❌ cleanup_homework_jobs xato: {e}")


@util.close_old_connections
def detect_missed_deadlines_job():
    """Deadline o'tganlarni aniqlash (har 15 daqiqada)."""
    logger.debug("⏰ Deadline detection ishga tushdi")


# ═══════════════════════════════════════════════════════════════
# 3. SCHEDULER ISHGA TUSHIRISH
# ═══════════════════════════════════════════════════════════════

def start():
    """Scheduler ishga tushirish."""
    global _scheduler
    if _scheduler is not None:
        logger.warning("⚠️ Scheduler allaqachon ishga tushgan")
        return

    _scheduler = BackgroundScheduler(timezone='Asia/Tashkent')
    _scheduler.add_jobstore(DjangoJobStore(), "default")

    # JOB 1: Har 30 daqiqada — faol bo'lmaganlar
    _scheduler.add_job(
        check_inactive_job,
        trigger=CronTrigger(minute='*/30'),
        id="check_inactive_job",
        max_instances=1,
        replace_existing=True,
        name="Faol bo'lmagan foydalanuvchilar",
    )
    logger.info("✅ Job qo'shildi: check_inactive_job (har 30 daqiqada)")

    # JOB 2: Har kuni 07:00 — morning boost
    _scheduler.add_job(
        morning_boost_job,
        trigger=CronTrigger(hour=7, minute=0),
        id="morning_boost_job",
        max_instances=1,
        replace_existing=True,
        name="Ertalabki xabar",
    )
    logger.info("✅ Job qo'shildi: morning_boost_job (07:00)")

    # JOB 3: Har dushanba 03:00 — eski loglarni tozalash
    _scheduler.add_job(
        delete_old_jobs,
        trigger=CronTrigger(day_of_week="mon", hour=3, minute=0),
        id="delete_old_jobs",
        max_instances=1,
        replace_existing=True,
        name="Eski loglarni tozalash",
    )
    logger.info("✅ Job qo'shildi: delete_old_jobs (dushanba 03:00)")

    # JOB 4: Har kuni 02:00 — homework job cleanup
    _scheduler.add_job(
        cleanup_homework_jobs,
        trigger=CronTrigger(hour=2, minute=0),
        id="cleanup_homework_jobs",
        max_instances=1,
        replace_existing=True,
        name="Homework joblarni tozalash",
    )
    logger.info("✅ Job qo'shildi: cleanup_homework_jobs (02:00)")

    # JOB 5: Har 15 daqiqada — deadline detection
    _scheduler.add_job(
        detect_missed_deadlines_job,
        trigger=CronTrigger(minute='*/15'),
        id="detect_missed_deadlines_job",
        max_instances=1,
        replace_existing=True,
        name="Deadline detection",
    )
    logger.info("✅ Job qo'shildi: detect_missed_deadlines_job (har 15 daqiqada)")

    # ═══ ISHGA TUSHIRISH ═══
    try:
        _scheduler.start()
        logger.info("🚀 APScheduler ishga tushdi!")
        for job in _scheduler.get_jobs():
            if job.id.startswith('hw_gl_'):
                _scheduler.remove_job(job.id)
                logger.info(f"🛑 Eski avtomatik homework job o'chirildi: {job.id}")
        logger.info(f"📊 Jami joblar: {len(_scheduler.get_jobs())}")
    except Exception as e:
        logger.exception(f"❌ Scheduler xatosi: {e}")


def stop():
    """Scheduler to'xtatish (test uchun)."""
    global _scheduler
    if _scheduler and _scheduler.running:
        try:
            _scheduler.shutdown(wait=False)
            logger.info("🛑 APScheduler to'xtatildi")
        except Exception as e:
            logger.exception(f"Stop xatosi: {e}")
    _scheduler = None