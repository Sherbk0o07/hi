# apps/courses/signals.py
"""
Kurslar moduli signallari.

1. distribute_lessons_to_group — guruhga darslarni taqsimlash
2. cancel_on_delete — soft-delete/restore holatini yangilash
"""
import logging
from datetime import timedelta

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from .models import Lesson, StudentGroup, GroupLesson

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# YORDAMCHI
# ═══════════════════════════════════════════════════════════════

WEEKDAY_MAP = {
    'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
    'friday': 4, 'saturday': 5, 'sunday': 6,
}


def get_next_date(start_date, weekday_name, week_offset=0):
    """Berilgan haftadan keyingi shu kunni topish."""
    target = WEEKDAY_MAP[weekday_name]
    current = start_date.weekday()
    days_ahead = (target - current) % 7
    return start_date + timedelta(days=days_ahead + week_offset * 7)


def distribute_lessons_to_group(group):
    """Guruhga barcha kurs darslarini avtomatik taqsimlash."""
    if not group.course_id:
        return 0

    start = group.lessons_start_date or group.start_date or timezone.now().date()

    lessons = Lesson.objects.filter(
        course=group.course, is_deleted=False
    ).order_by('lesson_number')

    if not lessons.exists():
        return 0

    # Schedule dan kunlarni olish
    schedule = group.schedule or {}
    days = sorted(schedule.keys(), key=lambda d: WEEKDAY_MAP.get(d, 99))
    if not days:
        return 0

    # Eski assignmentlarni tozalash (faqat yangi assignment uchun)
    GroupLesson.objects.filter(group=group).delete()

    created = 0
    for idx, lesson in enumerate(lessons):
        week_offset = idx // len(days)
        day_name = days[idx % len(days)]
        lesson_date = get_next_date(start, day_name, week_offset)

        GroupLesson.objects.create(
            group=group,
            lesson=lesson,
            lesson_date=lesson_date,
            order_in_group=idx + 1,
        )
        created += 1

    return created


# ═══════════════════════════════════════════════════════════════
# 1. GURUH YARATILGANDA → DARSLARNI TAQSIMLASH
# ═══════════════════════════════════════════════════════════════

@receiver(post_save, sender=StudentGroup)
def auto_distribute_on_group_save(sender, instance, created, **kwargs):
    """Guruh yaratilganda darslarni taqsimlash."""
    if created and instance.course_id:
        try:
            distribute_lessons_to_group(instance)
        except Exception as e:
            logger.exception(f"Auto-distribute xatosi ({instance.pk}): {e}")


# ═══════════════════════════════════════════════════════════════
# 2. YANGI DARS → BARCHA GURUHLARGA TARQATISH
# ═══════════════════════════════════════════════════════════════

@receiver(post_save, sender=Lesson)
def auto_add_lesson_to_groups(sender, instance, created, **kwargs):
    """Yangi dars qo'shilsa — kursning barcha guruhlariga tarqatish."""
    if not created:
        return

    groups = StudentGroup.objects.filter(
        course=instance.course, is_deleted=False
    )
    for group in groups:
        try:
            distribute_lessons_to_group(group)
        except Exception as e:
            logger.exception(f"Auto-add xatosi ({group.pk}): {e}")


# ═══════════════════════════════════════════════════════════════
# 3. SOFT-DELETE / RESTORE → YUBORISH HOLATINI YANGILASH
# ═══════════════════════════════════════════════════════════════

@receiver(pre_save, sender=GroupLesson)
def cancel_on_delete(sender, instance, **kwargs):
    """
    GroupLesson soft-delete/restore da yuborish holatini yangilash.
    """
    if not instance.pk:
        return

    try:
        old = GroupLesson.objects.get(pk=instance.pk)
    except GroupLesson.DoesNotExist:
        return

    # ═══ A) SOFT-DELETE: False → True ═══
    if not old.is_deleted and instance.is_deleted:
        instance.scheduled_task_id = None
        instance.homework_status = 'cancelled'

    # ═══ B) RESTORE: True → False ═══
    elif old.is_deleted and not instance.is_deleted:
        if instance.homework_status == 'cancelled':
            instance.homework_status = 'pending'
            instance.scheduled_task_id = None
            logger.info(f"♻️ GL#{instance.pk} — qo'lda yuborishga tayyor")