# apps/pages/views/homework.py
"""
Talaba uchun uyga vazifa view'lari — TO'LIQ BACKEND.
BARCHA MA'LUMOT SHU FAYLDA TAYYORLANADI.
"""
import logging
import random
from datetime import timedelta, date
from collections import defaultdict

from django.conf import settings
from django.db.models import Count, Sum, Avg, Q, F, Case, When, Value, IntegerField
from django.db.models.functions import Coalesce, TruncDate, TruncMonth
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views import View

from apps.courses.models import (
    Homework, HomeworkSubmission, GroupLesson, SubmissionStatus,
    Quiz, QuizAttempt, Attendance,
)
from apps.user.models import StudentProfile, Notification
from apps.service.telegram_webapp_auth import auto_login_from_request

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# KONSTANTALAR
# ═══════════════════════════════════════════════════════════════
MIN_FILE_SIZE_KB = 5
MAX_FILE_SIZE_MB = 100
MIN_TEXT_LENGTH = 20
DAILY_GOAL = 5
POMODORO_DEFAULT = 25

MOTIVATIONS = [
    "Kichik qadamlar katta natijalarga olib keladi.",
    "Bugun qilgan harakatlaringiz ertangi muvaffaqiyatingizdir.",
    "Muvaffaqiyat — bu kichik qadamlar yig'indisi.",
    "Har kuni 1% yaxshilanish — bir yilda 37x o'sish.",
    "Harakat qil, chunki sen buni qila olasan!",
    "Sen bugun kechagi sendan yaxshiroq bo'lishing mumkin.",
    "Mukammallik emas, izchillik muhim.",
    "Dangasalik — bugun, muvaffaqiyat — ertaga.",
    "Bugun boshlash — ertaga g'alaba qozonish.",
    "O'rganish — bu sarmoya, hech qachon yo'qolmaydi.",
    "Bilim — kuch, uni to'plashda davom eting.",
    "Har bir urinish — yangi imkoniyat.",
    "Sen kuchlisan, buni unutma!",
    "Vaqt — eng qimmatli resurs. Uni bekorga sarflamang.",
    "Bugun o'rgangan narsang ertaga seni yaxshiroq qiladi.",
]

FUN_FACTS = [
    "Miyangiz o'rganish uchun 20% kislorod ishlatadi.",
    "Har kuni 30 daqiqa o'qish 1 yilda 30+ kitob demakdir.",
    "Sizning miyangiz 86 milliard neyronni o'z ichiga oladi.",
    "Yangi narsa o'rganish miyani yosharttiradi.",
    "Uyqu paytida miya o'rganganlarini mustahkamlaydi.",
    "Kofe emas, suv miya uchun eng yaxshi ichimlik.",
    "Jismoniy mashq miya faoliyatini 20% yaxshilaydi.",
    "Musiqa tinglash matematik qobiliyatni oshiradi.",
    "Sizning miyangiz kunduzi 70,000 ta fikr ishlab chiqaradi.",
    "O'rganish davomida miya yangi neyron aloqalarini yaratadi.",
]

MOOD_OPTIONS = [
    {'key': 'great', 'emoji': '😄', 'label': 'Ajoyib', 'color': 'green'},
    {'key': 'good', 'emoji': '🙂', 'label': 'Yaxshi', 'color': 'blue'},
    {'key': 'ok', 'emoji': '😐', 'label': "O'rtacha", 'color': 'amber'},
    {'key': 'bad', 'emoji': '😔', 'label': 'Yomon', 'color': 'orange'},
    {'key': 'awful', 'emoji': '😢', 'label': 'Juda yomon', 'color': 'rose'},
]

TRUST_BADGES = [
    {'icon': 'shield-check', 'text': 'Xavfsiz', 'color': 'green'},
    {'icon': 'lock', 'text': 'Maxfiy', 'color': 'blue'},
    {'icon': 'clock', 'text': '24/7', 'color': 'amber'},
    {'icon': 'zap', 'text': 'Tez', 'color': 'purple'},
]

TIPS = [
    {'icon': 'keyboard', 'title': '⌘K bilan qidirish', 'subtitle': "Tez qidiruv ishlatib ko'ring", 'color': 'primary'},
    {'icon': 'target', 'title': f'Kunlik maqsad: {DAILY_GOAL} ta', 'subtitle': 'Har kuni maqsadga erishing', 'color': 'green'},
    {'icon': 'brain', 'title': f'Pomodoro: {POMODORO_DEFAULT} daqiqa', 'subtitle': 'Diqqatni oshiring', 'color': 'amber'},
]

QUICK_ACTIONS = [
    {'id': 'tasks', 'icon': 'list-todo', 'label': 'Vazifalar', 'color': 'primary'},
    {'id': 'pomodoro', 'icon': 'timer', 'label': 'Pomodoro', 'color': 'rose'},
    {'id': 'note', 'icon': 'notebook-pen', 'label': 'Izoh', 'color': 'amber'},
    {'id': 'ai', 'icon': 'sparkles', 'label': 'AI', 'color': 'fuchsia'},
    {'id': 'calendar', 'icon': 'calendar', 'label': 'Kalendar', 'color': 'cyan'},
    {'id': 'leaderboard', 'icon': 'crown', 'label': 'Reyting', 'color': 'yellow'},
]

# ═══════════════════════════════════════════════════════════════
# YORDAMCHI FUNKSIYALAR (30+)
# ═══════════════════════════════════════════════════════════════

