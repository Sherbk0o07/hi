# apps/courses/services/stats_service.py
"""
Kurslar statistikasi.
"""
from datetime import timedelta
from django.db.models import Count, Avg
from django.utils import timezone

from apps.courses.models import Course, Enrollment, Lesson


class CourseStatsService:

    @staticmethod
    def get_monthly_stats():
        """Oylik statistika."""
        today = timezone.now().date()
        months = []
        labels = []

        for i in range(5, -1, -1):
            # Oy boshlanishi
            first_day = (today.replace(day=1) - timedelta(days=i * 30))
            month_start = first_day.replace(day=1)

            # Oy tugashi
            if month_start.month == 12:
                next_month = month_start.replace(year=month_start.year + 1, month=1)
            else:
                next_month = month_start.replace(month=month_start.month + 1)

            count = Course.objects.filter(
                created_at__gte=month_start,
                created_at__lt=next_month,
            ).count()

            months.append(count)
            labels.append(month_start.strftime('%b'))

        return {'labels': labels, 'data': months}

    @staticmethod
    def get_top_categories(limit=5):
        """Top kategoriyalar."""
        return list(
            Course.objects
            .filter(is_deleted=False, category__isnull=False)
            .values('category__name')
            .annotate(count=Count('id'))
            .order_by('-count')[:limit]
        )

    @staticmethod
    def get_top_teachers(limit=5):
        """Top o'qituvchilar."""
        return list(
            Course.objects
            .filter(is_deleted=False, teacher__isnull=False)
            .values('teacher__first_name', 'teacher__last_name')
            .annotate(
                count=Count('id'),
                avg_rating=Avg('rating')
            )
            .order_by('-count')[:limit]
        )