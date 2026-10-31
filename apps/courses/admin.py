"""
apps/courses/admin.py
================================================
DIGION LMS — Kurslar admin paneli.

XUSUSIYATLAR:
- Inlines (nested editing)
- Rangli badges va statuslar
- Custom actions (bulk operations)
- Autocomplete fields
- CSV export
- Statistika kartochkalari
- Progress bars
- Audit tracking
"""

import csv
from datetime import timedelta

from django.contrib import admin, messages
from django.contrib.contenttypes.admin import GenericTabularInline
from django.db.models import Count, Sum, Avg, Q, F
from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, mark_safe
from django.utils.safestring import SafeString
# ═══ DIGION modellari (apps.courses app) ═══
from .models import (
    # Kurslar
    CourseCategory, Tag, Course,
    CourseLanguage, CourseLevel, CourseStatus,

    # Oylar va darslar
    CourseMonth, Lesson,
    LessonDay, LessonType, LessonStatus,

    # Uyga vazifalar
    Homework, HomeworkSubmission,
    HomeworkType, SubmissionStatus,

    # Testlar
    Quiz, Question, AnswerOption,
    QuizAttempt, AttemptAnswer,
    QuizDifficulty, QuestionType, AttemptStatus,

    # Guruhlar
    StudentGroup, GroupMember, GroupStatus,

    # Yozilish va davomat
    Enrollment, Attendance,
    EnrollmentStatus, AttendanceStatus,

    # Qo'shimcha
    Review, Certificate,
    CourseModule, CourseFAQ, CourseAnnouncement,
    CourseResource, LessonLog, AuditLog,
)# apps/courses/admin.py da (agar kerak bo'lsa)
from apps.user.models.user import QuizCategory
# ═══════════════════════════════════════════════════════════════
# YORDAMCHI FUNKSIYALAR
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# YORDAMCHI FUNKSIYALAR — XAVFSIZ VERSIYA
# ═══════════════════════════════════════════════════════════════

def _to_str(value) -> str:
    """Har qanday qiymatni xavfsiz string'ga o'girish."""
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.1f}"
    if isinstance(value, int):
        return str(value)
    return str(value)


def _to_float(value, default: float = 0.0) -> float:
    """Har qanday qiymatni xavfsiz float'ga o'girish (SafeString bilan ham)."""
    if value is None:
        return default
    try:
        if isinstance(value, (int, float)):
            return float(value)
        # SafeString / str — regex bilan raqam qidirish
        import re
        text = str(value)
        match = re.search(r'-?\d+\.?\d*', text)
        return float(match.group()) if match else default
    except Exception:
        return default


def badge(text, color: str = "#6B7280", icon: str = "") -> SafeString:
    """
    Rangli badge.
    HAR QANDAY: str / int / float / Decimal / SafeString / None.
    """
    text_str = _to_str(text)
    icon_str = f"{icon} " if icon else ""
    color_str = str(color) if color else "#6B7280"

    # ⭐ f-string — barchasi string, format kodi yo'q
    return mark_safe(
        f'<span style="background:{color_str};color:#fff;padding:3px 10px;'
        f'border-radius:999px;font-size:11px;font-weight:600;'
        f'display:inline-flex;align-items:center;gap:4px;">'
        f'{icon_str}{text_str}</span>'
    )


def progress_bar(percent, color: str = "#6366f1", width: int = 100) -> SafeString:
    """
    Progress bar.
    HAR QANDAY: int / float / Decimal / SafeString / None.
    """
    # ⭐ Xavfsiz konversiya
    pct = _to_float(percent, 0.0)
    pct = max(0.0, min(100.0, pct))

    try:
        width_int = int(width)
    except (TypeError, ValueError):
        width_int = 100

    color_str = str(color) if color else "#6366f1"

    # ⭐ pct ni oldindan formatlash — f-string ichida
    pct_str = f"{pct:.0f}"

    return mark_safe(
        f'<div style="display:flex;align-items:center;gap:8px;">'
        f'<div style="background:#e2e8f0;border-radius:4px;height:8px;'
        f'width:{width_int}px;overflow:hidden;">'
        f'<div style="background:{color_str};height:100%;width:{pct_str}%;'
        f'transition:width 0.3s;"></div></div>'
        f'<span style="font-size:11px;font-weight:600;color:{color_str};">'
        f'{pct_str}%</span>'
        f'</div>'
    )


def status_dot(text: str, color: str) -> SafeString:
    """Status nuqtasi — xavfsiz."""
    text_str = _to_str(text)
    color_str = str(color) if color else "#6B7280"

    return mark_safe(
        f'<span style="color:{color_str};font-weight:600;display:inline-flex;'
        f'align-items:center;gap:6px;">'
        f'<span style="width:8px;height:8px;background:{color_str};'
        f'border-radius:50%;box-shadow:0 0 0 3px {color_str}20;"></span>'
        f'{text_str}</span>'
    )

# ═══════════════════════════════════════════════════════════════
# 1. KURS KATEGORIYASI
# ═══════════════════════════════════════════════════════════════