def get_greeting_by_hour():
    hour = timezone.localtime().hour
    if 5 <= hour < 12:
        return {'emoji': '🌅', 'text': 'Xayrli tong', 'sub': 'Yangi kun yangi imkoniyatlar'}
    elif 12 <= hour < 17:
        return {'emoji': '☀️', 'text': 'Xayrli kun', 'sub': 'Kunning eng faol qismi'}
    elif 17 <= hour < 21:
        return {'emoji': '🌆', 'text': 'Xayrli oqshom', 'sub': 'Kunning yakuniy qismi'}
    return {'emoji': '🌙', 'text': 'Xayrli tun', 'sub': 'Tinch dam oling'}


def get_student_streak(student):
    try:
        thirty_days_ago = timezone.now() - timedelta(days=30)
        submissions = (
            HomeworkSubmission.objects
            .filter(student=student, submitted_at__gte=thirty_days_ago)
            .annotate(day=TruncDate('submitted_at'))
            .values_list('day', flat=True)
            .distinct()
        )
        submission_days = set(submissions)
        if not submission_days:
            return 0
        streak = 0
        today = timezone.now().date()
        for i in range(30):
            day = today - timedelta(days=i)
            if day in submission_days:
                streak += 1
            else:
                if i == 0:
                    continue
                break
        return streak
    except Exception as e:
        logger.exception(f"Streak: {e}")
        return 0


def _get_level_title(level):
    titles = {
        1: 'Yangi boshlovchi', 2: "O'rganuvchi", 3: "Faol o'quvchi",
        4: 'Bilimdon', 5: 'Tajribali', 6: 'Ustoz',
        7: 'Professional', 8: 'Ekspert', 9: 'Master', 10: 'Legend',
    }
    return titles.get(min(level, 10), 'Legend')


