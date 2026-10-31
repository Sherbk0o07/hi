# apps/courses/apps.py
"""
Courses App Config.
===================
Scheduler'ni birinchi so'rovda ishga tushiradi.
"""
from django.apps import AppConfig


class CoursesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.courses'
    verbose_name = "Kurslar"

    def ready(self):
        """
        Signal ulash — birinchi HTTP so'rovda scheduler ishga tushadi.
        """
        import sys
        import logging

        logger = logging.getLogger(__name__)

        # Faqat runserver paytida
        if 'runserver' not in sys.argv:
            return

        # Signal ulash
        from django.core.signals import request_started
        from django.dispatch import receiver

        @receiver(
            request_started,
            dispatch_uid="courses_start_scheduler_once",
        )
        def _start_scheduler_once(sender, **kwargs):
            """Birinchi HTTP so'rovda scheduler ishga tushadi."""
            try:
                from config import scheduler as sched_module

                # Allaqachon ishga tushganmi?
                if getattr(sched_module, '_scheduler', None) is not None:
                    return

                # `start` funksiyasi mavjudmi?
                if not hasattr(sched_module, 'start'):
                    logger.error(
                        "❌ config.scheduler'da `start` funksiyasi yo'q!"
                    )
                    return

                # Ishga tushirish
                sched_module.start()
                logger.warning("✅ Scheduler birinchi so'rovda ishga tushdi")

            except Exception as e:
                logger.exception(f"❌ Scheduler start xatosi: {e}")

        logger.warning(
            "✅ Courses app: `request_started` signal ulandi"
        )