@admin.register(CourseCategory)
class CourseCategoryAdmin(admin.ModelAdmin):
    list_display = (
        'icon_preview', 'name', 'parent',
        'courses_count_badge', 'order', 'is_active'
    )
    list_filter = ('is_active', 'parent')
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}
    list_editable = ('order', 'is_active')
    ordering = ('order', 'name')
    readonly_fields = ('created_at', 'updated_at')
    list_per_page = 30

    fieldsets = (
        ('Asosiy', {
            'fields': ('name', 'slug', 'description')
        }),
        ('Dizayn', {
            'fields': ('icon', 'color', 'parent', 'order')
        }),
        ('Holat', {
            'fields': ('is_active',)
        }),
        ('Sanalar', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    @admin.display(description="Ikonka")
    def icon_preview(self, obj):
        return format_html(
            '<div style="width:36px;height:36px;border-radius:8px;'
            'background:{}20;display:flex;align-items:center;'
            'justify-content:center;color:{};">'
            '<i class="{}" style="font-size:16px;"></i></div>',
            obj.color, obj.color, obj.icon
        )

    @admin.display(description="Kurslar")
    def courses_count_badge(self, obj):
        count = obj.courses_count
        color = '#10b981' if count > 0 else '#94a3b8'
        return badge(str(count), color)


# ═══════════════════════════════════════════════════════════════
# 2. TAG
# ═══════════════════════════════════════════════════════════════

@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ('name_badge', 'usage_count', 'color_preview')
    search_fields = ('name',)
    prepopulated_fields = {'slug': ('name',)}
    ordering = ('-usage_count', 'name')
    readonly_fields = ('usage_count', 'created_at', 'updated_at')

    @admin.display(description="Nomi")
    def name_badge(self, obj):
        return badge(obj.name, obj.color, '🏷')

    @admin.display(description="Rang")
    def color_preview(self, obj):
        return format_html(
            '<div style="width:60px;height:20px;background:{};'
            'border-radius:4px;"></div>',
            obj.color
        )


# ═══════════════════════════════════════════════════════════════
# 3. KURS (Asosiy)
# ═══════════════════════════════════════════════════════════════

class CourseMonthInline(admin.StackedInline):
    model = CourseMonth
    extra = 0
    fields = ('month_number', 'title', 'start_date', 'end_date', 'is_active')
    show_change_link = True
    classes = ('collapse',)


class CourseModuleInline(admin.TabularInline):
    model = CourseModule
    extra = 0
    fields = ('order', 'title', 'is_published')


class CourseFAQInline(admin.TabularInline):
    model = CourseFAQ
    extra = 0
    fields = ('order', 'question', 'is_active')


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = (
        'cover_thumb', 'title_link', 'category',
        'teacher_display', 'price_display',
        'status_badge', 'progress_display',
        'students_count_badge', 'rating_display', 'is_featured'
    )
    list_filter = (
        'status', 'level', 'language', 'is_active',
        'is_featured', 'is_free', 'category', 'created_at',
    )
    search_fields = (
        'title', 'short_description', 'description',
        'slug', 'teacher__first_name', 'teacher__last_name',
    )
    prepopulated_fields = {'slug': ('title',)}
    autocomplete_fields = ('teacher', 'created_by', 'category')
    filter_horizontal = ('tags', 'co_teachers')
    inlines = [CourseMonthInline, CourseModuleInline, CourseFAQInline]
    date_hierarchy = 'created_at'
    list_per_page = 20
    save_on_top = True

    fieldsets = (
        ('Asosiy ma’lumotlar', {
            'fields': (
                'title', 'slug', 'short_description', 'description',
                'cover_image', 'promo_video',
            )
        }),
        ('Kategoriya va teglar', {
            'fields': ('category', 'tags')
        }),
        ('O‘qituvchilar', {
            'fields': ('teacher', 'co_teachers', 'created_by')
        }),
        ('Sanalar va davomiylik', {
            'fields': (
                'start_date', 'end_date', 'duration_months',
            )
        }),
        ('Xususiyatlar', {
            'fields': ('language', 'level', 'status')
        }),
        ('Narx va to‘lov', {
            'fields': (
                'price', 'discounted_price', 'is_free',
            )
        }),
        ('Sozlamalar', {
            'fields': (
                'is_active', 'is_featured', 'is_certificate_enabled',
                'max_students',
            )
        }),
        ('Baholash mezonlari', {
            'fields': ('passing_score', 'attendance_required'),
            'classes': ('collapse',)
        }),
        ('Statistika', {
            'fields': (
                'view_count', 'enrollment_count', 'completion_count',
                'rating', 'reviews_count',
            ),
            'classes': ('collapse',)
        }),
        ('SEO', {
            'fields': ('meta_title', 'meta_description', 'meta_keywords'),
            'classes': ('collapse',)
        }),
        ('Sanalar', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    readonly_fields = (
        'created_at', 'updated_at',
        'view_count', 'enrollment_count', 'completion_count',
        'rating', 'reviews_count',
    )

    actions = [
        'publish_courses', 'archive_courses',
        'feature_courses', 'unfeature_courses',
        'activate_courses', 'deactivate_courses',
        'export_courses_csv',
    ]

    @admin.display(description="Muqova")
    def cover_thumb(self, obj):
        if obj.cover_image:
            return format_html(
                '<img src="{}" style="width:50px;height:50px;'
                'border-radius:8px;object-fit:cover;'
                'box-shadow:0 2px 8px rgba(0,0,0,0.1);">',
                obj.cover_image.url
            )
        return format_html(
            '<div style="width:50px;height:50px;border-radius:8px;'
            'background:linear-gradient(135deg,#6366f1,#8b5cf6);'
            'display:flex;align-items:center;justify-content:center;'
            'color:#fff;font-weight:700;font-size:18px;">'
            '{}</div>',
            obj.title[:1].upper() if obj.title else '?'
        )

    @admin.display(description="Kurs nomi", ordering='title')
    def title_link(self, obj):
        url = reverse('admin:courses_course_change', args=[obj.pk])
        return format_html(
            '<a href="{}" style="font-weight:600;color:#4338ca;'
            'text-decoration:none;">{}</a>'
            '<div style="font-size:11px;color:#94a3b8;margin-top:2px;">'
            '{} · {} oy</div>',
            url, obj.title[:50],
            obj.get_level_display(),
            obj.duration_months,
        )

    @admin.display(description="O‘qituvchi")
    def teacher_display(self, obj):
        if not obj.teacher:
            return status_dot("Belgilanmagan", "#dc2626")
        return format_html(
            '<div style="display:flex;align-items:center;gap:8px;">'
            '<div style="width:32px;height:32px;border-radius:50%;'
            'background:linear-gradient(135deg,#6366f1,#8b5cf6);'
            'display:flex;align-items:center;justify-content:center;'
            'color:#fff;font-weight:600;font-size:12px;">{}</div>'
            '<div><div style="font-weight:500;font-size:13px;">{}</div>'
            '<div style="font-size:11px;color:#94a3b8;">{}</div></div>'
            '</div>',
            (obj.teacher.first_name or 'T')[:1].upper(),
            obj.teacher.get_full_name() or obj.teacher.phone_number,
            obj.teacher.phone_number,
        )

    @admin.display(description="Narx", ordering='price')
    @admin.display(description="Narx", ordering='price')
    def price_display(self, obj):
        if obj.is_free or obj.price == 0:
            return badge("BEPUL", "#10b981", "🎁")

        # ⭐ xavfsiz float
        try:
            price = float(obj.current_price or 0)
            original = float(obj.price or 0)
        except (TypeError, ValueError):
            price, original = 0.0, 0.0

        if obj.discount_percent > 0:
            return format_html(
                '<div>'
                '<div style="font-weight:700;color:#10b981;">{:,.0f} so‘m</div>'
                '<div style="font-size:11px;text-decoration:line-through;'
                'color:#94a3b8;">{:,.0f} so‘m</div>'
                '<div style="font-size:10px;color:#ef4444;">-{}%</div>'
                '</div>',
                price, original, obj.discount_percent,
            )

        return format_html(
            '<span style="font-weight:700;">{:,.0f} so‘m</span>',
            price
        )

    @admin.display(description="Holat", ordering='status')
    def status_badge(self, obj):
        colors = {
            'draft': '#94a3b8',
            'pending': '#f59e0b',
            'published': '#10b981',
            'archived': '#6b7280',
        }
        icons = {
            'draft': '📝',
            'pending': '⏳',
            'published': '✅',
            'archived': '📦',
        }
        return badge(
            obj.get_status_display(),
            colors.get(obj.status, '#6b7280'),
            icons.get(obj.status, '')
        )

    @admin.display(description="Progress")
    def progress_display(self, obj):
        color = '#10b981' if obj.progress_percent >= 70 else \
            '#f59e0b' if obj.progress_percent >= 40 else '#ef4444'
        return progress_bar(obj.progress_percent, color, 80)

    @admin.display(description="Talabalar")
    def students_count_badge(self, obj):
        count = obj.total_students
        return format_html(
            '<span style="font-weight:600;color:#6366f1;font-size:14px;">'
            '{}</span> <span style="font-size:11px;color:#94a3b8;">ta</span>',
            count
        )

    @admin.display(description="Reyting")
    def rating_display(self, obj):
        # ⭐ SafeString bo'lsa float ga o'girish
        try:
            rating = float(obj.rating or 0)
        except (TypeError, ValueError):
            rating = 0.0

        if rating == 0:
            return "—"

        color = '#10b981' if rating >= 4.5 else \
            '#f59e0b' if rating >= 3.5 else '#ef4444'
        stars = '★' * int(round(rating)) + '☆' * (5 - int(round(rating)))

        return format_html(
            '<div style="color:{};">{}</div>'
            '<div style="font-size:11px;color:#94a3b8;">{:.1f} ({})</div>',
            color, stars, rating,  # ← rating — float
            int(obj.reviews_count or 0),
        )

    # ═══ ACTIONS ═══

    @admin.action(description="📢 Tanlangan kurslarni e’lon qilish")
    def publish_courses(self, request, queryset):
        updated = queryset.update(status='published', is_active=True)
        self.message_user(
            request,
            f"✅ {updated} ta kurs e’lon qilindi",
            messages.SUCCESS
        )

    @admin.action(description="📦 Arxivlash")
    def archive_courses(self, request, queryset):
        updated = queryset.update(status='archived')
        self.message_user(request, f"📦 {updated} ta kurs arxivlandi")

    @admin.action(description="⭐ Tanlangan deb belgilash")
    def feature_courses(self, request, queryset):
        updated = queryset.update(is_featured=True)
        self.message_user(request, f"⭐ {updated} ta kurs tanlandi")

    @admin.action(description="⭐ Tanlovdan olib tashlash")
    def unfeature_courses(self, request, queryset):
        updated = queryset.update(is_featured=False)
        self.message_user(request, f"❌ {updated} ta kurs tanlovdan olindi")

    @admin.action(description="✅ Aktivlashtirish")
    def activate_courses(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"✅ {updated} ta kurs aktivlashtirildi")

    @admin.action(description="🚫 O‘chirish")
    def deactivate_courses(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"🚫 {updated} ta kurs o‘chirildi")

    @admin.action(description="📥 CSV eksport")
    def export_courses_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="courses.csv"'
        response.write('\ufeff')
        writer = csv.writer(response)
        writer.writerow([
            'Kurs nomi', 'Kategoriya', 'O‘qituvchi', 'Daraja',
            'Til', 'Narx', 'Status', 'Talabalar', 'Reyting', 'Sana'
        ])
        for course in queryset:
            writer.writerow([
                course.title,
                course.category.name if course.category else '',
                course.teacher.get_full_name() if course.teacher else '',
                course.get_level_display(),
                course.get_language_display(),
                float(course.current_price),
                course.get_status_display(),
                course.total_students,
                float(course.rating),
                course.created_at.strftime('%Y-%m-%d'),
            ])
        return response


# ═══════════════════════════════════════════════════════════════
# 4. KURS OYI
# ═══════════════════════════════════════════════════════════════

class LessonInline(admin.TabularInline):
    model = Lesson
    extra = 0
    fields = (
        'week_number', 'day_of_week', 'title',
        'status', 'lesson_date', 'is_published',
    )
    show_change_link = True
    classes = ('collapse',)


@admin.register(CourseMonth)
class CourseMonthAdmin(admin.ModelAdmin):
    list_display = (
        'month_badge', 'course_link', 'title',
        'dates_display', 'lessons_count_badge',
        'progress_display', 'is_completed'
    )
    list_filter = ('is_active', 'is_completed', 'course')
    search_fields = ('title', 'description', 'course__title')
    autocomplete_fields = ('course',)
    inlines = [LessonInline]
    ordering = ('course', 'month_number')
    list_per_page = 20

    fieldsets = (
        ('Asosiy', {
            'fields': ('course', 'month_number', 'title', 'description')
        }),
        ('Maqsadlar', {
            'fields': ('goals', 'topics_covered')
        }),
        ('Sanalar', {
            'fields': ('start_date', 'end_date')
        }),
        ('Holat', {
            'fields': ('is_active', 'is_completed')
        }),
        ('Dizayn', {
            'fields': ('icon', 'color'),
            'classes': ('collapse',)
        }),
        ('Sanalar', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    readonly_fields = ('created_at', 'updated_at')

    @admin.display(description="Oy", ordering='month_number')
    def month_badge(self, obj):
        colors = [
            '#6366f1', '#8b5cf6', '#ec4899', '#06b6d4',
            '#10b981', '#f59e0b', '#ef4444', '#14b8a6', '#a855f7'
        ]
        color = colors[(obj.month_number - 1) % len(colors)]
        return format_html(
            '<div style="width:52px;height:52px;border-radius:14px;'
            'background:linear-gradient(135deg,{},{}cc);'
            'display:flex;flex-direction:column;align-items:center;'
            'justify-content:center;color:#fff;font-weight:700;'
            'box-shadow:0 4px 12px {}40;">'
            '<span style="font-size:9px;opacity:0.85;">OY</span>'
            '<span style="font-size:20px;line-height:1;">{}</span>'
            '</div>',
            color, color, color, obj.month_number
        )

    @admin.display(description="Kurs")
    def course_link(self, obj):
        url = reverse('admin:courses_course_change', args=[obj.course.pk])
        return format_html(
            '<a href="{}" style="color:#4338ca;font-weight:500;">'
            '{}</a>',
            url, obj.course.title[:40]
        )

    @admin.display(description="Sanalar")
    def dates_display(self, obj):
        return format_html(
            '<div style="font-size:12px;">'
            '<div style="color:#10b981;">▶ {}</div>'
            '<div style="color:#ef4444;">◀ {}</div>'
            '</div>',
            obj.start_date.strftime('%d.%m.%Y'),
            obj.end_date.strftime('%d.%m.%Y'),
        )

    @admin.display(description="Darslar")
    def lessons_count_badge(self, obj):
        total = obj.total_lessons
        completed = obj.completed_lessons
        color = '#10b981' if completed == total else \
            '#f59e0b' if completed > 0 else '#94a3b8'
        return badge(f"{completed}/{total}", color)

    @admin.display(description="Progress")
    def progress_display(self, obj):
        pct = obj.progress_percent
        color = '#10b981' if pct >= 70 else \
            '#f59e0b' if pct >= 40 else '#ef4444'
        return progress_bar(pct, color, 80)


# ═══════════════════════════════════════════════════════════════
# 5. DARS
# ═══════════════════════════════════════════════════════════════

class HomeworkInline(admin.StackedInline):
    model = Homework
    extra = 0
    max_num = 1
    fields = (
        'title', 'short_description', 'homework_type',
        'deadline_days', 'max_score', 'coins_reward',
    )
    classes = ('collapse',)


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = (
        'day_badge', 'title_link', 'course_display',
        'week_badge', 'date_display', 'type_badge',
        'status_badge', 'media_badges', 'is_published'
    )
    list_filter = (
        'status', 'day_of_week', 'lesson_type',
        'is_published', 'is_mandatory', 'course',
    )
    search_fields = ('title', 'content', 'course__title')
    autocomplete_fields = ('course', 'month')          # ← 'group' olib tashlandi
    inlines = [HomeworkInline]
    date_hierarchy = 'lesson_date'
    ordering = ('-lesson_date', 'week_number', 'order')
    list_per_page = 20
    save_on_top = True

    # admin.py — LessonAdmin.fieldsets ni almashtiring
    fieldsets = (
        ('Asosiy', {
            'fields': ('course', 'lesson_number', 'topic',
                       'title', 'short_description')
        }),
        ('Kontent', {
            'fields': ('content', 'code_examples',
                       'extra_sections', 'extra_materials')
        }),
        ('Multimedia', {
            'fields': ('video_url', 'video_file', 'attachments')
        }),
        ('Vaqt', {
            'fields': ('lesson_date', 'duration_minutes')
        }),
        ('Holat', {
            'fields': ('status', 'is_published', 'is_mandatory')
        }),
        ('Statistika', {
            'fields': ('view_count',),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = (
        'view_count',                                   # ← 'completion_count' olib tashlandi
        'created_at', 'updated_at',
    )

    actions = [
        'mark_completed', 'mark_planned',
        'publish_lessons', 'unpublish_lessons',
    ]

    # ==========================================
    # BARCHA @admin.display METODLAR O'ZGARMAYDI
    # ==========================================
    @admin.display(description="Kun", ordering='day_of_week')
    def day_badge(self, obj):
        colors = {
            'monday': '#3b82f6', 'tuesday': '#10b981',
            'wednesday': '#8b5cf6', 'thursday': '#ec4899',
            'friday': '#f59e0b', 'saturday': '#f97316',
            'sunday': '#ef4444',
        }
        short = {
            'monday': 'Du', 'tuesday': 'Se', 'wednesday': 'Ch',
            'thursday': 'Pa', 'friday': 'Ju',
            'saturday': 'Sha', 'sunday': 'Ya',
        }
        color = colors.get(obj.day_of_week, '#6b7280')
        return format_html(
            '<div style="width:44px;height:44px;border-radius:12px;'
            'background:{}15;color:{};display:flex;flex-direction:column;'
            'align-items:center;justify-content:center;'
            'border:2px solid {}30;">'
            '<span style="font-size:14px;font-weight:800;line-height:1;">'
            '{}</span>'
            '<span style="font-size:8px;opacity:0.7;">kun</span>'
            '</div>',
            color, color, color,
            short.get(obj.day_of_week, '?')
        )

    @admin.display(description="Mavzu", ordering='title')
    def title_link(self, obj):
        url = reverse('admin:courses_lesson_change', args=[obj.pk])
        badges = []
        if obj.has_homework:
            badges.append(
                '<span style="background:#10b98120;color:#059669;'
                'padding:1px 6px;border-radius:4px;font-size:10px;'
                'font-weight:600;">📝 Vazifa</span>'
            )
        if obj.has_test:
            badges.append(
                '<span style="background:#6366f120;color:#4338ca;'
                'padding:1px 6px;border-radius:4px;font-size:10px;'
                'font-weight:600;">🧪 Test</span>'
            )
        return format_html(
            '<a href="{}" style="color:#4338ca;font-weight:600;'
            'text-decoration:none;">{}</a>'
            '<div style="margin-top:4px;display:flex;gap:4px;">{}</div>',
            url, obj.title[:60],
            mark_safe(''.join(badges))
        )

    @admin.display(description="Kurs")
    def course_display(self, obj):
        return format_html(
            '<div style="font-size:12px;color:#64748b;">{}</div>',
            obj.course.title[:30]
        )

    @admin.display(description="Hafta")
    def week_badge(self, obj):
        return badge(f"{obj.week_number}-hafta", '#8b5cf6')

    @admin.display(description="Sana", ordering='lesson_date')
    def date_display(self, obj):
        if not obj.lesson_date:
            return status_dot("Belgilanmagan", "#94a3b8")
        if obj.is_today:
            return badge("BUGUN", '#10b981', '🔥')
        if obj.is_past:
            return format_html(
                '<span style="color:#94a3b8;">{}</span>',
                obj.lesson_date.strftime('%d.%m.%Y')
            )
        return format_html(
            '<span style="color:#4338ca;font-weight:600;">{}</span>',
            obj.lesson_date.strftime('%d.%m.%Y')
        )

    @admin.display(description="Tur")
    def type_badge(self, obj):
        colors = {
            'theory': '#6366f1', 'practice': '#10b981',
            'workshop': '#f59e0b', 'project': '#8b5cf6',
            'review': '#06b6d4', 'exam': '#ef4444',
        }
        return badge(
            obj.get_lesson_type_display(),
            colors.get(obj.lesson_type, '#6b7280')
        )

    @admin.display(description="Holat")
    def status_badge(self, obj):
        colors = {
            'planned': '#94a3b8', 'in_progress': '#f59e0b',
            'completed': '#10b981', 'skipped': '#ef4444',
            'rescheduled': '#8b5cf6',
        }
        icons = {
            'planned': '📅', 'in_progress': '⏳',
            'completed': '✅', 'skipped': '⏭',
            'rescheduled': '🔄',
        }
        return badge(
            obj.get_status_display(),
            colors.get(obj.status, '#6b7280'),
            icons.get(obj.status, '')
        )

    @admin.display(description="Media")
    @admin.display(description="Media")
    def media_badges(self, obj):
        items = []
        if obj.has_video:
            items.append('<span title="Video">🎬</span>')
        if obj.has_homework:
            items.append('<span title="Vazifa">📝</span>')
        if obj.has_test:
            items.append('<span title="Test">🧪</span>')
        return mark_safe(
            f'<div style="display:flex;gap:6px;">'
            f'{"".join(items) if items else "—"}</div>'
    )
    # ═══ ACTIONS ═══

    @admin.action(description="✅ O'tilgan deb belgilash")
    def mark_completed(self, request, queryset):
        updated = queryset.update(
            status='completed',
            lesson_date=timezone.now().date()
        )
        self.message_user(request, f"✅ {updated} ta dars o'tilgan deb belgilandi")

    @admin.action(description="📅 Rejalashtirilgan deb belgilash")
    def mark_planned(self, request, queryset):
        updated = queryset.update(status='planned')
        self.message_user(request, f"📅 {updated} ta dars rejalashtirildi")

    @admin.action(description="📢 E'lon qilish")
    def publish_lessons(self, request, queryset):
        updated = queryset.update(is_published=True)
        self.message_user(request, f"📢 {updated} ta dars e'lon qilindi")

    @admin.action(description="🔒 Yopish")
    def unpublish_lessons(self, request, queryset):
        updated = queryset.update(is_published=False)
        self.message_user(request, f"🔒 {updated} ta dars yopildi")
# ═══════════════════════════════════════════════════════════════
# 6. UYGA VAZIFA
# ═══════════════════════════════════════════════════════════════

@admin.register(Homework)
class HomeworkAdmin(admin.ModelAdmin):
    list_display = (
        'title_link', 'lesson_display', 'type_badge',
        'deadline_badge', 'score_badge',
        'approval_status', 'send_status',
        'completion_display'
    )
    list_filter = (
        'homework_type', 'is_approved', 'is_sent',
        'lesson__course', 'created_at',
    )
    search_fields = ('title', 'description', 'lesson__title')
    autocomplete_fields = (
        'lesson', 'quiz', 'created_by', 'approved_by',
    )
    filter_horizontal = ('sent_to_groups',)
    date_hierarchy = 'created_at'
    list_per_page = 20
    save_on_top = True

    fieldsets = (
        ('Asosiy', {
            'fields': (
                'lesson', 'title', 'short_description',
                'description', 'instructions', 'homework_type',
            )
        }),
        ('Fayllar va kod', {
            'fields': (
                'task_file', 'starter_code',
                'solution_code', 'reference_materials',
            )
        }),
        ('Mezonlar', {
            'fields': (
                'deadline_days', 'max_score',
                'coins_reward', 'xp_reward',
            )
        }),
        ('Test', {
            'fields': ('quiz',)
        }),
        ('Tasdiqlash', {
            'fields': (
                'is_approved', 'approved_by', 'approved_at',
            )
        }),
        ('Yuborish', {
            'fields': (
                'is_sent', 'sent_at', 'sent_to_groups',
            )
        }),
        ('Statistika', {
            'fields': (
                'views_count', 'submissions_count', 'avg_score',
            ),
            'classes': ('collapse',)
        }),
    )

    readonly_fields = (
        'approved_at', 'sent_at',
        'views_count', 'submissions_count', 'avg_score',
        'created_at', 'updated_at',
    )

    actions = [
        'approve_homeworks', 'unapprove_homeworks',
        'send_to_groups', 'export_submissions_csv',
    ]

    @admin.display(description="Vazifa", ordering='title')
    def title_link(self, obj):
        url = reverse('admin:courses_homework_change', args=[obj.pk])
        return format_html(
            '<a href="{}" style="color:#4338ca;font-weight:600;'
            'text-decoration:none;">{}</a>'
            '<div style="font-size:11px;color:#94a3b8;margin-top:2px;">'
            '{} ta topshiriq</div>',
            url, obj.title[:50],
            obj.submissions_count,
        )

    @admin.display(description="Dars")
    def lesson_display(self, obj):
        return format_html(
            '<div style="font-size:12px;">'
            '<div style="font-weight:500;">{}</div>'
            '<div style="color:#94a3b8;font-size:11px;">{}</div>'
            '</div>',
            obj.lesson.title[:40],
            obj.lesson.course.title[:30]
        )

    @admin.display(description="Tur")
    def type_badge(self, obj):
        colors = {
            'writing': '#6366f1', 'coding': '#10b981',
            'project': '#8b5cf6', 'reading': '#f59e0b',
            'video': '#ef4444', 'mixed': '#06b6d4',
        }
        icons = {
            'writing': '✍️', 'coding': '💻',
            'project': '📦', 'reading': '📖',
            'video': '🎬', 'mixed': '🎨',
        }
        return badge(
            obj.get_homework_type_display(),
            colors.get(obj.homework_type, '#6b7280'),
            icons.get(obj.homework_type, '')
        )

    @admin.display(description="Muddat")
    def deadline_badge(self, obj):
        return format_html(
            '<div style="text-align:center;">'
            '<div style="font-size:16px;font-weight:700;color:#4338ca;">'
            '{}</div>'
            '<div style="font-size:10px;color:#94a3b8;">kun</div>'
            '</div>',
            obj.deadline_days
        )

    @admin.display(description="Ball")
    def score_badge(self, obj):
        return format_html(
            '<div style="text-align:center;">'
            '<div style="font-size:14px;font-weight:700;color:#10b981;">'
            '{}</div>'
            '<div style="font-size:10px;color:#f59e0b;">🪙 {}</div>'
            '</div>',
            obj.max_score, obj.coins_reward
        )

    @admin.display(description="Tasdiq")
    def approval_status(self, obj):
        if obj.is_approved:
            return badge("Tasdiqlangan", '#10b981', '✅')
        return badge("Kutilmoqda", '#f59e0b', '⏳')

    @admin.display(description="Yuborish")
    def send_status(self, obj):
        if obj.is_sent:
            groups = obj.sent_to_groups.count()
            return badge(f"Yuborilgan ({groups})", '#6366f1', '📤')
        return badge("Yuborilmagan", '#94a3b8', '📥')

    @admin.display(description="Bajarish")
    @admin.display(description="Bajarish")
    def completion_display(self, obj):
        if not obj.submissions_count:
            return "—"

        # ⭐ SafeString/None bo'lsa ham xavfsiz
        try:
            pct = float(obj.completion_rate or 0)
        except (TypeError, ValueError):
            pct = 0.0

        color = '#10b981' if pct >= 70 else \
            '#f59e0b' if pct >= 40 else '#ef4444'

        return format_html(
            '<div style="font-size:11px;color:#64748b;margin-bottom:2px;">'
            '{} / {} ta</div>',
            int(obj.completed_count or 0),
            int(obj.total_students or 0),
        ) + progress_bar(pct, color, 60)

    # ═══ ACTIONS ═══

    @admin.action(description="✅ Tasdiqlash")
    def approve_homeworks(self, request, queryset):
        updated = queryset.update(
            is_approved=True,
            approved_by=request.user,
            approved_at=timezone.now()
        )
        self.message_user(
            request,
            f"✅ {updated} ta uyga vazifa tasdiqlandi",
            messages.SUCCESS
        )

    @admin.action(description="❌ Tasdiqni bekor qilish")
    def unapprove_homeworks(self, request, queryset):
        updated = queryset.update(is_approved=False)
        self.message_user(request, f"❌ {updated} ta tasdiq bekor qilindi")

    @admin.action(description="📤 Guruhga yuborish")
    def send_to_groups(self, request, queryset):
        from apps.service.notification_service import send_homework_to_group

        sent_count = 0
        for homework in queryset.filter(is_approved=True):
            for group in homework.sent_to_groups.all():
                try:
                    result = send_homework_to_group(homework, group, request.user)
                    if result.get('success'):
                        sent_count += 1
                except Exception as e:
                    self.message_user(
                        request,
                        f"❌ {homework.title}: {e}",
                        messages.ERROR
                    )

        self.message_user(
            request,
            f"📤 {sent_count} ta guruhga yuborildi",
            messages.SUCCESS
        )

    @admin.action(description="📥 Topshiriqlar CSV")
    def export_submissions_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="submissions.csv"'
        response.write('\ufeff')
        writer = csv.writer(response)
        writer.writerow([
            'Vazifa', 'Talaba', 'Telefon', 'Topshirildi',
            'Ball', 'Foiz', 'Baho', 'Kechikkan', 'Holat'
        ])
        for hw in queryset:
            for sub in hw.submissions.all():
                writer.writerow([
                    hw.title,
                    sub.student.user.get_full_name(),
                    sub.student.user.phone_number,
                    sub.submitted_at.strftime('%Y-%m-%d %H:%M'),
                    sub.score or '—',
                    f"{sub.percent}%" if sub.score else '—',
                    sub.grade_letter if sub.score else '—',
                    'Ha' if sub.is_late else 'Yo‘q',
                    sub.get_status_display(),
                ])
        return response


# ═══════════════════════════════════════════════════════════════
# 7. UYGA VAZIFA TOPSHIRIG‘I
# ═══════════════════════════════════════════════════════════════

@admin.register(HomeworkSubmission)
class HomeworkSubmissionAdmin(admin.ModelAdmin):
    list_display = (
        'student_display', 'homework_display',
        'submitted_at_display', 'late_badge',
        'score_badge', 'grade_display',
        'status_badge', 'graded_by'
    )
    list_filter = (
        'status', 'is_late', 'is_latest',
        'homework__lesson__course', 'submitted_at',
    )
    search_fields = (
        'student__user__phone_number',
        'student__user__first_name',
        'student__user__last_name',
        'homework__title',
    )
    autocomplete_fields = ('homework', 'student', 'graded_by')
    date_hierarchy = 'submitted_at'
    list_per_page = 30
    save_on_top = True

    fieldsets = (
        ('Asosiy', {
            'fields': (
                'homework', 'student', 'submitted_at',
                'deadline', 'is_late', 'time_spent_minutes',
            )
        }),
        ('Javob', {
            'fields': (
                'answer_text', 'answer_code',
                'answer_file', 'attachments',
            )
        }),
        ('Baholash', {
            'fields': (
                'status', 'score', 'feedback',
                'graded_by', 'graded_at',
                'coins_awarded', 'xp_awarded',
            )
        }),
        ('Qo‘shimcha', {
            'fields': ('is_latest', 'resubmit_count'),
            'classes': ('collapse',)
        }),
    )

    readonly_fields = (
        'submitted_at', 'graded_at',
        'created_at', 'updated_at',
    )

    actions = ['mark_graded', 'export_csv']

    @admin.display(description="Talaba")
    def student_display(self, obj):
        user = obj.student.user
        return format_html(
            '<div style="display:flex;align-items:center;gap:8px;">'
            '<div style="width:36px;height:36px;border-radius:50%;'
            'background:linear-gradient(135deg,#3b82f6,#6366f1);'
            'display:flex;align-items:center;justify-content:center;'
            'color:#fff;font-weight:600;font-size:13px;">{}</div>'
            '<div><div style="font-weight:600;font-size:13px;">{}</div>'
            '<div style="font-size:11px;color:#94a3b8;">{}</div></div>'
            '</div>',
            (user.first_name or user.phone_number)[:1].upper(),
            user.get_full_name() or user.phone_number,
            user.phone_number,
        )

    @admin.display(description="Vazifa")
    def homework_display(self, obj):
        return format_html(
            '<div style="font-size:12px;font-weight:500;">{}</div>',
            obj.homework.title[:50]
        )

    @admin.display(description="Topshirildi", ordering='submitted_at')
    def submitted_at_display(self, obj):
        return format_html(
            '<div style="font-size:12px;">'
            '<div style="font-weight:500;">{}</div>'
            '<div style="color:#94a3b8;font-size:11px;">{}</div>'
            '</div>',
            obj.submitted_at.strftime('%d.%m.%Y'),
            obj.submitted_at.strftime('%H:%M'),
        )

    @admin.display(description="Kech?", ordering='is_late')
    def late_badge(self, obj):
        if obj.is_late:
            return badge("Kechikkan", '#ef4444', '⏰')
        return badge("Vaqtida", '#10b981', '✓')

    @admin.display(description="Ball")
    def score_badge(self, obj):
        if obj.score is None:
            return status_dot("Baholanmagan", "#f59e0b")
        return format_html(
            '<div style="font-weight:700;font-size:15px;color:#4338ca;">'
            '{}<span style="font-size:11px;color:#94a3b8;">/{}</span>'
            '</div>',
            obj.score, obj.homework.max_score
        )

    @admin.display(description="Baho")
    def grade_display(self, obj):
        if obj.score is None:
            return "—"
        return badge(
            obj.grade_letter,
            obj.grade_color,
            '🏆'
        )

    @admin.display(description="Holat")
    def status_badge(self, obj):
        colors = {
            'pending': '#f59e0b', 'graded': '#10b981',
            'late': '#ef4444', 'resubmit': '#8b5cf6',
            'rejected': '#dc2626',
        }
        icons = {
            'pending': '⏳', 'graded': '✅',
            'late': '⏰', 'resubmit': '🔄',
            'rejected': '❌',
        }
        return badge(
            obj.get_status_display(),
            colors.get(obj.status, '#6b7280'),
            icons.get(obj.status, '')
        )

    @admin.action(description="✅ Baholangan deb belgilash")
    def mark_graded(self, request, queryset):
        updated = queryset.update(status='graded')
        self.message_user(request, f"✅ {updated} ta topshiriq baholandi")

    @admin.action(description="📥 CSV eksport")
    def export_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="submissions.csv"'
        response.write('\ufeff')
        writer = csv.writer(response)
        writer.writerow([
            'Talaba', 'Telefon', 'Vazifa', 'Topshirildi',
            'Ball', 'Foiz', 'Baho', 'Kechikkan',
        ])
        for sub in queryset:
            writer.writerow([
                sub.student.user.get_full_name(),
                sub.student.user.phone_number,
                sub.homework.title,
                sub.submitted_at.strftime('%Y-%m-%d %H:%M'),
                sub.score or '',
                f"{sub.percent}%" if sub.score else '',
                sub.grade_letter if sub.score else '',
                'Ha' if sub.is_late else 'Yo‘q',
            ])
        return response


# ═══════════════════════════════════════════════════════════════
# 8. TEST
# ═══════════════════════════════════════════════════════════════

class QuestionInline(admin.StackedInline):
    model = Question
    extra = 0
    show_change_link = True
    fields = (
        'order', 'question_type', 'text',
        'points', 'difficulty',
    )
    classes = ('collapse',)


@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = (
        'title_link', 'course_display', 'difficulty_badge',
        'questions_count', 'duration_badge',
        'attempts_badge', 'success_display', 'is_active'
    )
    list_filter = (
        'difficulty', 'is_active', 'is_free', 'is_practice',
        'course', 'created_at',
    )
    search_fields = ('title', 'description')
    autocomplete_fields = (
        'course', 'lesson', 'category', 'created_by',
    )
    inlines = [QuestionInline]
    date_hierarchy = 'created_at'
    list_per_page = 20
    save_on_top = True

    fieldsets = (
        ('Asosiy', {
            'fields': (
                'course', 'lesson', 'category',
                'title', 'description', 'instructions',
                'difficulty', 'created_by',
            )
        }),
        ('Sozlamalar', {
            'fields': (
                'duration_minutes', 'passing_score', 'max_attempts',
                'shuffle_questions', 'shuffle_options',
                'show_correct_answers', 'show_results_immediately',
                'allow_back', 'allow_skip',
            )
        }),
        ('Mukofotlar', {
            'fields': ('coins_reward', 'xp_reward')
        }),
        ('Holat', {
            'fields': ('is_active', 'is_free', 'is_practice')
        }),
        ('Statistika', {
            'fields': (
                'attempts_count', 'passes_count', 'average_score',
            ),
            'classes': ('collapse',)
        }),
    )

    readonly_fields = (
        'attempts_count', 'passes_count', 'average_score',
        'created_at', 'updated_at',
    )

    actions = ['activate_quizzes', 'deactivate_quizzes']

    @admin.display(description="Test", ordering='title')
    def title_link(self, obj):
        url = reverse('admin:courses_quiz_change', args=[obj.pk])
        return format_html(
            '<a href="{}" style="color:#4338ca;font-weight:600;'
            'text-decoration:none;">{}</a>',
            url, obj.title[:50]
        )

    @admin.display(description="Kurs")
    def course_display(self, obj):
        if not obj.course:
            return "—"
        return format_html(
            '<div style="font-size:12px;color:#64748b;">{}</div>',
            obj.course.title[:30]
        )

    @admin.display(description="Qiyinlik")
    def difficulty_badge(self, obj):
        colors = {
            'easy': '#10b981', 'medium': '#f59e0b',
            'hard': '#ef4444', 'expert': '#8b5cf6',
        }
        icons = {
            'easy': '🟢', 'medium': '🟡',
            'hard': '🔴', 'expert': '💎',
        }
        return badge(
            obj.get_difficulty_display(),
            colors.get(obj.difficulty, '#6b7280'),
            icons.get(obj.difficulty, '')
        )

    @admin.display(description="Savollar")
    def questions_count(self, obj):
        return format_html(
            '<div style="font-weight:600;color:#4338ca;">{}</div>',
            obj.total_questions
        )

    @admin.display(description="Vaqt")
    def duration_badge(self, obj):
        return badge(f"{obj.duration_minutes} daq", '#06b6d4', '⏱')

    @admin.display(description="Urinishlar")
    def attempts_badge(self, obj):
        return format_html(
            '<div style="font-size:13px;">'
            '<span style="font-weight:600;color:#4338ca;">{}</span>'
            '<span style="font-size:11px;color:#94a3b8;"> / {}</span>'
            '</div>',
            obj.passes_count, obj.attempts_count
        )

    @admin.display(description="Muvaffaqiyat")
    def success_display(self, obj):
        pct = obj.success_rate
        if pct == 0:
            return "—"
        color = '#10b981' if pct >= 70 else \
            '#f59e0b' if pct >= 40 else '#ef4444'
        return progress_bar(pct, color, 60)

    @admin.action(description="✅ Aktivlashtirish")
    def activate_quizzes(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"✅ {updated} ta test aktivlashtirildi")

    @admin.action(description="🚫 O‘chirish")
    def deactivate_quizzes(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"🚫 {updated} ta test o‘chirildi")


# ═══════════════════════════════════════════════════════════════
# 9. SAVOL
# ═══════════════════════════════════════════════════════════════

class AnswerOptionInline(admin.TabularInline):
    model = AnswerOption
    extra = 4
    min_num = 2
    max_num = 8
    fields = ('order', 'text', 'is_correct', 'match_text')


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'text_preview', 'quiz_display',
        'type_badge', 'points_badge', 'order',
        'options_count_badge'
    )
    list_filter = ('question_type', 'difficulty', 'quiz')
    search_fields = ('text', 'quiz__title')
    autocomplete_fields = ('quiz',)
    inlines = [AnswerOptionInline]
    ordering = ('quiz', 'order')
    list_per_page = 30

    fieldsets = (
        ('Asosiy', {
            'fields': ('quiz', 'question_type', 'text', 'order')
        }),
        ('Media', {
            'fields': ('image', 'video_url')
        }),
        ('Ball', {
            'fields': ('points', 'difficulty')
        }),
        ('Matnli javob', {
            'fields': ('correct_text', 'number_tolerance'),
            'classes': ('collapse',)
        }),
        ('Raqamli javob', {
            'fields': ('correct_number',),
            'classes': ('collapse',)
        }),
        ('Kod javobi', {
            'fields': (
                'code_language', 'starter_code', 'expected_output',
            ),
            'classes': ('collapse',)
        }),
        ('Tushuntirish', {
            'fields': ('explanation', 'hint'),
            'classes': ('collapse',)
        }),
    )

    @admin.display(description="Savol")
    def text_preview(self, obj):
        return format_html(
            '<div style="font-weight:500;">{}</div>',
            obj.text[:70] + ('…' if len(obj.text) > 70 else '')
        )

    @admin.display(description="Test")
    def quiz_display(self, obj):
        return format_html(
            '<div style="font-size:12px;color:#64748b;">{}</div>',
            obj.quiz.title[:30]
        )

    @admin.display(description="Tur")
    def type_badge(self, obj):
        colors = {
            'single': '#6366f1', 'multiple': '#8b5cf6',
            'true_false': '#10b981', 'text': '#06b6d4',
            'number': '#f59e0b', 'matching': '#ec4899',
            'ordering': '#f97316', 'code': '#ef4444',
        }
        return badge(
            obj.get_question_type_display(),
            colors.get(obj.question_type, '#6b7280')
        )

    @admin.display(description="Ball", ordering='points')
    def points_badge(self, obj):
        return format_html(
            '<span style="font-weight:700;color:#4338ca;">{}</span>',
            obj.points
        )

    @admin.display(description="Variantlar")
    def options_count_badge(self, obj):
        count = obj.options.count()
        color = '#10b981' if count >= 2 else '#ef4444'
        return badge(str(count), color)


# ═══════════════════════════════════════════════════════════════
# 10. JAVOB VARIANTI
# ═══════════════════════════════════════════════════════════════

@admin.register(AnswerOption)
class AnswerOptionAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'text_preview', 'question_display',
        'correct_badge', 'order'
    )
    list_filter = ('is_correct', 'question__quiz')
    search_fields = ('text', 'question__text')
    autocomplete_fields = ('question',)
    list_editable = ('order',)
    ordering = ('question', 'order')

    @admin.display(description="Javob")
    def text_preview(self, obj):
        return obj.text[:70]

    @admin.display(description="Savol")
    def question_display(self, obj):
        return format_html(
            '<div style="font-size:12px;color:#64748b;">{}</div>',
            obj.question.text[:40]
        )

    @admin.display(description="To‘g‘ri?", ordering='is_correct')
    def correct_badge(self, obj):
        if obj.is_correct:
            return badge("To‘g‘ri", '#10b981', '✓')
        return badge("Xato", '#94a3b8', '✗')


# ═══════════════════════════════════════════════════════════════
# 11. TEST URINISHI
# ═══════════════════════════════════════════════════════════════

@admin.register(QuizAttempt)
class QuizAttemptAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'student_display', 'quiz_display',
        'score_display', 'percent_display',
        'grade_badge', 'status_badge',
        'passed_badge', 'started_at'
    )
    list_filter = (
        'status', 'is_passed', 'quiz',
        'started_at', 'completed_at',
    )
    search_fields = (
        'student__user__phone_number',
        'student__user__first_name',
        'quiz__title',
    )
    autocomplete_fields = ('quiz', 'student')
    date_hierarchy = 'started_at'
    list_per_page = 30

    fieldsets = (
        ('Asosiy', {
            'fields': (
                'quiz', 'student', 'status',
                'attempt_number', 'started_at', 'completed_at',
                'time_spent_seconds',
            )
        }),
        ('Natija', {
            'fields': (
                'score', 'max_score',
                'correct_count', 'wrong_count', 'skipped_count',
                'is_passed',
            )
        }),
        ('Mukofotlar', {
            'fields': ('coins_awarded', 'xp_awarded')
        }),
        ('Qurilma', {
            'fields': ('ip_address', 'user_agent'),
            'classes': ('collapse',)
        }),
    )

    readonly_fields = (
        'started_at', 'completed_at',
        'created_at', 'updated_at',
    )

    @admin.display(description="Talaba")
    def student_display(self, obj):
        return format_html(
            '<div style="font-size:12px;font-weight:600;">{}</div>',
            obj.student.user.get_full_name()[:30]
        )

    @admin.display(description="Test")
    def quiz_display(self, obj):
        return format_html(
            '<div style="font-size:12px;color:#64748b;">{}</div>',
            obj.quiz.title[:30]
        )

    @admin.display(description="Ball")
    def score_display(self, obj):
        return format_html(
            '<span style="font-weight:700;color:#4338ca;">{}</span>'
            '<span style="font-size:11px;color:#94a3b8;"> / {}</span>',
            obj.score, obj.max_score
        )

    @admin.display(description="Foiz")
    def percent_display(self, obj):
        pct = obj.percent
        color = '#10b981' if pct >= 70 else \
            '#f59e0b' if pct >= 50 else '#ef4444'
        return format_html(
            '<span style="font-weight:700;color:{};">{}%</span>',
            color, pct
        )

    @admin.display(description="Baho")
    def grade_badge(self, obj):
        colors = {
            'A': '#10b981', 'B': '#3b82f6',
            'C': '#f59e0b', 'D': '#f97316', 'F': '#ef4444',
        }
        return badge(obj.grade_letter, colors.get(obj.grade_letter, '#6b7280'))

    @admin.display(description="Holat")
    def status_badge(self, obj):
        colors = {
            'in_progress': '#f59e0b', 'completed': '#10b981',
            'abandoned': '#94a3b8', 'expired': '#ef4444',
        }
        return badge(
            obj.get_status_display(),
            colors.get(obj.status, '#6b7280')
        )

    @admin.display(description="O‘tgan?", ordering='is_passed')
    def passed_badge(self, obj):
        if obj.is_passed:
            return badge("O‘tdi", '#10b981', '🎉')
        return badge("O‘tmadi", '#ef4444', '😔')


# ═══════════════════════════════════════════════════════════════
# 12. GURUH
# ═══════════════════════════════════════════════════════════════

class GroupMemberInline(admin.TabularInline):
    model = GroupMember
    extra = 0
    autocomplete_fields = ('student',)
    fields = ('student', 'role', 'joined_at', 'is_active')


# # # @admin.register(StudentGroup)
class StudentGroupAdmin(admin.ModelAdmin):
    list_display = (
        'group_badge', 'name_link', 'course_display',
        'teacher_display', 'schedule_display',
        'students_count_badge', 'capacity_display',
        'status_badge'
    )
    list_filter = ('status', 'course', 'created_at')
    search_fields = ('name', 'code', 'description')
    autocomplete_fields = ('course', 'teacher', 'assistant')
    filter_horizontal = ('students',)
    # # inlines = [GroupMemberInline]  # courses.StudentGroup endi ishlatilmaydi
    date_hierarchy = 'created_at'
    list_per_page = 20
    save_on_top = True

    fieldsets = (
        ('Asosiy', {
            'fields': ('name', 'code', 'description')
        }),
        ('O‘qituvchilar', {
            'fields': ('teacher', 'assistant')
        }),
        ('Kurs va talabalar', {
            'fields': ('course', 'students', 'max_students')
        }),
        ('Sanalar', {
            'fields': ('start_date', 'end_date')
        }),
        ('Jadval', {
            'fields': ('schedule', 'room')
        }),
        ('Telegram', {
            'fields': ('telegram_group_id', 'telegram_invite_link'),
            'classes': ('collapse',)
        }),
        ('Dizayn', {
            'fields': ('color', 'cover_image'),
            'classes': ('collapse',)
        }),
        ('Holat', {
            'fields': ('status',)
        }),
    )

    readonly_fields = ('created_at', 'updated_at')

    actions = ['activate_groups', 'pause_groups', 'export_students_csv']

    @admin.display(description="Guruh")
    def group_badge(self, obj):
        return format_html(
            '<div style="width:48px;height:48px;border-radius:12px;'
            'background:linear-gradient(135deg,{}cc,{});'
            'display:flex;align-items:center;justify-content:center;'
            'color:#fff;font-weight:800;font-size:16px;'
            'box-shadow:0 4px 12px {}30;">{}</div>',
            obj.color, obj.color, obj.color,
            obj.name[:2].upper()
        )

    @admin.display(description="Nomi", ordering='name')
    def name_link(self, obj):
        url = reverse('admin:courses_studentgroup_change', args=[obj.pk])
        return format_html(
            '<a href="{}" style="color:#4338ca;font-weight:600;'
            'text-decoration:none;">{}</a>'
            '<div style="font-size:11px;color:#94a3b8;">{}</div>',
            url, obj.name, obj.code
        )

    @admin.display(description="Kurs")
    def course_display(self, obj):
        if not obj.course:
            return "—"
        return format_html(
            '<div style="font-size:12px;">{}</div>',
            obj.course.title[:30]
        )

    @admin.display(description="O‘qituvchi")
    def teacher_display(self, obj):
        if not obj.teacher:
            return status_dot("Belgilanmagan", "#dc2626")
        return format_html(
            '<div style="font-size:12px;">{}</div>',
            obj.teacher.get_full_name() or obj.teacher.phone_number
        )

    @admin.display(description="Jadval")
    def schedule_display(self, obj):
        return format_html(
            '<div style="font-size:11px;color:#64748b;">{}</div>',
            obj.schedule_display
        )

    @admin.display(description="Talabalar")
    def students_count_badge(self, obj):
        count = obj.students_count
        max_count = obj.max_students
        color = '#10b981' if count < max_count else '#ef4444'
        return format_html(
            '<span style="font-weight:700;color:{};font-size:14px;">'
            '{}</span>'
            '<span style="font-size:11px;color:#94a3b8;"> / {}</span>',
            color, count, max_count
        )

    @admin.display(description="To‘lish")
    def capacity_display(self, obj):
        pct = obj.capacity_percent
        color = '#ef4444' if pct >= 90 else \
            '#f59e0b' if pct >= 70 else '#10b981'
        return progress_bar(pct, color, 60)

    @admin.display(description="Holat")
    def status_badge(self, obj):
        colors = {
            'active': '#10b981', 'paused': '#f59e0b',
            'finished': '#6366f1', 'archived': '#94a3b8',
        }
        return badge(
            obj.get_status_display(),
            colors.get(obj.status, '#6b7280')
        )

    @admin.action(description="✅ Aktivlashtirish")
    def activate_groups(self, request, queryset):
        updated = queryset.update(status='active')
        self.message_user(request, f"✅ {updated} ta guruh aktivlashtirildi")

    @admin.action(description="⏸ To‘xtatish")
    def pause_groups(self, request, queryset):
        updated = queryset.update(status='paused')
        self.message_user(request, f"⏸ {updated} ta guruh to‘xtatildi")

    @admin.action(description="📥 Talabalar CSV")
    def export_students_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="group_students.csv"'
        response.write('\ufeff')
        writer = csv.writer(response)
        writer.writerow(['Guruh', 'Talaba', 'Telefon', 'Holat'])
        for group in queryset:
            for student in group.students.all():
                writer.writerow([
                    group.name,
                    student.user.get_full_name(),
                    student.user.phone_number,
                    student.get_status_display(),
                ])
        return response


# ═══════════════════════════════════════════════════════════════
# 13. GURUH A’ZOSI
# ═══════════════════════════════════════════════════════════════

@admin.register(GroupMember)
class GroupMemberAdmin(admin.ModelAdmin):
    list_display = (
        'student_display', 'group_display', 'role_badge',
        'joined_at', 'is_active'
    )
    list_filter = ('role', 'is_active', 'group')
    search_fields = (
        'student__user__phone_number',
        'student__user__first_name',
        'group__name',
    )
    autocomplete_fields = ('group', 'student')
    date_hierarchy = 'joined_at'

    @admin.display(description="Talaba")
    def student_display(self, obj):
        return obj.student.user.get_full_name()

    @admin.display(description="Guruh")
    def group_display(self, obj):
        return obj.group.name

    @admin.display(description="Roli")
    def role_badge(self, obj):
        colors = {
            'student': '#6366f1',
            'leader': '#f59e0b',
            'assistant': '#10b981',
        }
        icons = {
            'student': '👤', 'leader': '👑', 'assistant': '🤝',
        }
        return badge(
            obj.get_role_display(),
            colors.get(obj.role, '#6b7280'),
            icons.get(obj.role, '')
        )


# ═══════════════════════════════════════════════════════════════
# 14. YOZILISH
# ═══════════════════════════════════════════════════════════════

@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = (
        'student_display', 'course_display',
        'status_badge', 'progress_display',
        'score_display', 'paid_badge',
        'certificate_badge', 'enrolled_at'
    )
    list_filter = (
        'status', 'is_passed', 'is_paid', 'certificate_issued',
        'course', 'enrolled_at',
    )
    search_fields = (
        'student__user__phone_number',
        'student__user__first_name',
        'course__title',
    )
    autocomplete_fields = ('student', 'course', 'group')
    date_hierarchy = 'enrolled_at'
    list_per_page = 30
    save_on_top = True

    fieldsets = (
        ('Asosiy', {
            'fields': ('student', 'course', 'group', 'status')
        }),
        ('Sanalar', {
            'fields': ('enrolled_at', 'started_at', 'completed_at')
        }),
        ('Progress', {
            'fields': (
                'progress_percent', 'lessons_completed',
                'homework_submitted', 'homework_graded',
            )
        }),
        ('Natija', {
            'fields': (
                'total_score', 'average_score',
                'grade', 'is_passed',
            )
        }),
        ('To‘lov', {
            'fields': ('is_paid', 'paid_amount')
        }),
        ('Sertifikat', {
            'fields': (
                'certificate_issued', 'certificate_file', 'certificate_id',
            )
        }),
    )

    readonly_fields = ('enrolled_at', 'created_at', 'updated_at')

    actions = ['mark_passed', 'issue_certificates', 'export_csv']

    @admin.display(description="Talaba")
    def student_display(self, obj):
        return format_html(
            '<div style="font-size:12px;font-weight:600;">{}</div>'
            '<div style="font-size:10px;color:#94a3b8;">{}</div>',
            obj.student.user.get_full_name()[:25],
            obj.student.user.phone_number,
        )

    @admin.display(description="Kurs")
    def course_display(self, obj):
        return format_html(
            '<div style="font-size:12px;">{}</div>',
            obj.course.title[:30]
        )

    @admin.display(description="Holat")
    def status_badge(self, obj):
        colors = {
            'pending': '#f59e0b', 'active': '#10b981',
            'paused': '#f97316', 'completed': '#6366f1',
            'dropped': '#ef4444', 'expired': '#94a3b8',
        }
        return badge(
            obj.get_status_display(),
            colors.get(obj.status, '#6b7280')
        )

    @admin.display(description="Progress")
    def progress_display(self, obj):
        pct = obj.progress
        color = '#10b981' if pct >= 70 else \
            '#f59e0b' if pct >= 40 else '#ef4444'
        return progress_bar(pct, color, 80)

    @admin.display(description="Ball")
    def score_display(self, obj):
        if not obj.total_score:
            return "—"
        return format_html(
            '<div style="font-weight:700;color:#4338ca;">{}</div>'
            '<div style="font-size:11px;color:#94a3b8;">'
            'o‘rt: {}</div>',
            obj.total_score, obj.average_score
        )

    @admin.display(description="To‘langan?")
    def paid_badge(self, obj):
        if obj.is_paid:
            return badge("To‘langan", '#10b981', '💰')
        return badge("Kutilmoqda", '#f59e0b', '⏳')

    @admin.display(description="Sertifikat")
    def certificate_badge(self, obj):
        if obj.certificate_issued:
            return badge("Berilgan", '#f59e0b', '🏆')
        return "—"

    @admin.action(description="✅ O‘tgan deb belgilash")
    def mark_passed(self, request, queryset):
        updated = queryset.update(is_passed=True)
        self.message_user(request, f"✅ {updated} ta yozilish o‘tgan deb belgilandi")

    @admin.action(description="🏆 Sertifikat berish")
    def issue_certificates(self, request, queryset):
        count = 0
        for enrollment in queryset.filter(is_passed=True, certificate_issued=False):
            try:
                enrollment.issue_certificate()
                count += 1
            except Exception as e:
                self.message_user(
                    request, f"❌ {enrollment}: {e}", messages.ERROR
                )
        self.message_user(
            request, f"🏆 {count} ta sertifikat berildi", messages.SUCCESS
        )

    @admin.action(description="📥 CSV eksport")
    def export_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="enrollments.csv"'
        response.write('\ufeff')
        writer = csv.writer(response)
        writer.writerow([
            'Talaba', 'Telefon', 'Kurs', 'Status',
            'Progress %', 'Ball', 'O‘rt ball', 'Sertifikat', 'Sana'
        ])
        for e in queryset:
            writer.writerow([
                e.student.user.get_full_name(),
                e.student.user.phone_number,
                e.course.title,
                e.get_status_display(),
                float(e.progress_percent),
                e.total_score,
                float(e.average_score),
                'Ha' if e.certificate_issued else 'Yo‘q',
                e.enrolled_at.strftime('%Y-%m-%d'),
            ])
        return response


# ═══════════════════════════════════════════════════════════════
# 15. DAVOMAT
# ═══════════════════════════════════════════════════════════════

@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = (
        'student_display', 'lesson_display',
        'status_badge', 'marked_at',
        'marked_by_display'
    )
    list_filter = ('status', 'marked_at', 'lesson__course')
    search_fields = (
        'student__user__phone_number',
        'student__user__first_name',
        'lesson__title',
    )
    autocomplete_fields = ('lesson', 'student', 'marked_by')
    date_hierarchy = 'marked_at'
    list_per_page = 40

    fieldsets = (
        ('Asosiy', {
            'fields': ('lesson', 'student', 'status')
        }),
        ('Vaqt', {
            'fields': ('check_in_time', 'check_out_time')
        }),
        ('Meta', {
            'fields': ('marked_by', 'notes')
        }),
    )

    readonly_fields = ('marked_at', 'created_at', 'updated_at')

    @admin.display(description="Talaba")
    def student_display(self, obj):
        return obj.student.user.get_full_name()

    @admin.display(description="Dars")
    def lesson_display(self, obj):
        return obj.lesson.title[:40]

    @admin.display(description="Holat")
    def status_badge(self, obj):
        colors = {
            'present': '#10b981', 'absent': '#ef4444',
            'late': '#f59e0b', 'excused': '#6366f1',
            'online': '#06b6d4',
        }
        icons = {
            'present': '✅', 'absent': '❌',
            'late': '⏰', 'excused': '📝',
            'online': '💻',
        }
        return badge(
            obj.get_status_display(),
            colors.get(obj.status, '#6b7280'),
            icons.get(obj.status, '')
        )

    @admin.display(description="Kim belgiladi")
    def marked_by_display(self, obj):
        if not obj.marked_by:
            return "—"
        return obj.marked_by.get_full_name()


# ═══════════════════════════════════════════════════════════════
# 16. SHARH
# ═══════════════════════════════════════════════════════════════

@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = (
        'course_display', 'student_display',
        'rating_stars', 'title_preview',
        'approved_badge', 'created_at'
    )
    list_filter = ('rating', 'is_approved', 'created_at', 'course')
    search_fields = (
        'course__title',
        'student__user__first_name',
        'comment',
    )
    autocomplete_fields = ('course', 'student')
    date_hierarchy = 'created_at'
    list_per_page = 30

    fieldsets = (
        ('Asosiy', {
            'fields': ('course', 'student', 'rating')
        }),
        ('Sharh', {
            'fields': ('title', 'comment')
        }),
        ('Meta', {
            'fields': ('is_anonymous', 'is_approved', 'helpful_count')
        }),
    )

    readonly_fields = ('created_at', 'updated_at')

    actions = ['approve_reviews', 'reject_reviews']

    @admin.display(description="Kurs")
    def course_display(self, obj):
        return format_html(
            '<div style="font-size:12px;font-weight:500;">{}</div>',
            obj.course.title[:40]
        )

    @admin.display(description="Talaba")
    def student_display(self, obj):
        if obj.is_anonymous:
            return badge("Anonim", '#94a3b8', '🕵')
        return obj.student.user.get_full_name()

    @admin.display(description="Reyting", ordering='rating')
    def rating_stars(self, obj):
        color = '#10b981' if obj.rating >= 4 else \
            '#f59e0b' if obj.rating >= 3 else '#ef4444'
        return format_html(
            '<span style="color:{};font-size:14px;">{}</span>',
            color, obj.stars_display
        )

    @admin.display(description="Sarlavha")
    def title_preview(self, obj):
        return (obj.title[:40] or obj.comment[:40])

    @admin.display(description="Holat", ordering='is_approved')
    def approved_badge(self, obj):
        if obj.is_approved:
            return badge("Tasdiqlangan", '#10b981', '✓')
        return badge("Kutilmoqda", '#f59e0b', '⏳')

    @admin.action(description="✅ Tasdiqlash")
    def approve_reviews(self, request, queryset):
        updated = queryset.update(is_approved=True)
        self.message_user(request, f"✅ {updated} ta sharh tasdiqlandi")

    @admin.action(description="❌ Rad etish")
    def reject_reviews(self, request, queryset):
        updated = queryset.update(is_approved=False)
        self.message_user(request, f"❌ {updated} ta sharh rad etildi")


# ═══════════════════════════════════════════════════════════════
# 17. SERTIFIKAT
# ═══════════════════════════════════════════════════════════════

@admin.register(Certificate)
class CertificateAdmin(admin.ModelAdmin):
    list_display = (
        'certificate_number_badge', 'student_display',
        'course_display', 'grade_badge',
        'issued_date', 'verified_badge'
    )
    list_filter = ('grade', 'is_verified', 'issued_date')
    search_fields = (
        'certificate_number',
        'enrollment__student__user__first_name',
        'enrollment__course__title',
    )
    autocomplete_fields = ('enrollment',)
    date_hierarchy = 'issued_date'
    list_per_page = 30

    fieldsets = (
        ('Asosiy', {
            'fields': (
                'enrollment', 'certificate_number',
                'verification_code',
            )
        }),
        ('Sanalar', {
            'fields': ('issued_date', 'expiry_date')
        }),
        ('Natija', {
            'fields': ('grade', 'score')
        }),
        ('Fayl', {
            'fields': ('file',)
        }),
        ('Holat', {
            'fields': ('is_verified',)
        }),
    )

    readonly_fields = (
        'certificate_number', 'verification_code',
        'issued_date', 'created_at', 'updated_at',
    )

    @admin.display(description="Sertifikat №")
    def certificate_number_badge(self, obj):
        return badge(obj.certificate_number, '#6366f1', '🏆')

    @admin.display(description="Talaba")
    def student_display(self, obj):
        return obj.enrollment.student.user.get_full_name()

    @admin.display(description="Kurs")
    def course_display(self, obj):
        return format_html(
            '<div style="font-size:12px;">{}</div>',
            obj.enrollment.course.title[:30]
        )

    @admin.display(description="Baho")
    def grade_badge(self, obj):
        if not obj.grade:
            return "—"
        colors = {
            'A': '#10b981', 'B': '#3b82f6',
            'C': '#f59e0b', 'D': '#f97316', 'F': '#ef4444',
        }
        return badge(obj.grade, colors.get(obj.grade, '#6b7280'))

    @admin.display(description="Tasdiqlangan?")
    def verified_badge(self, obj):
        if obj.is_verified:
            return badge("Tasdiqlangan", '#10b981', '✓')
        return badge("Tasdiqlanmagan", '#ef4444', '✗')


# ═══════════════════════════════════════════════════════════════
# 18. KURS MODULI
# ═══════════════════════════════════════════════════════════════

@admin.register(CourseModule)
class CourseModuleAdmin(admin.ModelAdmin):
    list_display = (
        'order_badge', 'title', 'course_display',
        'is_published'
    )
    list_filter = ('is_published', 'course')
    search_fields = ('title', 'description', 'course__title')
    autocomplete_fields = ('course',)
    list_editable = ('is_published',)
    ordering = ('course', 'order')

    @admin.display(description="Tartib", ordering='order')
    def order_badge(self, obj):
        return badge(f"#{obj.order}", '#6366f1')

    @admin.display(description="Kurs")
    def course_display(self, obj):
        return obj.course.title[:40]


# ═══════════════════════════════════════════════════════════════
# 19. KURS FAQ
# ═══════════════════════════════════════════════════════════════

@admin.register(CourseFAQ)
class CourseFAQAdmin(admin.ModelAdmin):
    list_display = (
        'order_badge', 'question_preview',
        'course_display', 'views_display', 'is_active'
    )
    list_filter = ('is_active', 'course')
    search_fields = ('question', 'answer', 'course__title')
    autocomplete_fields = ('course',)
    list_editable = ('is_active',)
    ordering = ('course', 'order')

    @admin.display(description="#")
    def order_badge(self, obj):
        return badge(f"#{obj.order}", '#8b5cf6')

    @admin.display(description="Savol")
    def question_preview(self, obj):
        return obj.question[:70]

    @admin.display(description="Kurs")
    def course_display(self, obj):
        return obj.course.title[:30]

    @admin.display(description="Ko‘rishlar")
    def views_display(self, obj):
        return format_html(
            '<span style="font-weight:600;color:#4338ca;">{}</span>',
            obj.views_count
        )


# ═══════════════════════════════════════════════════════════════
# 20. E’LON
# ═══════════════════════════════════════════════════════════════

@admin.register(CourseAnnouncement)
class CourseAnnouncementAdmin(admin.ModelAdmin):
    list_display = (
        'title_preview', 'course_display', 'group_display',
        'author_display', 'is_pinned', 'is_published', 'publish_at'   # ← qo'shildi
    )
    list_filter = ('is_pinned', 'is_published', 'publish_at', 'course')
    search_fields = ('title', 'content', 'course__title')
    autocomplete_fields = ('course', 'group', 'author')
    date_hierarchy = 'publish_at'
    list_editable = ('is_pinned', 'is_published') 
    @admin.display(description="Sarlavha")
    def title_preview(self, obj):
        return obj.title[:60]

    @admin.display(description="Kurs")
    def course_display(self, obj):
        return obj.course.title[:30]

    @admin.display(description="Guruh")
    def group_display(self, obj):
        return obj.group.name if obj.group else "Barchasi"

    @admin.display(description="Muallif")
    def author_display(self, obj):
        return obj.author.get_full_name()

    @admin.display(description="Qadalgan?")
    def pinned_badge(self, obj):
        if obj.is_pinned:
            return badge("Qadalgan", '#f59e0b', '📌')
        return "—"

    @admin.display(description="E’lon qilingan?")
    def published_badge(self, obj):
        if obj.is_published:
            return badge("E’lon qilingan", '#10b981', '✓')
        return badge("Qoralama", '#94a3b8', '📝')


# ═══════════════════════════════════════════════════════════════
# 21. KURS RESURSI
# ═══════════════════════════════════════════════════════════════

@admin.register(CourseResource)
class CourseResourceAdmin(admin.ModelAdmin):
    list_display = (
        'type_badge', 'title_preview', 'course_display',
        'free_badge', 'downloads_display', 'created_at'
    )
    list_filter = ('resource_type', 'is_free', 'course')
    search_fields = ('title', 'description', 'course__title')
    autocomplete_fields = ('course', 'lesson')
    date_hierarchy = 'created_at'
    list_per_page = 30

    @admin.display(description="Turi")
    def type_badge(self, obj):
        colors = {
            'pdf': '#ef4444', 'doc': '#3b82f6',
            'slide': '#f59e0b', 'code': '#10b981',
            'link': '#06b6d4', 'book': '#8b5cf6',
            'video': '#ec4899', 'audio': '#14b8a6',
            'other': '#6b7280',
        }
        icons = {
            'pdf': '📄', 'doc': '📝', 'slide': '📊',
            'code': '💻', 'link': '🔗', 'book': '📖',
            'video': '🎬', 'audio': '🎵', 'other': '📦',
        }
        return badge(
            obj.get_resource_type_display().upper(),
            colors.get(obj.resource_type, '#6b7280'),
            icons.get(obj.resource_type, '')
        )

    @admin.display(description="Sarlavha")
    def title_preview(self, obj):
        return obj.title[:50]

    @admin.display(description="Kurs")
    def course_display(self, obj):
        return obj.course.title[:30]

    @admin.display(description="Bepul?")
    def free_badge(self, obj):
        if obj.is_free:
            return badge("Bepul", '#10b981', '🎁')
        return badge("Pullik", '#f59e0b', '💰')

    @admin.display(description="Yuklab olishlar")
    def downloads_display(self, obj):
        return format_html(
            '<span style="font-weight:600;color:#4338ca;">{}</span>',
            obj.download_count
        )


# ═══════════════════════════════════════════════════════════════
# 22. DARS JURNALI
# ═══════════════════════════════════════════════════════════════

@admin.register(LessonLog)
class LessonLogAdmin(admin.ModelAdmin):
    list_display = (
        'lesson_display', 'teacher_display',
        'lesson_date', 'homework_given_badge',
        'approved_badge'
    )
    list_filter = ('homework_given', 'is_approved', 'lesson_date')
    search_fields = (
        'lesson__title',
        'teacher__first_name',
        'topics_covered',
    )
    autocomplete_fields = ('lesson', 'teacher', 'approved_by')
    date_hierarchy = 'lesson_date'
    list_per_page = 30

    fieldsets = (
        ('Asosiy', {
            'fields': ('lesson', 'teacher', 'lesson_date')
        }),
        ('Mazmun', {
            'fields': (
                'topics_covered', 'notes', 'next_lesson_plan',
            )
        }),
        ('Uyga vazifa', {
            'fields': ('homework_given',)
        }),
        ('Tasdiqlash', {
            'fields': ('is_approved', 'approved_by', 'approved_at')
        }),
    )

    readonly_fields = ('approved_at', 'created_at', 'updated_at')

    @admin.display(description="Dars")
    def lesson_display(self, obj):
        return obj.lesson.title[:50]

    @admin.display(description="O‘qituvchi")
    def teacher_display(self, obj):
        return obj.teacher.get_full_name()

    @admin.display(description="Uyga vazifa")
    def homework_given_badge(self, obj):
        if obj.homework_given:
            return badge("Berildi", '#10b981', '📝')
        return badge("Berilmadi", '#94a3b8', '❌')

    @admin.display(description="Tasdiqlangan?")
    def approved_badge(self, obj):
        if obj.is_approved:
            return badge("Tasdiqlangan", '#10b981', '✓')
        return badge("Kutilmoqda", '#f59e0b', '⏳')


# ═══════════════════════════════════════════════════════════════
# 23. AUDIT LOG
# ═══════════════════════════════════════════════════════════════

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        'created_at', 'user_display', 'action_badge',
        'object_display', 'description_preview'
    )
    list_filter = ('action', 'created_at')
    search_fields = (
        'user__phone_number',
        'description',
        'object_id',
    )
    date_hierarchy = 'created_at'
    list_per_page = 50
    readonly_fields = (
        'user', 'action', 'content_type', 'object_id',
        'description', 'changes', 'ip_address', 'user_agent',
        'created_at', 'updated_at',
    )

    @admin.display(description="Foydalanuvchi")
    def user_display(self, obj):
        if not obj.user:
            return "—"
        return obj.user.get_full_name() or obj.user.phone_number

    @admin.display(description="Harakat")
    def action_badge(self, obj):
        colors = {
            'create': '#10b981', 'update': '#3b82f6',
            'delete': '#ef4444', 'view': '#6366f1',
            'grade': '#f59e0b', 'send': '#8b5cf6',
            'approve': '#10b981', 'reject': '#ef4444',
        }
        return badge(
            obj.get_action_display(),
            colors.get(obj.action, '#6b7280')
        )

    @admin.display(description="Obyekt")
    def object_display(self, obj):
        if not obj.content_type:
            return "—"
        return f"{obj.content_type.model} #{obj.object_id}"

    @admin.display(description="Tavsif")
    def description_preview(self, obj):
        return obj.description[:60] if obj.description else "—"

    def has_add_permission(self, request):
        return False  # Audit log qo‘lda qo‘shib bo‘lmaydi

    def has_change_permission(self, request, obj=None):
        return False  # Faqat o‘qish

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser  # Faqat superuser o‘chira oladi

from .models import CourseListPageSettings
from django.contrib import admin


@admin.register(CourseListPageSettings)
class CourseListPageSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not CourseListPageSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    fieldsets = (
        ("📄 Sahifa sarlavhasi", {
            "fields": ("page_title", "page_subtitle", "page_icon",
                       "page_badge_text", "page_badge_icon",
                       "btn_create", "btn_create_icon", "btn_create_tooltip",
                       "btn_help", "btn_help_icon",
                       "btn_refresh", "btn_refresh_icon",
                       "btn_export", "btn_export_icon"),
        }),
        ("📊 Statistika", {
            "fields": (
                ("stat_total_label", "stat_total_icon", "stat_total_hint"),
                ("stat_published_label", "stat_published_icon", "stat_published_hint"),
                ("stat_draft_label", "stat_draft_icon", "stat_draft_hint"),
                ("stat_pending_label", "stat_pending_icon", "stat_pending_hint"),
                ("stat_archived_label", "stat_archived_icon", "stat_archived_hint"),
                ("stat_featured_label", "stat_featured_icon", "stat_featured_hint"),
                ("stat_students_label", "stat_students_icon", "stat_students_hint"),
                ("stat_lessons_label", "stat_lessons_icon", "stat_lessons_hint"),
                ("stat_months_label", "stat_months_icon", "stat_months_hint"),
                ("stat_avg_rating_label", "stat_avg_rating_icon", "stat_avg_rating_hint"),
            ),
            "classes": ("wide",),
        }),
        ("🔍 Qidiruv", {
            "fields": ("filter_search_label", "filter_search_placeholder",
                       "filter_search_icon", "filter_search_hint"),
        }),
        ("🎛️ Filtrlar", {
            "fields": (
                ("filter_btn_label", "filter_btn_icon", "filter_btn_active_badge"),
                ("filter_category_label", "filter_category_all"),
                ("filter_level_label", "filter_level_all"),
                ("filter_language_label", "filter_language_all"),
                ("filter_status_label", "filter_status_all"),
                ("filter_price_label", "filter_price_all",
                 "filter_price_free", "filter_price_paid"),
                ("filter_date_label", "filter_date_all",
                 "filter_date_today", "filter_date_week", "filter_date_month"),
                ("filter_sort_label", "filter_sort_newest", "filter_sort_oldest",
                 "filter_sort_title_az", "filter_sort_title_za",
                 "filter_sort_popular", "filter_sort_rating"),
                ("btn_search", "btn_search_icon"),
                ("btn_clear", "btn_clear_icon"),
                ("btn_apply", "btn_apply_icon"),
                ("btn_reset", "btn_reset_icon"),
                ("active_filters_label", "active_filters_clear"),
            ),
            "classes": ("wide",),
        }),
        ("👁️ Ko'rinish", {
            "fields": (("view_grid", "view_grid_icon"),
                       ("view_list", "view_list_icon"),
                       ("view_compact", "view_compact_icon"),
                       "view_switch_label"),
        }),
        ("⚡ Bulk amallar", {
            "fields": (
                ("bulk_label", "bulk_select_all"),
                ("bulk_publish", "bulk_publish_icon"),
                ("bulk_unpublish", "bulk_unpublish_icon"),
                ("bulk_feature", "bulk_feature_icon"),
                ("bulk_unfeature", "bulk_unfeature_icon"),
                ("bulk_archive", "bulk_archive_icon"),
                ("bulk_delete", "bulk_delete_icon"),
                ("bulk_cancel", "bulk_cancel_icon"),
                "bulk_confirm_text",
            ),
            "classes": ("wide", "collapse"),
        }),
        ("🏷️ Badgelar", {
            "fields": (
                ("badge_published", "badge_draft", "badge_pending", "badge_archived"),
                ("badge_featured", "badge_free", "badge_paid",
                 "badge_new", "badge_hot"),
                ("badge_new_days", "badge_hot_threshold"),
            ),
        }),
        ("📦 Kurs kartasi", {
            "fields": (
                ("card_teacher_icon", "card_teacher_label"),
                ("card_duration_label", "card_duration_suffix"),
                ("card_level_label", "card_lang_label"),
                ("card_tag_icon", "card_price_label"),
                ("card_no_teacher", "card_no_description", "card_no_cover"),
                ("card_view_btn", "card_view_icon"),
                ("card_edit_btn", "card_edit_icon"),
                ("card_delete_btn", "card_delete_icon"),
                ("card_more_btn", "card_more_icon"),
                ("card_dropdown_view", "card_dropdown_edit",
                 "card_dropdown_duplicate", "card_dropdown_duplicate_icon",
                 "card_dropdown_publish", "card_dropdown_unpublish",
                 "card_dropdown_feature", "card_dropdown_unfeature",
                 "card_dropdown_archive", "card_dropdown_delete"),
                ("card_stat_months_icon", "card_stat_lessons_icon",
                 "card_stat_students_icon"),
            ),
            "classes": ("wide", "collapse"),
        }),
        ("📋 Jadval ustunlari", {
            "fields": ("table_col_select", "table_col_cover", "table_col_title",
                       "table_col_category", "table_col_teacher", "table_col_level",
                       "table_col_months", "table_col_lessons", "table_col_students",
                       "table_col_rating", "table_col_status", "table_col_actions"),
            "classes": ("wide", "collapse"),
        }),
        ("📭 Bo'sh holat", {
            "fields": ("empty_title", "empty_subtitle", "empty_icon",
                       "empty_cta", "empty_cta_icon",
                       "empty_search_title", "empty_search_subtitle",
                       "empty_search_icon", "empty_search_cta",
                       "empty_filtered_title", "empty_filtered_subtitle"),
        }),
        ("📄 Pagination", {
            "fields": ("pagination_prev_icon", "pagination_next_icon",
                       "pagination_first_icon", "pagination_last_icon",
                       "pagination_info",
                       "pagination_per_page", "pagination_per_page_options"),
        }),
        ("💬 Xabarlar", {
            "fields": ("msg_deleted", "msg_published", "msg_unpublish",
                       "msg_featured", "msg_unfeatured", "msg_archived",
                       "msg_duplicated", "msg_error", "msg_network_error",
                       "msg_loading", "msg_confirm_delete",
                       "msg_confirm_delete_extra", "msg_confirm_bulk_delete",
                       "msg_no_selection", "msg_duplicate_suffix"),
            "classes": ("wide", "collapse"),
        }),
        ("💡 Tooltip", {
            "fields": ("tooltip_view", "tooltip_edit", "tooltip_delete",
                       "tooltip_publish", "tooltip_unpublish",
                       "tooltip_feature", "tooltip_unfeature",
                       "tooltip_duplicate", "tooltip_more"),
            "classes": ("collapse",),
        }),
        ("⌨️ Klaviatura", {
            "fields": ("keyboard_hint_title", "keyboard_hint_new",
                       "keyboard_hint_select", "keyboard_hint_clear",
                       "keyboard_hint_search"),
            "classes": ("collapse",),
        }),
    )
# ═══════════════════════════════════════════════════════════════
# ADMIN SITE SOZLAMALARI
# ═══════════════════════════════════════════════════════════════

admin.site.site_header = "DIGION — Kurslar Boshqaruvi"
admin.site.site_title = "DIGION Admin"
admin.site.index_title = "Kurslar boshqaruv paneli"

# ═══════════════════════════════════════════════════════════════
# END
# ═══════════════════════════════════════════════════════════════


from .models import CourseFormPageSettings


@admin.register(CourseFormPageSettings)
class CourseFormPageSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not CourseFormPageSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    fieldsets = (
        ("🎨 Sahifa sarlavhasi", {
            "fields": (
                ("page_badge_create", "page_badge_edit", "page_badge_icon"),
                ("page_title_create", "page_title_edit", "page_icon"),
                ("page_subtitle_create", "page_subtitle_edit"),
            ),
        }),
        ("🔘 Tugmalar", {
            "fields": (
                ("btn_save", "btn_save_icon"),
                ("btn_save_and_new", "btn_save_and_new_icon"),
                ("btn_cancel", "btn_cancel_icon"),
                ("btn_reset", "btn_reset_icon"),
                ("btn_preview", "btn_preview_icon"),
                ("btn_back", "btn_back_icon"),
            ),
        }),
        ("📑 Bo‘lim sarlavhalari", {
            "fields": (
                ("sec_basic_title", "sec_basic_subtitle", "sec_basic_icon"),
                ("sec_media_title", "sec_media_subtitle", "sec_media_icon"),
                ("sec_teacher_title", "sec_teacher_subtitle", "sec_teacher_icon"),
                ("sec_dates_title", "sec_dates_subtitle", "sec_dates_icon"),
                ("sec_settings_title", "sec_settings_subtitle", "sec_settings_icon"),
                ("sec_price_title", "sec_price_subtitle", "sec_price_icon"),
                ("sec_advanced_title", "sec_advanced_subtitle", "sec_advanced_icon"),
                ("sec_seo_title", "sec_seo_subtitle", "sec_seo_icon"),
            ),
            "classes": ("wide", "collapse"),
        }),
        ("🏷 Maydon belgilari", {
            "fields": (
                ("field_title", "field_title_hint", "field_title_placeholder"),
                ("field_slug", "field_slug_hint", "field_slug_placeholder"),
                ("btn_generate_slug", "btn_generate_slug_icon"),
                ("field_short_description", "field_short_description_hint", "field_short_description_placeholder"),
                ("field_description", "field_description_hint", "field_description_placeholder"),
                ("field_cover", "field_cover_hint", "field_cover_placeholder"),
                ("btn_cover_upload", "btn_cover_upload_icon"),
                ("btn_cover_remove", "btn_cover_remove_icon"),
                ("field_promo_video", "field_promo_video_placeholder"),
                ("field_teacher", "field_teacher_hint"),
                ("field_category", "field_category_hint"),
                ("field_start_date", "field_end_date"),
                ("field_duration", "field_duration_hint"),
                ("field_language", "field_level", "field_status"),
                ("field_price", "field_price_hint", "field_price_placeholder"),
                ("field_discounted_price", "field_discounted_price_hint"),
                ("field_max_students", "field_max_students_hint"),
                ("field_passing_score", "field_attendance_required"),
                ("field_meta_title", "field_meta_title_placeholder"),
                ("field_meta_description", "field_meta_description_placeholder"),
                ("field_meta_keywords", "field_meta_keywords_placeholder"),
            ),
            "classes": ("wide", "collapse"),
        }),
        ("☑️ Checkbox yorliqlari", {
            "fields": (
                ("check_is_active", "check_is_active_hint"),
                ("check_is_featured", "check_is_featured_hint"),
                ("check_is_certificate", "check_is_certificate_hint"),
            ),
        }),
        ("👁 Ko‘rinish preview", {
            "fields": (
                ("preview_title", "preview_subtitle"),
                ("preview_no_cover", "preview_no_title", "preview_no_teacher"),
                ("preview_no_description", "preview_free", "preview_duration_suffix"),
            ),
            "classes": ("collapse",),
        }),
        ("💬 Xabarlar", {
            "fields": (
                "msg_saved_create", "msg_saved_edit",
                "msg_error", "msg_network_error",
                "msg_unsaved", "msg_unsaved_confirm",
                "msg_slug_generated", "msg_char_limit",
            ),
            "classes": ("wide", "collapse"),
        }),
        ("⚠️ Validatsiya", {
            "fields": (
                "err_title_required", "err_title_min",
                "err_date_order", "err_price_negative", "err_discount_higher",
            ),
            "classes": ("collapse",),
        }),
        ("⌨️ Klaviatura", {
            "fields": ("keyboard_hint_title", "keyboard_save", "keyboard_cancel"),
            "classes": ("collapse",),
        }),
    )