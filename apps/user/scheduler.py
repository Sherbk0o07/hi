"""
APScheduler — avtomatik xabar yuborish.
"""
import logging
import os
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from django_apscheduler.jobstores import DjangoJobStore
from django_apscheduler.models import DjangoJobExecution
from django_apscheduler import util

logger = logging.getLogger(__name__)
_scheduler = None


def check_inactive_job():
    """Faol bo‘lmaganlarni tekshirish."""
    from django.core.management import call_command
    try:
        call_command('check_inactive')
        logger.info("✅ check_inactive ishga tushdi")
    except Exception as e:
        logger.exception(f"❌ check_inactive xato: {e}")


def morning_boost_job():
    """Ertalab 07:00 da xabar."""
    from apps.services.notification_service import send_morning_boost
    try:
        result = send_morning_boost()
        logger.info(f"🌅 Morning boost: {result}")
    except Exception as e:
        logger.exception(f"❌ Morning xato: {e}")


@util.close_old_connections
def delete_old_jobs(max_age=604_800):
    """Eski loglarni o‘chirish."""
    DjangoJobExecution.objects.delete_old_job_executions(max_age)


def start():
    """Scheduler ishga tushirish."""
    global _scheduler
    if _scheduler is not None:
        return

    # Faqat asosiy processda (reloader ikki marta ishga tushmasligi uchun)
    if os.environ.get('RUN_MAIN') != 'true' and not os.environ.get('DJANGO_ALLOW_ASYNC_UNSAFE'):
        pass  # Production uchun

    _scheduler = BackgroundScheduler(timezone='Asia/Tashkent')
    _scheduler.add_jobstore(DjangoJobStore(), "default")

    # ═══ Har 30 daqiqada ═══
    _scheduler.add_job(
        check_inactive_job,
        trigger=CronTrigger(minute='*/30'),
        id="check_inactive_job",
        max_instances=1,
        replace_existing=True,
        name="Faol bo‘lmagan foydalanuvchilar",
    )
    logger.info("✅ Job: check_inactive (har 30 daqiqada)")

    # ═══ Har kuni 07:00 ═══
    _scheduler.add_job(
        morning_boost_job,
        trigger=CronTrigger(hour=7, minute=0),
        id="morning_boost_job",
        max_instances=1,
        replace_existing=True,
        name="Ertalabki xabar",
    )
    logger.info("✅ Job: morning_boost (07:00)")

    # ═══ Dushanba 03:00 ═══
    _scheduler.add_job(
        delete_old_jobs,
        trigger=CronTrigger(day_of_week="mon", hour=3, minute=0),
        id="delete_old_jobs",
        max_instances=1,
        replace_existing=True,
        name="Eski loglarni tozalash",
    )
    logger.info("✅ Job: cleanup (dushanba 03:00)")

    try:
        _scheduler.start()
        logger.info("🚀 APScheduler ishga tushdi!")
    except Exception as e:
        logger.exception(f"❌ Scheduler xato: {e}")