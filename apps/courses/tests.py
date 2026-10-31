from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.service.homework_scheduler import HomeworkScheduler

from .tasks import send_homework_to_group_job


class HomeworkManualDeliveryTests(SimpleTestCase):
    def test_scheduler_does_not_create_jobs(self):
        result = HomeworkScheduler.schedule_homework(
            SimpleNamespace(pk=1)
        )

        self.assertEqual(result, {'scheduled': False, 'reason': 'manual_only'})

    def test_scheduled_delivery_is_rejected(self):
        result = send_homework_to_group_job(group_lesson_id=1)

        self.assertEqual(result, {'ok': False, 'reason': 'manual_only'})