def get_student_level(student):
    try:
        total_xp = HomeworkSubmission.objects.filter(student=student).aggregate(
            total=Coalesce(Sum('xp_awarded'), 0)
        )['total']
        level = max(1, total_xp // 100)
        current_level_xp = (level - 1) * 100
        next_level_xp = level * 100
        xp_in_level = total_xp - current_level_xp
        xp_needed = next_level_xp - total_xp
        progress_percent = round((xp_in_level / 100) * 100, 1)
        return {
            'level': level, 'total_xp': total_xp, 'xp_in_level': xp_in_level,
            'xp_needed': xp_needed, 'progress_percent': progress_percent,
            'title': _get_level_title(level),
            'next_title': _get_level_title(level + 1),
        }
    except Exception as e:
        logger.exception(f"Level: {e}")
        return {'level': 1, 'total_xp': 0, 'xp_in_level': 0, 'xp_needed': 100,
                'progress_percent': 0, 'title': 'Yangi boshlovchi', 'next_title': "O'rganuvchi"}


def get_weekly_activity(student):
    try:
        today = timezone.now().date()
        day_labels = ['Du', 'Se', 'Ch', 'Pa', 'Ju', 'Sha', 'Ya']
        days_data = [today - timedelta(days=i) for i in range(6, -1, -1)]
        submissions = (
            HomeworkSubmission.objects
            .filter(student=student, submitted_at__date__in=days_data)
            .annotate(day=TruncDate('submitted_at'))
            .values('day').annotate(count=Count('id'))
        )
        count_map = {item['day']: item['count'] for item in submissions}
        max_count = max(count_map.values()) if count_map else 1
        result = []
        for day in days_data:
            count = count_map.get(day, 0)
            value = round((count / max_count) * 100) if max_count > 0 else 0
            result.append({
                'date': day, 'label': day_labels[day.weekday()], 'count': count,
                'value': max(value, 4), 'is_today': day == today, 'day_number': day.day,
            })
        return result
    except Exception as e:
        logger.exception(f"Weekly: {e}")
        return []


def get_monthly_activity(student):
    try:
        today = timezone.now().date()
        first_day = today.replace(day=1)
        submissions = (
            HomeworkSubmission.objects
            .filter(student=student, submitted_at__date__gte=first_day)
            .annotate(day=TruncDate('submitted_at'))
            .values('day').annotate(count=Count('id'))
        )
        count_map = {item['day']: item['count'] for item in submissions}
        days = []
        for i in range((today - first_day).days + 1):
            day = first_day + timedelta(days=i)
            days.append({
                'day': day.day, 'count': count_map.get(day, 0),
                'is_today': day == today,
            })
        return days
    except Exception as e:
        logger.exception(f"Monthly: {e}")
        return []


def get_urgent_count(student):
    try:
        today = timezone.now().date()
        tomorrow = today + timedelta(days=1)
        urgent_lessons = (
            GroupLesson.objects
            .filter(group__students=student, lesson_date__in=[today, tomorrow],
                    lesson__homework__isnull=False)
            .distinct()
        )
        count = 0
        for gl in urgent_lessons:
            hw = getattr(gl.lesson, 'homework', None)
            if not hw:
                continue
            submitted = HomeworkSubmission.objects.filter(
                homework=hw, student=student, is_latest=True
            ).exists()
            if not submitted:
                count += 1
        return count
    except Exception as e:
        logger.exception(f"Urgent: {e}")
        return 0


def get_daily_quests(stats, streak):
    return [
        {
            'title': f'{DAILY_GOAL} ta vazifa bajarish',
            'description': f"Bugun {stats['completed']}/{DAILY_GOAL} bajarildi",
            'icon': 'check-circle', 'color': 'green', 'reward': 15,
            'completed': stats['completed'] >= DAILY_GOAL,
        },
        {
            'title': 'Yangi darsni ochish',
            'description': "Kamida 1 yangi darsni boshlang",
            'icon': 'book-open', 'color': 'primary', 'reward': 10,
            'completed': stats['completed'] >= 1,
        },
        {
            'title': "Barcha vazifalarni ko'rish",
            'description': "Hammani ko'rib chiqing",
            'icon': 'eye', 'color': 'purple', 'reward': 5,
            'completed': stats['total'] > 0,
        },
        {
            'title': 'Pomodoro ishlatish',
            'description': f"{POMODORO_DEFAULT} daqiqa fokus",
            'icon': 'timer', 'color': 'rose', 'reward': 20,
            'completed': False,
        },
        {
            'title': 'Streak saqlash',
            'description': f"Ketma-ket {streak} kun faol",
            'icon': 'flame', 'color': 'orange', 'reward': 25,
            'completed': streak > 0,
        },
    ]


def get_upcoming_deadlines(student):
    try:
        today = timezone.now().date()
        three_days = today + timedelta(days=3)
        items = []
        gls = (
            GroupLesson.objects
            .filter(group__students=student, lesson_date__gte=today,
                    lesson_date__lte=three_days, lesson__homework__isnull=False)
            .select_related('lesson', 'lesson__homework', 'lesson__course')
            .order_by('lesson_date')[:5]
        )
        for gl in gls:
            hw = getattr(gl.lesson, 'homework', None)
            if not hw:
                continue
            if HomeworkSubmission.objects.filter(
                homework=hw, student=student, is_latest=True
            ).exists():
                continue
            deadline = hw.get_deadline(student)
            if not deadline:
                continue
            hours_left = max(0, int((deadline - timezone.now()).total_seconds() / 3600))
            items.append({
                'id': hw.pk, 'title': hw.title, 'course': gl.lesson.course.title,
                'deadline_relative': f"{hours_left} soat qoldi",
                'hours_left': hours_left,
            })
        return items
    except Exception as e:
        logger.exception(f"Upcoming: {e}")
        return []


def get_recent_activity(student):
    try:
        submissions = (
            HomeworkSubmission.objects
            .filter(student=student).select_related('homework')
            .order_by('-submitted_at')[:5]
        )
        result = []
        for sub in submissions:
            diff = timezone.now() - sub.submitted_at
            if diff.days > 0:
                time_ago = f"{diff.days} kun oldin"
            elif diff.seconds > 3600:
                time_ago = f"{diff.seconds // 3600} soat oldin"
            else:
                time_ago = f"{diff.seconds // 60} daqiqa oldin"
            result.append({
                'icon': 'upload', 'color': 'primary',
                'text': f"'{sub.homework.title}' topshirildi",
                'time_ago': time_ago,
            })
        return result
    except Exception as e:
        logger.exception(f"Recent: {e}")
        return []


def get_skills(student):
    """Ko'nikmalar — topshirilgan vazifalar asosida."""
    try:
        skills = []
        courses = (
            HomeworkSubmission.objects
            .filter(student=student, score__isnull=False)
            .values('homework__lesson__course__title')
            .annotate(avg_score=Avg('score'), count=Count('id'))
            .order_by('-count')[:5]
        )
        colors = ['primary', 'amber', 'cyan', 'rose', 'purple']
        for idx, c in enumerate(courses):
            title = c['homework__lesson__course__title'] or 'Kurs'
            avg = c['avg_score'] or 0
            level = min(10, max(1, int(avg / 10)))
            skills.append({
                'name': title[:20], 'level': level,
                'progress': round(avg, 1),
                'color': colors[idx % len(colors)],
            })
        return skills if skills else [
            {'name': 'Python', 'level': 1, 'progress': 0, 'color': 'primary'},
        ]
    except Exception as e:
        logger.exception(f"Skills: {e}")
        return []


def get_achievements(student, streak, level):
    """Yutuqlar — haqiqiy statistikaga asosida."""
    try:
        total_subs = HomeworkSubmission.objects.filter(student=student).count()
        graded = HomeworkSubmission.objects.filter(
            student=student, score__isnull=False
        )
        perfect = graded.filter(score__gte=90).count()

        return [
            {'emoji': '🥇', 'title': 'Birinchi qadam', 'unlocked': total_subs >= 1,
             'description': '1 ta vazifa topshiring'},
            {'emoji': '🎯', 'title': 'Maqsadli', 'unlocked': total_subs >= 5,
             'description': '5 ta vazifa topshiring'},
            {'emoji': '⭐', 'title': 'Yulduz', 'unlocked': perfect >= 1,
             'description': '90+ ball oling'},
            {'emoji': '🔥', 'title': '7 kun streak', 'unlocked': streak >= 7,
             'description': '7 kun ketma-ket faol bo\'ling'},
            {'emoji': '💎', 'title': 'Olmos', 'unlocked': perfect >= 5,
             'description': '5 marta 90+ ball oling'},
            {'emoji': '⚡', 'title': 'Tezkor', 'unlocked': total_subs >= 20,
             'description': '20 ta vazifa topshiring'},
            {'emoji': '🌟', 'title': 'Porloq', 'unlocked': level['level'] >= 5,
             'description': 'Level 5 ga yeting'},
            {'emoji': '🏅', 'title': 'Chempion', 'unlocked': level['level'] >= 10,
             'description': 'Level 10 ga yeting'},
            {'emoji': '🎖️', 'title': 'Medal', 'unlocked': total_subs >= 50,
             'description': '50 ta vazifa topshiring'},
            {'emoji': '👑', 'title': 'Qirol', 'unlocked': level['level'] >= 15,
             'description': 'Level 15 ga yeting'},
            {'emoji': '🚀', 'title': 'Raketa', 'unlocked': streak >= 30,
             'description': '30 kun ketma-ket faol'},
            {'emoji': '💪', 'title': 'Kuchli', 'unlocked': total_subs >= 100,
             'description': '100 ta vazifa topshiring'},
        ]
    except Exception as e:
        logger.exception(f"Achievements: {e}")
        return []


def get_leaderboard(student):
    try:
        students = (
            StudentProfile.objects
            .select_related('user')
            .annotate(total_xp=Coalesce(Sum('homework_submissions__xp_awarded'), 0))
            .order_by('-total_xp')[:10]
        )
        return [{
            'rank': idx, 'name': s.user.get_full_name() or 'Talaba',
            'letter': (s.user.first_name[:1] if s.user.first_name else 'T').upper(),
            'level': max(1, s.total_xp // 100), 'xp': s.total_xp,
            'is_me': s.pk == student.pk,
        } for idx, s in enumerate(students, start=1)]
    except Exception as e:
        logger.exception(f"Leaderboard: {e}")
        return []


def get_shop_items(coins):
    return [
        {'emoji': '🎨', 'title': 'Avatar rang', 'price': 50, 'can_buy': coins >= 50},
        {'emoji': '🎭', 'title': 'Maxsus nishon', 'price': 100, 'can_buy': coins >= 100},
        {'emoji': '🎮', 'title': "Mini o'yin", 'price': 150, 'can_buy': coins >= 150},
        {'emoji': '📚', 'title': 'Kitob', 'price': 200, 'can_buy': coins >= 200},
        {'emoji': '🎧', 'title': 'Audio dars', 'price': 250, 'can_buy': coins >= 250},
        {'emoji': '🎬', 'title': 'Video kurs', 'price': 300, 'can_buy': coins >= 300},
        {'emoji': '🎁', 'title': 'Bonus +100 XP', 'price': 500, 'can_buy': coins >= 500},
        {'emoji': '💎', 'title': 'Premium nishon', 'price': 1000, 'can_buy': coins >= 1000},
    ]


def get_calendar_events(student):
    try:
        today = timezone.now().date()
        first_day = today.replace(day=1)
        if first_day.month == 12:
            next_month = first_day.replace(year=first_day.year + 1, month=1)
        else:
            next_month = first_day.replace(month=first_day.month + 1)
        days_in_month = (next_month - first_day).days
        gls = (
            GroupLesson.objects
            .filter(group__students=student, lesson_date__gte=first_day,
                    lesson_date__lt=next_month)
            .values_list('lesson_date', flat=True)
        )
        events = set(gls)
        result = []
        for day in range(1, days_in_month + 1):
            current = date(first_day.year, first_day.month, day)
            result.append({
                'day': day, 'has_event': current in events,
                'is_today': current == today,
            })
        return result
    except Exception as e:
        logger.exception(f"Calendar: {e}")
        return []


def get_grade_distribution(student):
    try:
        subs = HomeworkSubmission.objects.filter(
            student=student, score__isnull=False, is_latest=True
        )
        total = subs.count()
        if not total:
            return []
        grades = [
            ('A', 90, 100, 'green', 'from-green-500 to-emerald-500'),
            ('B', 80, 89, 'blue', 'from-blue-500 to-cyan-500'),
            ('C', 70, 79, 'amber', 'from-amber-500 to-orange-500'),
            ('D', 60, 69, 'orange', 'from-orange-500 to-red-500'),
            ('F', 0, 59, 'rose', 'from-rose-500 to-red-600'),
        ]
        result = []
        for letter, min_s, max_s, color, gradient in grades:
            count = subs.filter(score__gte=min_s, score__lte=max_s).count()
            percent = round((count / total) * 100) if total else 0
            result.append({
                'letter': letter, 'min': min_s, 'max': max_s,
                'count': count, 'percent': percent,
                'color': color, 'gradient': gradient,
            })
        return result
    except Exception as e:
        logger.exception(f"Grade: {e}")
        return []


def get_subject_scores(student):
    try:
        enrollments = student.enrollments.filter(status='active').select_related('course')[:5]
        result = []
        for enr in enrollments:
            avg = HomeworkSubmission.objects.filter(
                student=student, homework__lesson__course=enr.course
            ).aggregate(avg=Avg('score'))['avg']
            result.append({
                'name': enr.course.title,
                'percent': round(float(avg), 1) if avg else 0,
            })
        return result
    except Exception as e:
        logger.exception(f"Subjects: {e}")
        return []


def get_homework_types_stats(student):
    """Uyga vazifa turlari bo'yicha statistika."""
    try:
        stats = (
            HomeworkSubmission.objects
            .filter(student=student)
            .values('homework__homework_type')
            .annotate(count=Count('id'), avg_score=Avg('score'))
        )
        type_display = dict(Homework._meta.get_field('homework_type').choices)
        return [{
            'type': type_display.get(s['homework__homework_type'], s['homework__homework_type']),
            'count': s['count'],
            'avg_score': round(float(s['avg_score']), 1) if s['avg_score'] else 0,
        } for s in stats]
    except Exception as e:
        logger.exception(f"HW types: {e}")
        return []


def get_week_summary(student):
    """Bu hafta bo'yicha xulosa."""
    try:
        today = timezone.now().date()
        week_start = today - timedelta(days=today.weekday())
        submissions = HomeworkSubmission.objects.filter(
            student=student, submitted_at__date__gte=week_start
        )
        total = submissions.count()
        graded = submissions.filter(score__isnull=False)
        avg = graded.aggregate(avg=Avg('score'))['avg'] or 0
        perfect = graded.filter(score__gte=90).count()
        return {
            'total': total, 'graded': graded.count(),
            'avg_score': round(float(avg), 1), 'perfect': perfect,
            'week_start': week_start, 'week_end': week_start + timedelta(days=6),
        }
    except Exception as e:
        logger.exception(f"Week summary: {e}")
        return {'total': 0, 'graded': 0, 'avg_score': 0, 'perfect': 0,
                'week_start': None, 'week_end': None}


def get_coins_history(student):
    """Coinlar tarixi (oxirgi 7 kun)."""
    try:
        today = timezone.now().date()
        days = [today - timedelta(days=i) for i in range(6, -1, -1)]
        history = []
        for day in days:
            coins = HomeworkSubmission.objects.filter(
                student=student, graded_at__date=day
            ).aggregate(total=Coalesce(Sum('coins_awarded'), 0))['total']
            history.append({
                'date': day, 'label': day.strftime('%d.%m'),
                'coins': coins,
            })
        return history
    except Exception as e:
        logger.exception(f"Coins history: {e}")
        return []


def get_xp_history(student):
    """XP tarixi (oxirgi 7 kun)."""
    try:
        today = timezone.now().date()
        days = [today - timedelta(days=i) for i in range(6, -1, -1)]
        history = []
        for day in days:
            xp = HomeworkSubmission.objects.filter(
                student=student, graded_at__date=day
            ).aggregate(total=Coalesce(Sum('xp_awarded'), 0))['total']
            history.append({
                'date': day, 'label': day.strftime('%d.%m'),
                'xp': xp,
            })
        return history
    except Exception as e:
        logger.exception(f"XP history: {e}")
        return []


def get_recommendations(student, stats):
    """Tavsiyalar."""
    recommendations = []
    if stats['missed'] > 0:
        recommendations.append({
            'icon': 'alert-triangle', 'color': 'rose',
            'title': f"{stats['missed']} ta vazifani bajaring",
            'text': "Kechikkan vazifalarni hoziroq boshlang",
            'action': 'filter_missed',
        })
    if stats['pending'] >= 3:
        recommendations.append({
            'icon': 'target', 'color': 'amber',
            'title': f"{stats['pending']} ta vazifa kutilmoqda",
            'text': "Kunlik maqsadni bajaring",
            'action': 'filter_new',
        })
    if stats['completed'] > 0:
        recommendations.append({
            'icon': 'trophy', 'color': 'green',
            'title': f"{stats['completed']} ta bajarildi",
            'text': "Zo'r ketmoqda, davom eting!",
            'action': 'show_stats',
        })
    return recommendations[:3]


def get_teacher_feedback(student):
    """O'qituvchi izohlari."""
    try:
        feedbacks = HomeworkSubmission.objects.filter(
            student=student, feedback__isnull=False
        ).exclude(feedback='').select_related('homework', 'graded_by').order_by('-graded_at')[:5]
        return [{
            'homework': f.homework.title,
            'teacher': f.graded_by.get_full_name() if f.graded_by else 'O\'qituvchi',
            'text': f.feedback[:200],
            'score': f.score,
            'date': f.graded_at.strftime('%d.%m.%Y') if f.graded_at else '',
        } for f in feedbacks]
    except Exception as e:
        logger.exception(f"Feedback: {e}")
        return []


def get_upcoming_tests(student):
    """Kelgusi testlar."""
    try:
        today = timezone.now().date()
        week_ahead = today + timedelta(days=7)
        tests = Quiz.objects.filter(
            course__enrollments__student=student,
            is_active=True,
            lesson__lesson_date__gte=today,
            lesson__lesson_date__lte=week_ahead,
        ).distinct().order_by('lesson__lesson_date')[:5]
        return [{
            'title': t.title, 'course': t.course.title if t.course else '',
            'date': t.lesson.lesson_date if t.lesson else None,
            'duration': t.duration_minutes, 'questions': t.questions.count(),
        } for t in tests]
    except Exception as e:
        logger.exception(f"Upcoming tests: {e}")
        return []


def get_recent_submissions(student):
    """So'nggi topshiriqlar."""
    try:
        subs = HomeworkSubmission.objects.filter(
            student=student, is_latest=True
        ).select_related('homework').order_by('-submitted_at')[:5]
        return [{
            'title': s.homework.title,
            'score': s.score,
            'max_score': s.homework.max_score,
            'percent': s.percent,
            'grade': s.grade_letter,
            'grade_color': s.grade_color,
            'status': s.get_status_display(),
            'submitted_at': s.submitted_at.strftime('%d.%m.%Y %H:%M'),
        } for s in subs]
    except Exception as e:
        logger.exception(f"Recent subs: {e}")
        return []


def get_badges_progress(student, streak, level):
    """Badge progress."""
    total_subs = HomeworkSubmission.objects.filter(student=student).count()
    graded = HomeworkSubmission.objects.filter(student=student, score__isnull=False)
    perfect = graded.filter(score__gte=90).count()
    return [
        {'name': 'Vazifalar', 'current': total_subs, 'target': 100,
         'progress': min(100, total_subs), 'icon': 'list-todo', 'color': 'primary'},
        {'name': 'Mukammal', 'current': perfect, 'target': 20,
         'progress': min(100, int(perfect / 20 * 100)), 'icon': 'star', 'color': 'amber'},
        {'name': 'Streak', 'current': streak, 'target': 30,
         'progress': min(100, int(streak / 30 * 100)), 'icon': 'flame', 'color': 'orange'},
        {'name': 'Daraja', 'current': level['level'], 'target': 15,
         'progress': min(100, int(level['level'] / 15 * 100)), 'icon': 'award', 'color': 'purple'},
    ]


def get_attendance_stats(student):
    """Davomat statistikasi."""
    try:
        total = Attendance.objects.filter(student=student).count()
        present = Attendance.objects.filter(student=student, status__in=['present', 'online']).count()
        absent = Attendance.objects.filter(student=student, status='absent').count()
        late = Attendance.objects.filter(student=student, status='late').count()
        percent = round((present / total * 100), 1) if total else 0
        return {'total': total, 'present': present, 'absent': absent,
                'late': late, 'percent': percent}
    except Exception as e:
        logger.exception(f"Attendance: {e}")
        return {'total': 0, 'present': 0, 'absent': 0, 'late': 0, 'percent': 0}


# ═══════════════════════════════════════════════════════════════
# ASOSIY VIEW
# ═══════════════════════════════════════════════════════════════

class StudentHomeworkListView(View):
    template_name = 'student/homework_list.html'

    def get(self, request):
        # 1. AUTH
        user = auto_login_from_request(request)
        if not user:
            return render(request, 'student/need_login.html', status=401)

        # 2. STUDENT
        student = StudentProfile.objects.filter(user=user).select_related('user').first()
        if not student:
            return render(request, 'student/no_profile.html',
                         {'user': user, 'debug': settings.DEBUG}, status=403)

        # 3. BUGUNGI DARSLAR
        today = timezone.localtime().date()
        today_lessons = (
            GroupLesson.objects
            .filter(group__students=student, lesson_date=today)
            .select_related('lesson', 'lesson__homework', 'lesson__course', 'group')
            .order_by('lesson__lesson_number')
        )

        # 4. ITEMS
        items = []
        for gl in today_lessons:
            homework = getattr(gl.lesson, 'homework', None)
            submission = None
            if homework:
                submission = HomeworkSubmission.objects.filter(
                    homework=homework, student=student, is_latest=True
                ).first()
            status_data = self._get_status_data(homework, submission, student)
            deadline = homework.get_deadline(student) if homework else None
            deadline_ts = int(deadline.timestamp()) if deadline else 0
            deadline_relative = self._get_relative_time(deadline) if deadline else ''

            homework_data = None
            if homework:
                homework_data = {
                    'id': homework.pk, 'title': homework.title,
                    'short_description': homework.short_description or '',
                    'type_display': homework.get_homework_type_display(),
                    'difficulty': homework.difficulty,
                    'difficulty_display': self._get_difficulty_display(homework.difficulty),
                    'difficulty_emoji': self._get_difficulty_emoji(homework.difficulty),
                    'difficulty_color': self._get_difficulty_color(homework.difficulty),
                    'estimated_minutes': homework.estimated_minutes or 0,
                    'max_score': homework.max_score,
                    'coins_reward': homework.coins_reward,
                    'xp_reward': homework.xp_reward,
                    'is_group_work': homework.is_group_work,
                }

            submission_data = None
            if submission:
                submission_data = {
                    'score': submission.score, 'percent': submission.percent,
                    'grade_letter': submission.grade_letter,
                    'is_graded': submission.is_graded,
                }

            is_urgent = False
            if deadline and not submission:
                hours_left = (deadline - timezone.now()).total_seconds() / 3600
                is_urgent = 0 < hours_left < 24

            items.append({
                'gl_id': gl.pk,
                'lesson': {'id': gl.lesson.pk, 'number': gl.lesson.lesson_number,
                           'title': gl.lesson.title},
                'course': {'id': gl.lesson.course.pk, 'title': gl.lesson.course.title},
                'group': {'id': gl.group.pk, 'name': gl.group.name},
                'homework': homework_data, 'submission': submission_data,
                'has_homework': bool(homework),
                'has_test': hasattr(gl.lesson, 'test') and gl.lesson.test is not None,
                'status': status_data['key'], 'status_text': status_data['text'],
                'status_icon': status_data['emoji'], 'status_color': status_data['color'],
                'status_cta': status_data['cta'],
                'deadline': deadline, 'deadline_ts': deadline_ts,
                'deadline_relative': deadline_relative, 'is_urgent': is_urgent,
                'search_text': self._build_search_text(gl, homework),
            })

        # 5. STATS
        total = len(items)
        completed = sum(1 for i in items if i['status'] in ('graded', 'pending', 'submitted'))
        pending = sum(1 for i in items if i['status'] == 'new')
        missed = sum(1 for i in items if i['status'] == 'missed')
        graded = sum(1 for i in items if i['status'] == 'graded')
        progress = round((completed / total * 100) if total else 0, 1)
        stats = {'total': total, 'completed': completed, 'pending': pending,
                 'missed': missed, 'graded': graded, 'progress': progress}

        # 6. GAMIFICATION
        greeting = get_greeting_by_hour()
        streak = get_student_streak(student)
        level = get_student_level(student)
        coins = getattr(student, 'coins', 0) or 0
        weekly = get_weekly_activity(student)
        monthly = get_monthly_activity(student)
        urgent_count = get_urgent_count(student)

        # 7. NOTIFICATIONS
        try:
            notification_count = Notification.objects.filter(
                user=user, is_read=False, is_approved=True
            ).count()
        except Exception:
            notification_count = 0

        # 8. BARCHA MA'LUMOTLAR
        daily_quests = get_daily_quests(stats, streak)
        quests_done = sum(1 for q in daily_quests if q['completed'])
        upcoming_deadlines = get_upcoming_deadlines(student)
        recent_activity = get_recent_activity(student)
        skills = get_skills(student)
        achievements = get_achievements(student, streak, level)
        achievements_unlocked = sum(1 for a in achievements if a['unlocked'])
        leaderboard = get_leaderboard(student)
        shop_items = get_shop_items(coins)
        calendar_events = get_calendar_events(student)
        grade_distribution = get_grade_distribution(student)
        subject_scores = get_subject_scores(student)
        hw_types_stats = get_homework_types_stats(student)
        week_summary = get_week_summary(student)
        coins_history = get_coins_history(student)
        xp_history = get_xp_history(student)
        recommendations = get_recommendations(student, stats)
        teacher_feedback = get_teacher_feedback(student)
        upcoming_tests = get_upcoming_tests(student)
        recent_submissions = get_recent_submissions(student)
        badges_progress = get_badges_progress(student, streak, level)
        attendance_stats = get_attendance_stats(student)

        # 9. AVG SCORE
        try:
            avg_score_val = HomeworkSubmission.objects.filter(
                student=student, score__isnull=False
            ).aggregate(avg=Avg('score'))['avg']
            avg_score = round(float(avg_score_val), 1) if avg_score_val else 0
        except Exception:
            avg_score = 0

        # 10. USER DATA
        user_data = {
            'first_name': user.first_name or '',
            'last_name': user.last_name or '',
            'full_name': user.get_full_name() or 'Talaba',
            'avatar_letter': (user.first_name[:1] if user.first_name else 'T').upper(),
            'phone': getattr(user, 'phone_number', '') or '',
            'id': user.pk,
        }

        # 11. CONTEXT
        ctx = {
            'current_url': 'homework', 'debug': settings.DEBUG,
            'user': user, 'student': student, 'user_data': user_data,
            'today': today, 'now': timezone.now(), 'greeting': greeting,
            # Items
            'items': items, 'homework_items': items, 'has_items': bool(items),
            # Stats
            'stats': stats, 'avg_score': avg_score,
            # Gamification
            'streak': streak, 'level': level, 'coins': coins,
            'weekly': weekly, 'monthly': monthly,
            'urgent_count': urgent_count, 'notification_count': notification_count,
            # Content
            'motivation': {'text': random.choice(MOTIVATIONS), 'icon': '💡'},
            'fun_fact': random.choice(FUN_FACTS),
            'mood_options': MOOD_OPTIONS, 'trust_badges': TRUST_BADGES,
            'tips': TIPS, 'quick_actions': QUICK_ACTIONS,
            # Yangi ma'lumotlar
            'daily_quests': daily_quests, 'quests_done': quests_done,
            'upcoming_deadlines': upcoming_deadlines,
            'recent_activity': recent_activity, 'skills': skills,
            'achievements': achievements,
            'achievements_unlocked': achievements_unlocked,
            'achievements_total': len(achievements),
            'leaderboard': leaderboard, 'shop_items': shop_items,
            'calendar_events': calendar_events,
            'grade_distribution': grade_distribution,
            'subject_scores': subject_scores,
            'hw_types_stats': hw_types_stats, 'week_summary': week_summary,
            'coins_history': coins_history, 'xp_history': xp_history,
            'recommendations': recommendations,
            'teacher_feedback': teacher_feedback,
            'upcoming_tests': upcoming_tests,
            'recent_submissions': recent_submissions,
            'badges_progress': badges_progress,
            'attendance_stats': attendance_stats,
            # Constants
            'min_file_size_kb': MIN_FILE_SIZE_KB,
            'max_file_size_mb': MAX_FILE_SIZE_MB,
            'min_text_length': MIN_TEXT_LENGTH,
            'daily_goal': DAILY_GOAL,
            'pomodoro_default': POMODORO_DEFAULT,
        }
        return render(request, self.template_name, ctx)

    @staticmethod
    def _get_status_data(homework, submission, student):
        if not homework:
            return {'key': 'no_hw', 'text': "Vazifa yo'q", 'emoji': 'ℹ️',
                    'color': 'gray', 'cta': "Ko'rish"}
        if submission:
            if submission.status == SubmissionStatus.GRADED:
                return {'key': 'graded', 'text': 'Baholangan', 'emoji': '✅',
                        'color': 'success', 'cta': "Natijani ko'rish"}
            elif submission.status == SubmissionStatus.PENDING:
                return {'key': 'pending', 'text': 'Tekshirilmoqda', 'emoji': '⏳',
                        'color': 'warm', 'cta': 'Tekshirilmoqda'}
            elif submission.status == SubmissionStatus.LATE:
                return {'key': 'late', 'text': 'Kechikkan', 'emoji': '⚠️',
                        'color': 'rose', 'cta': "Ko'rish"}
            return {'key': 'submitted', 'text': 'Topshirilgan', 'emoji': '📤',
                    'color': 'primary', 'cta': "Ko'rish"}
        deadline = homework.get_deadline(student)
        if deadline and timezone.now() > deadline:
            return {'key': 'missed', 'text': 'Bajarilmagan', 'emoji': '❌',
                    'color': 'rose', 'cta': 'Bajarish'}
        return {'key': 'new', 'text': 'Yangi', 'emoji': '🆕',
                'color': 'primary', 'cta': 'Boshlash'}

    @staticmethod
    def _get_relative_time(deadline):
        if not deadline:
            return ''
        diff = deadline - timezone.now()
        if diff.total_seconds() < 0:
            d = abs(diff)
            if d.days > 0: return f"{d.days} kun oldin"
            elif d.seconds > 3600: return f"{d.seconds // 3600} soat oldin"
            return f"{d.seconds // 60} daqiqa oldin"
        if diff.days > 0: return f"{diff.days} kun qoldi"
        elif diff.seconds > 3600: return f"{diff.seconds // 3600} soat qoldi"
        return f"{diff.seconds // 60} daqiqa qoldi"

    @staticmethod
    def _get_difficulty_display(d):
        return {'easy': 'Oson', 'medium': "O'rta", 'hard': 'Qiyin'}.get(d, "O'rta")

    @staticmethod
    def _get_difficulty_emoji(d):
        return {'easy': '🟢', 'medium': '🟡', 'hard': '🔴'}.get(d, '🟡')

    @staticmethod
    def _get_difficulty_color(d):
        return {'easy': 'green', 'medium': 'amber', 'hard': 'rose'}.get(d, 'amber')

    @staticmethod
    def _build_search_text(gl, homework):
        parts = [gl.lesson.title or '', gl.lesson.course.title or '', gl.group.name or '']
        if homework:
            parts.append(homework.title or '')
            parts.append(homework.short_description or '')
        return ' '.join(parts).lower()


# ═══════════════════════════════════════════════════════════════
# DETAIL VIEW
# ═══════════════════════════════════════════════════════════════

class StudentHomeworkDetailView(View):
    template_name = 'student/homework_detail.html'

    def get(self, request, pk):
        user = auto_login_from_request(request)
        if not user:
            return render(request, 'student/need_login.html', status=401)
        student = StudentProfile.objects.filter(user=user).first()
        if not student:
            return render(request, 'student/no_profile.html',
                         {'user': user, 'debug': settings.DEBUG}, status=403)
        homework = get_object_or_404(
            Homework.objects.filter(is_deleted=False, is_approved=True)
            .select_related('lesson', 'lesson__course'), pk=pk)
        gl_id = request.GET.get('gl')
        group_lesson = None
        if gl_id:
            try:
                group_lesson = GroupLesson.objects.filter(
                    pk=int(gl_id), lesson=homework.lesson
                ).select_related('group').first()
            except (ValueError, TypeError):
                pass
        submission = HomeworkSubmission.objects.filter(
            homework=homework, student=student, is_latest=True).first()
        deadline = homework.get_deadline(student)
        is_late = bool(deadline and timezone.now() > deadline)
        can_submit, block_reason = self._check_can_submit(homework, submission, is_late)
        ctx = {
            'homework': homework, 'lesson': homework.lesson,
            'course': homework.lesson.course, 'student': student, 'user': user,
            'group_lesson': group_lesson, 'submission': submission,
            'deadline': deadline, 'is_late': is_late,
            'can_submit': can_submit, 'submit_block_reason': block_reason,
            'min_file_size_kb': MIN_FILE_SIZE_KB,
            'max_file_size_mb': MAX_FILE_SIZE_MB,
            'min_text_length': MIN_TEXT_LENGTH,
            'debug': settings.DEBUG,
        }
        return render(request, self.template_name, ctx)

    def post(self, request, pk):
        user = auto_login_from_request(request)
        if not user:
            return JsonResponse({'ok': False, 'error': "Auth"}, status=401)
        student = StudentProfile.objects.filter(user=user).first()
        if not student:
            return JsonResponse({'ok': False, 'error': "Profil yo'q"}, status=403)
        homework = get_object_or_404(Homework, pk=pk, is_deleted=False, is_approved=True)
        answer_text = (request.POST.get('answer_text') or '').strip()
        answer_code = (request.POST.get('answer_code') or '').strip()
        answer_file = request.FILES.get('answer_file')
        if not (answer_text or answer_code or answer_file):
            return JsonResponse({'ok': False, 'error': "Javob bo'sh"}, status=400)
        deadline = homework.get_deadline(student)
        is_late = bool(deadline and timezone.now() > deadline)
        if is_late and not homework.allow_late_submission:
            return JsonResponse({'ok': False, 'error': "Muddat o'tgan"}, status=400)
        old = HomeworkSubmission.objects.filter(
            homework=homework, student=student, is_latest=True).first()
        if old:
            if old.status == SubmissionStatus.GRADED:
                return JsonResponse({'ok': False, 'error': "Baholangan"}, status=400)
            old.is_latest = False
            old.save(update_fields=['is_latest'])
        submission = HomeworkSubmission.objects.create(
            homework=homework, student=student, answer_text=answer_text,
            answer_code=answer_code, answer_file=answer_file, deadline=deadline,
            is_late=is_late, is_latest=True,
            resubmit_count=(old.resubmit_count + 1) if old else 0,
            status=SubmissionStatus.LATE if is_late else SubmissionStatus.PENDING)
        logger.info(f"✅ Submission: student={student.pk}, sub={submission.pk}")
        return JsonResponse({
            'ok': True, 'submission_id': submission.pk,
            'message': "✅ Vazifa topshirildi!", 'is_late': is_late})

    @staticmethod
    def _check_can_submit(homework, submission, is_late):
        if submission and submission.status == SubmissionStatus.GRADED:
            return False, "Allaqachon baholangan"
        if submission and submission.status == SubmissionStatus.PENDING:
            return False, "Tekshirilmoqda"
        if is_late and not homework.allow_late_submission:
            return False, "Muddat o'tgan"
        return True, ''