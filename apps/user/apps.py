from django.apps import AppConfig
import os
import sys


class UserConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.user'
    verbose_name = "Foydalanuvchilar"

    def ready(self):
        """Scheduler ni ishga tushirish."""
        # Faqat runserver da
        if 'runserver' not in sys.argv:
            return
        # Reloader ikki marta ishga tushmasligi uchun
        if os.environ.get('RUN_MAIN') != 'true':
            return

        try:
            from . import scheduler
            scheduler.start()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Scheduler xato: {e}")