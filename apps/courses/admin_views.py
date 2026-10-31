"""
apps/courses/admin_views.py
================================================
DIGION LMS — Kurslar admin paneli uchun Class-Based Views.

XUSUSIYATLAR:
- Class-Based Views (CBV) — professional arxitektura
- Django Forms — validatsiya va XSS himoyasi
- Transaction — xato bo'lsa rollback
- Audit Log — har bir o'zgarish qayd etiladi
- AJAX + oddiy POST qo'llab-quvvatlanadi
- Soft-delete boshqaruvi
- N+1 query optimizatsiyasi
- GroupLesson — guruh-dars bog'lanishi
"""

# ═══════════════════════════════════════════════════════════════
# IMPORTS
# ═══════════════════════════════════════════════════════════════
import re
from datetime import timedelta, date
from decimal import Decimal, InvalidOperation
from django.db import transaction, IntegrityError   # ⭐ IntegrityError qo'shildi
from django.db.models import (
    Count, Q, Sum, Avg, F, Case, When, Value, BooleanField,
    OuterRef, Subquery, IntegerField,              # ⭐ GroupListView uchun
)
from django.db.models.functions import Coalesce    # ⭐ GroupListView uchun

from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.text import slugify
from django.views import View
from django.views.generic import (
    ListView, DetailView, CreateView, UpdateView, DeleteView, FormView
)

from .models import (
    Course, CourseCategory, CourseMonth,
    CourseLevel, CourseLanguage, CourseStatus,
    CourseListPageSettings, CourseFormPageSettings,
    Lesson, LessonStatus, GroupLesson,
    LessonStatus,
    Homework, HomeworkSubmission,
    Quiz, Question, AnswerOption,
    StudentGroup, GroupMember,
    Enrollment, Attendance,
    Certificate, Review, AuditLog,
    LessonType,
)
from apps.user.models import StudentProfile, CustomUser
import logging

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# MIXINS — Umumiy xatti-harakatlar
# ═══════════════════════════════════════════════════════════════

class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Faqat admin yoki superuser kira oladi."""
    raise_exception = False

    def test_func(self):
        user = self.request.user
        return user.is_authenticated and (
            user.is_superuser or getattr(user, 'role', None) == 'admin'
        )

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            messages.error(self.request, "Ruxsat yo'q!")
        return redirect('home_page_view')


class AdminContextMixin:
    """Umumiy context (current_url)."""

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['current_url'] = 'courses'
        return ctx


class AjaxFormMixin:
    """
    AJAX POST → JSON javob.
    Oddiy POST → messages + redirect.
    """

    def is_ajax(self):
        return self.request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def form_invalid(self, form):
        if self.is_ajax():
            return JsonResponse({
                'success': False,
                'errors': form.errors,
                'message': "Formada xatolik bor",
            }, status=400)
        messages.error(self.request, "❌ Iltimos, formani tekshiring.")
        return super().form_invalid(form)


class AuditLogMixin:
    """Create/Update/Delete da AuditLog yozadi."""

    audit_action = 'update'

    def log_action(self, obj, description='', changes=None):
        try:
            AuditLog.objects.create(
                user=self.request.user,
                action=self.audit_action,
                content_type=ContentType.objects.get_for_model(obj.__class__),
                object_id=obj.pk,
                description=description or f"{obj.__class__.__name__}: {obj}",
                changes=changes or {},
                ip_address=self._client_ip(),
            )
        except Exception:
            pass  # Audit xato bersa asosiy amalni to'xtatmaymiz

    def _client_ip(self):
        xff = self.request.META.get('HTTP_X_FORWARDED_FOR')
        if xff:
            return xff.split(',')[0].strip()
        return self.request.META.get('REMOTE_ADDR')


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_decimal(value, default=None):
    if default is None:
        default = Decimal('0')
    if value is None or value == '':
        return default
    try:
        return Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation):
        return default


# ═══════════════════════════════════════════════════════════════
# FORMS — Professional validatsiya
# ═══════════════════════════════════════════════════════════════

class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = [
            'title', 'slug', 'short_description', 'description',
            'cover_image', 'promo_video',
            'category', 'teacher',
            'start_date', 'end_date', 'duration_months',
            'language', 'level', 'status',
            'price', 'discounted_price',
            'max_students', 'passing_score', 'attendance_required',
            'meta_title', 'meta_description', 'meta_keywords',
            'is_active', 'is_featured', 'is_certificate_enabled',
        ]
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 6}),
            'short_description': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            css = 'form-check-input' if isinstance(field.widget, forms.CheckboxInput) else 'form-control'
            field.widget.attrs.setdefault('class', css)

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get('start_date'), cleaned.get('end_date')
        price = cleaned.get('price') or Decimal('0')
        discount = cleaned.get('discounted_price')

        if start and end and start > end:
            raise ValidationError({'end_date': "Tugash sanasi boshlanishdan keyin bo'lsin"})
        if discount and discount > price:
            raise ValidationError({'discounted_price': "Chegirma narxdan katta bo'lmasin"})
        if price < 0:
            raise ValidationError({'price': "Narx manfiy bo'lmasin"})
        return cleaned

    def clean_title(self):
        title = (self.cleaned_data.get('title') or '').strip()
        if len(title) < 3:
            raise ValidationError("Kurs nomi kamida 3 belgi")
        if len(title) > 255:
            raise ValidationError("Kurs nomi juda uzun")
        return title


class CourseMonthForm(forms.ModelForm):
    """
    Kurs oyi formasi.
    `month_number` — forma maydoni emas (view o'zi qo'yadi).
    `start_date`, `end_date` — ixtiyoriy.
    """

    class Meta:
        model = CourseMonth
        # ⚠️ month_number OLIB TASHLANDI — view o'zi qo'yadi
        fields = ['title', 'description', 'goals', 'start_date', 'end_date']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 3}),
            'goals': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, course=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.course = course

        # ⭐ Sanalarni ixtiyoriy qilish
        self.fields['start_date'].required = False
        self.fields['end_date'].required = False
        self.fields['description'].required = False
        self.fields['goals'].required = False

        # CSS class
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.Textarea):
                css = 'mf-textarea'
            else:
                css = 'mf-input'
            field.widget.attrs.setdefault('class', css)

    def clean_title(self):
        """Oy nomi majburiy."""
        title = (self.cleaned_data.get('title') or '').strip()
        if not title:
            raise ValidationError("Oy nomini kiriting!")
        if len(title) < 2:
            raise ValidationError("Oy nomi kamida 2 belgi bo'lsin")
        if len(title) > 200:
            raise ValidationError("Oy nomi juda uzun (max 200 belgi)")
        return title

    def clean(self):
        """Sana tekshirish."""
        cleaned = super().clean()
        start = cleaned.get('start_date')
        end = cleaned.get('end_date')

        if start and end and start > end:
            raise ValidationError({
                'end_date': "Tugash sanasi boshlanishdan keyin bo'lishi kerak"
            })

        return cleaned

class LessonForm(forms.ModelForm):
    class Meta:
        model = Lesson
        fields = [
            'lesson_number', 'topic', 'title', 'short_description',
            'content', 'lesson_type',
            'code_examples', 'extra_sections', 'extra_materials',
            'video_url', 'video_file',
            'lesson_date', 'duration_minutes',
            'status', 'is_published', 'is_mandatory',
        ]
        widgets = {
            'lesson_date': forms.DateInput(attrs={'type': 'date'}),
            'content': forms.Textarea(attrs={'rows': 12}),
        }

    def __init__(self, *args, course=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.course = course
        if course and not self.instance.pk:
            last = Lesson.objects.filter(course=course).order_by('-lesson_number').first()
            self.fields['lesson_number'].initial = (last.lesson_number + 1) if last else 1

    def clean_lesson_number(self):
        num = self.cleaned_data.get('lesson_number')
        if not num:
            return num
        if num < 1:
            raise ValidationError("1 dan kichik bo'lmasin")
        qs = Lesson.objects.filter(course=self.course, lesson_number=num)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError(f"{num}-dars allaqachon mavjud")
        return num

    def clean_content(self):
        content = self.cleaned_data.get('content') or ''
        if '<script' in content.lower():
            raise ValidationError("Script teglari taqiqlangan")
        if len(content) > 100_000:
            raise ValidationError("Matn juda uzun (max 100 000 belgi)")
        return content

    def clean_video_file(self):
        f = self.cleaned_data.get('video_file')
        if f and hasattr(f, 'size') and f.size > 200 * 1024 * 1024:
            raise ValidationError("Video 200 MB dan oshmasin")
        return f


class HomeworkForm(forms.ModelForm):
    """Uyga vazifa formasi — to'liq."""

    # ⭐ JSON maydonlar (dinamik editorlar uchun)
    extra_links_json = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={'id': 'id_extra_links_json'}),
    )
    extra_sections_json = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={'id': 'id_extra_sections_json'}),
    )

    class Meta:
        model = Homework
        fields = [
            # ─── Asosiy ───
            'title', 'short_description', 'description', 'instructions',

            # ─── Turi va qiyinlik ⭐ YANGI ───
            'homework_type', 'difficulty', 'estimated_minutes',

            # ─── Muddat va mukofot ───
            'deadline_days', 'max_score', 'coins_reward', 'xp_reward',

            # ─── Kod ───
            'starter_code', 'solution_code',

            # ─── Testlar ⭐ extra_quizzes YANGI ───
            'quiz', 'extra_quizzes',

            # ─── Fayl ───
            'task_file',

            # ─── Guruh ishi ⭐ YANGI ───
            'is_group_work', 'min_group_size', 'max_group_size',

            # ─── Kech topshirish ⭐ YANGI ───
            'allow_late_submission', 'late_penalty_percent',
        ]

    def __init__(self, *args, lesson=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.lesson = lesson

        # Quiz queryset — kurs bo'yicha
        if lesson:
            quizzes = Quiz.objects.filter(course=lesson.course, is_active=True)
            if 'quiz' in self.fields:
                self.fields['quiz'].queryset = quizzes
                self.fields['quiz'].empty_label = "— Asosiy test tanlanmagan —"
            if 'extra_quizzes' in self.fields:
                self.fields['extra_quizzes'].queryset = quizzes

        # Ixtiyoriy maydonlar
        optional = [
            'short_description', 'instructions', 'starter_code',
            'solution_code', 'quiz', 'task_file', 'extra_quizzes',
        ]
        for f in optional:
            if f in self.fields:
                self.fields[f].required = False

        # ⭐ DEFAULT qiymatlar — yangi forma uchun
        if not self.instance.pk:
            defaults = {
                'deadline_days': 3,
                'max_score': 100,
                'coins_reward': 10,
                'xp_reward': 50,
                'estimated_minutes': 60,
                'min_group_size': 2,
                'max_group_size': 5,
                'late_penalty_percent': 10,
            }
            for name, value in defaults.items():
                if name in self.fields:
                    self.fields[name].initial = value

        # ⭐ JSON maydonlarni tayyorlash
        import json
        if self.instance.pk:
            self.fields['extra_links_json'].initial = json.dumps(
                self.instance.extra_links or [], ensure_ascii=False
            )
            self.fields['extra_sections_json'].initial = json.dumps(
                self.instance.extra_sections or [], ensure_ascii=False
            )
        else:
            self.fields['extra_links_json'].initial = '[]'
            self.fields['extra_sections_json'].initial = '[]'

    def clean(self):
        cleaned = super().clean()

        # Guruh ishi validatsiyasi
        if cleaned.get('is_group_work'):
            mn = cleaned.get('min_group_size') or 2
            mx = cleaned.get('max_group_size') or 5
            if mn > mx:
                self.add_error(
                    'max_group_size',
                    "Maks. hajm minimaldan kichik bo'lmasin"
                )

        # JSON parse
        import json
        for field, model_field in [
            ('extra_links_json', 'extra_links'),
            ('extra_sections_json', 'extra_sections'),
        ]:
            raw = cleaned.get(field) or '[]'
            try:
                data = json.loads(raw) if isinstance(raw, str) else raw
                if not isinstance(data, list):
                    data = []
                cleaned[model_field] = data
            except (json.JSONDecodeError, TypeError):
                cleaned[model_field] = []

        return cleaned

    def clean_title(self):
        t = (self.cleaned_data.get('title') or '').strip()
        if len(t) < 3:
            raise ValidationError("Sarlavha kamida 3 belgi")
        return t

    def save(self, commit=True):
        hw = super().save(commit=False)
        hw.extra_links = self.cleaned_data.get('extra_links', [])
        hw.extra_sections = self.cleaned_data.get('extra_sections', [])
        if commit:
            hw.save()
            self.save_m2m()
        return hw

class QuizForm(forms.ModelForm):
    """Test formasi — to'liq validatsiya bilan."""

    class Meta:
        model = Quiz
        fields = [
            'title', 'description', 'difficulty',
            'duration_minutes', 'passing_score', 'max_attempts',
            'coins_reward', 'xp_reward',
            'shuffle_questions', 'show_correct_answers',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # ═══ DEFAULT qiymatlar — yangi forma uchun ═══
        if not self.instance.pk:
            defaults = {
                'difficulty': 'medium',
                'duration_minutes': 30,
                'passing_score': 60,
                'max_attempts': 3,
                'coins_reward': 0,
                'xp_reward': 0,
                'shuffle_questions': False,
                'show_correct_answers': True,
            }
            for name, value in defaults.items():
                if name in self.fields:
                    self.fields[name].initial = value

        # ═══ IXTIYORIY maydonlar ═══
        optional_fields = [
            'description',
            'duration_minutes',
            'passing_score',
            'max_attempts',
            'coins_reward',
            'xp_reward',
        ]
        for f in optional_fields:
            if f in self.fields:
                self.fields[f].required = False

        # ═══ CSS klasslar ═══
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault('class', 'qf-checkbox')
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault('class', 'qf-select')
            elif isinstance(widget, forms.Textarea):
                widget.attrs.setdefault('class', 'qf-textarea')
                widget.attrs.setdefault('rows', 4)
            else:
                widget.attrs.setdefault('class', 'qf-input')

    # ═══ VALIDATSIYA ═══
    def clean_title(self):
        title = (self.cleaned_data.get('title') or '').strip()
        if len(title) < 3:
            raise ValidationError("Sarlavha kamida 3 belgi bo'lsin")
        if len(title) > 255:
            raise ValidationError("Sarlavha juda uzun (max 255 belgi)")
        return title

    def clean_duration_minutes(self):
        val = self.cleaned_data.get('duration_minutes')
        if val is None or val == '':
            return 30
        try:
            val = int(val)
        except (ValueError, TypeError):
            return 30
        if val < 1:
            raise ValidationError("Davomiylik kamida 1 daqiqa")
        if val > 300:
            raise ValidationError("Davomiylik 300 daqiqadan oshmasin")
        return val

    def clean_passing_score(self):
        val = self.cleaned_data.get('passing_score')
        if val is None or val == '':
            return 60
        try:
            val = int(val)
        except (ValueError, TypeError):
            return 60
        if val < 0 or val > 100:
            raise ValidationError("O'tish bali 0-100 oralig'ida bo'lsin")
        return val

    def clean_max_attempts(self):
        val = self.cleaned_data.get('max_attempts')
        if val is None or val == '':
            return 3
        try:
            val = int(val)
        except (ValueError, TypeError):
            return 3
        if val < 1:
            return 3
        return val

    def clean_coins_reward(self):
        val = self.cleaned_data.get('coins_reward')
        if val is None or val == '':
            return 0
        try:
            return max(0, int(val))
        except (ValueError, TypeError):
            return 0

    def clean_xp_reward(self):
        val = self.cleaned_data.get('xp_reward')
        if val is None or val == '':
            return 0
        try:
            return max(0, int(val))
        except (ValueError, TypeError):
            return 0

class GroupForm(forms.ModelForm):
    """
    Guruh formasi — to'liq professional.

    XUSUSIYATLAR:
    - Schedule (7 kun) alohida maydonlar
    - Vaqtni avtomatik formatlash (14 → 14:00, 1430 → 14:30, 9 → 09:00)
    - Schedule type bo'yicha avtomatik to'ldirish (odd/even)
    - Course bilan integratsiya
    - Capacity validatsiyasi (1-200)
    - Sanalar tartibi tekshiriladi
    - Rang HEX format tekshiriladi
    - Barcha default qiymatlar bound bo'lsa ham ishlaydi
    """

    # ═══════════════════════════════════════════════════════════
    # SCHEDULE MAYDONLARI (7 kun)
    # ═══════════════════════════════════════════════════════════

    schedule_monday = forms.CharField(
        required=False, max_length=10,
        widget=forms.TextInput(attrs={
            'class': 'gf-day-time',
            'placeholder': '14:00',
            'autocomplete': 'off',
        })
    )
    schedule_tuesday = forms.CharField(
        required=False, max_length=10,
        widget=forms.TextInput(attrs={
            'class': 'gf-day-time',
            'placeholder': '14:00',
            'autocomplete': 'off',
        })
    )
    schedule_wednesday = forms.CharField(
        required=False, max_length=10,
        widget=forms.TextInput(attrs={
            'class': 'gf-day-time',
            'placeholder': '14:00',
            'autocomplete': 'off',
        })
    )
    schedule_thursday = forms.CharField(
        required=False, max_length=10,
        widget=forms.TextInput(attrs={
            'class': 'gf-day-time',
            'placeholder': '14:00',
            'autocomplete': 'off',
        })
    )
    schedule_friday = forms.CharField(
        required=False, max_length=10,
        widget=forms.TextInput(attrs={
            'class': 'gf-day-time',
            'placeholder': '14:00',
            'autocomplete': 'off',
        })
    )
    schedule_saturday = forms.CharField(
        required=False, max_length=10,
        widget=forms.TextInput(attrs={
            'class': 'gf-day-time',
            'placeholder': '14:00',
            'autocomplete': 'off',
        })
    )
    schedule_sunday = forms.CharField(
        required=False, max_length=10,
        widget=forms.TextInput(attrs={
            'class': 'gf-day-time',
            'placeholder': '14:00',
            'autocomplete': 'off',
        })
    )

    # ═══════════════════════════════════════════════════════════
    # META
    # ═══════════════════════════════════════════════════════════

    class Meta:
        model = StudentGroup
        fields = [
            'name', 'code', 'description',
            'course', 'teacher',
            'max_students', 'status',
            'start_date', 'end_date', 'lessons_start_date',
            'room', 'color', 'schedule_type',
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'gf-input',
                'placeholder': 'Masalan: B6-2025',
                'maxlength': '100',
            }),
            'code': forms.TextInput(attrs={
                'class': 'gf-input',
                'placeholder': 'B6-2025 (ixtiyoriy)',
                'maxlength': '20',
            }),
            'description': forms.Textarea(attrs={
                'class': 'gf-textarea',
                'rows': 3,
                'placeholder': "Guruh haqida qisqacha ma'lumot...",
            }),
            'course': forms.Select(attrs={'class': 'gf-select'}),
            'teacher': forms.Select(attrs={'class': 'gf-select'}),
            'max_students': forms.NumberInput(attrs={
                'class': 'gf-input',
                'min': '1', 'max': '200',
            }),
            'status': forms.Select(attrs={'class': 'gf-select'}),
            'start_date': forms.DateInput(attrs={
                'type': 'date', 'class': 'gf-input',
            }),
            'end_date': forms.DateInput(attrs={
                'type': 'date', 'class': 'gf-input',
            }),
            'lessons_start_date': forms.DateInput(attrs={
                'type': 'date', 'class': 'gf-input',
            }),
            'room': forms.TextInput(attrs={
                'class': 'gf-input',
                'placeholder': 'Masalan: 302-xona',
                'maxlength': '100',
            }),
            'color': forms.TextInput(attrs={
                'class': 'gf-input',
                'type': 'color',
            }),
            'schedule_type': forms.Select(attrs={'class': 'gf-select'}),
        }
        labels = {
            'name': 'Guruh nomi',
            'code': 'Guruh kodi',
            'description': 'Tavsif',
            'course': 'Kurs',
            'teacher': "O'qituvchi",
            'max_students': 'Maks. talabalar',
            'status': 'Holat',
            'start_date': 'Boshlanish sanasi',
            'end_date': 'Tugash sanasi',
            'lessons_start_date': 'Darslar boshlanish sanasi',
            'room': 'Xona',
            'color': 'Rang',
            'schedule_type': 'Dars kunlari turi',
        }
        help_texts = {
            'name': 'Qisqa va eslab qoladigan nom (masalan: B6, B7)',
            'code': "Bo'sh qoldirsangiz avtomatik yaratiladi",
            'max_students': "1-200 oralig'ida",
            'lessons_start_date': "Bu sanadan boshlab darslar taqsimlanadi",
            'color': "Guruh rangi (HEX format)",
        }

    # ═══════════════════════════════════════════════════════════
    # INITIALIZATION
    # ═══════════════════════════════════════════════════════════

    def __init__(self, *args, **kwargs):
        """Forma initsializatsiyasi — to'liq professional."""
        super().__init__(*args, **kwargs)

        # ═══ 1. Ixtiyoriy maydonlar ═══
        optional_fields = [
            'code', 'description', 'start_date', 'end_date',
            'lessons_start_date', 'room',
            'color', 'schedule_type',  # ⭐ MUHIM: default bor
        ]
        for name in optional_fields:
            if name in self.fields:
                self.fields[name].required = False

        # ═══ 2. Course queryset — faqat live kurslar ═══
        if 'course' in self.fields:
            self.fields['course'].queryset = (
                Course.objects.filter(is_deleted=False).order_by('title')
            )
            self.fields['course'].empty_label = "— Kurs tanlanmagan —"

        # ═══ 3. Teacher queryset — faqat live o'qituvchilar ═══
        if 'teacher' in self.fields:
            self.fields['teacher'].queryset = (
                CustomUser.objects
                .filter(role='teacher', is_active=True)
                .order_by('first_name', 'last_name')
            )
            self.fields['teacher'].empty_label = "— O'qituvchi tanlanmagan —"

        # ═══ 4. DEFAULT INITIAL — har doim (bound/unbound farqi yo'q) ═══
        if 'color' in self.fields:
            self.fields['color'].initial = '#06b6d4'
        if 'schedule_type' in self.fields:
            self.fields['schedule_type'].initial = 'odd'
        if 'max_students' in self.fields:
            self.fields['max_students'].initial = 20
        if 'status' in self.fields:
            self.fields['status'].initial = 'active'

        # ═══ 5. Jadval maydonlarini mavjud qiymatlar bilan to'ldirish ═══
        if self.instance and self.instance.pk:
            schedule = self.instance.schedule or {}
            for day in ('monday', 'tuesday', 'wednesday', 'thursday',
                        'friday', 'saturday', 'sunday'):
                field_name = f'schedule_{day}'
                if field_name in self.fields and day in schedule:
                    self.fields[field_name].initial = schedule[day]

    # ═══════════════════════════════════════════════════════════
    # VALIDATSIYA METODLARI
    # ═══════════════════════════════════════════════════════════

    def clean_name(self):
        """Guruh nomini tekshirish."""
        name = (self.cleaned_data.get('name') or '').strip()

        if not name:
            raise ValidationError("Guruh nomini kiriting")

        if len(name) < 2:
            raise ValidationError("Guruh nomi kamida 2 belgi bo'lsin")

        if len(name) > 100:
            raise ValidationError("Guruh nomi juda uzun (max 100 belgi)")

        # Dublikat tekshirish
        qs = StudentGroup.objects.filter(
            name__iexact=name,
            is_deleted=False,
        )
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError(
                f"'{name}' nomli guruh allaqachon mavjud"
            )

        return name

    def clean_code(self):
        """Guruh kodini tekshirish."""
        code = (self.cleaned_data.get('code') or '').strip()

        if not code:
            return code

        if len(code) > 20:
            raise ValidationError("Guruh kodi juda uzun (max 20 belgi)")

        # Dublikat tekshirish
        qs = StudentGroup.objects.filter(
            code__iexact=code,
            is_deleted=False,
        )
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError(
                f"'{code}' kodli guruh allaqachon mavjud"
            )

        return code

    def clean_max_students(self):
        """Maksimal talabalar sonini tekshirish."""
        n = self.cleaned_data.get('max_students')

        if n is None:
            return 20

        if n < 1:
            raise ValidationError("Kamida 1 talaba bo'lishi kerak")

        if n > 200:
            raise ValidationError("Maksimal 200 talaba")

        # Tahrirlashda: mavjud talabalar sonidan kam bo'lmasin
        if self.instance.pk:
            try:
                current_students = self.instance.students_count
                if n < current_students:
                    raise ValidationError(
                        f"Guruhda {current_students} ta talaba bor. "
                        f"Limitni {current_students} dan kam qilmang."
                    )
            except Exception:
                pass

        return n

    def clean_color(self):
        """Rang HEX format tekshirish."""
        color = (self.cleaned_data.get('color') or '').strip()

        # ⭐ Bo'sh bo'lsa — default qaytaramiz
        if not color:
            return '#06b6d4'

        # HEX format tekshirish
        if not re.match(r'^#[0-9A-Fa-f]{6}$', color):
            raise ValidationError(
                "Rang HEX formatida bo'lsin (masalan: #06b6d4)"
            )

        return color.lower()

    def clean_schedule_type(self):
        """Schedule type — default 'odd'."""
        st = (self.cleaned_data.get('schedule_type') or '').strip()
        if not st:
            return 'odd'
        if st not in ('odd', 'even', 'custom'):
            return 'odd'
        return st

    def clean_room(self):
        """Xona nomini tozalash."""
        room = (self.cleaned_data.get('room') or '').strip()
        if len(room) > 100:
            raise ValidationError("Xona nomi juda uzun (max 100 belgi)")
        return room

    def clean_description(self):
        """Tavsifni tozalash."""
        description = (self.cleaned_data.get('description') or '').strip()

        if len(description) > 2000:
            raise ValidationError("Tavsif juda uzun (max 2000 belgi)")

        return description

    # ═══════════════════════════════════════════════════════════
    # VAQTNI FORMATLASH
    # ═══════════════════════════════════════════════════════════

    def _clean_time(self, value):
        """
        Vaqtni standart formatga keltirish.

        Qabul qiladi:
        - "14" → "14:00"
        - "14:30" → "14:30"
        - "1430" → "14:30"
        - "9" → "09:00"
        - "930" → "09:30"
        - "abc" → "" (bo'sh)
        - "25" → "" (bo'sh, noto'g'ri soat)
        """
        if not value:
            return ''

        value = str(value).strip()

        # Allaqachon HH:MM formatda
        if ':' in value:
            parts = value.split(':')
            if len(parts) == 2:
                try:
                    h = int(parts[0])
                    m = int(parts[1])
                    if 0 <= h < 24 and 0 <= m < 60:
                        return f"{h:02d}:{m:02d}"
                except ValueError:
                    pass
            return ''

        # Faqat raqamlar
        digits = ''.join(c for c in value if c.isdigit())

        if len(digits) == 1 or len(digits) == 2:
            # "9" → "09:00", "14" → "14:00"
            try:
                h = int(digits)
                if 0 <= h < 24:
                    return f"{h:02d}:00"
            except ValueError:
                pass

        elif len(digits) == 3:
            # "930" → "09:30"
            try:
                h = int(digits[0])
                m = int(digits[1:])
                if 0 <= h < 24 and 0 <= m < 60:
                    return f"{h:02d}:{m:02d}"
            except ValueError:
                pass

        elif len(digits) == 4:
            # "1430" → "14:30"
            try:
                h = int(digits[:2])
                m = int(digits[2:])
                if 0 <= h < 24 and 0 <= m < 60:
                    return f"{h:02d}:{m:02d}"
            except ValueError:
                pass

        return ''  # Noto'g'ri format — bo'sh qaytaramiz

    def clean_schedule_monday(self):
        return self._clean_time(self.cleaned_data.get('schedule_monday'))

    def clean_schedule_tuesday(self):
        return self._clean_time(self.cleaned_data.get('schedule_tuesday'))

    def clean_schedule_wednesday(self):
        return self._clean_time(self.cleaned_data.get('schedule_wednesday'))

    def clean_schedule_thursday(self):
        return self._clean_time(self.cleaned_data.get('schedule_thursday'))

    def clean_schedule_friday(self):
        return self._clean_time(self.cleaned_data.get('schedule_friday'))

    def clean_schedule_saturday(self):
        return self._clean_time(self.cleaned_data.get('schedule_saturday'))

    def clean_schedule_sunday(self):
        return self._clean_time(self.cleaned_data.get('schedule_sunday'))

    # ═══════════════════════════════════════════════════════════
    # UMUMIY VALIDATSIYA
    # ═══════════════════════════════════════════════════════════

    def clean(self):
        """Umumiy validatsiya."""
        cleaned = super().clean()

        # ═══ 1. Sanalar tartibi ═══
        start = cleaned.get('start_date')
        end = cleaned.get('end_date')
        lessons_start = cleaned.get('lessons_start_date')

        if start and end and start > end:
            self.add_error(
                'end_date',
                "Tugash sanasi boshlanish sanasidan keyin bo'lsin"
            )

        if lessons_start and end and lessons_start > end:
            self.add_error(
                'lessons_start_date',
                "Darslar boshlanish sanasi tugash sanasidan keyin bo'lmasin"
            )

        # ═══ 2. Schedule (7 kun) yig'ish ═══
        schedule = {}
        for day in ('monday', 'tuesday', 'wednesday', 'thursday',
                    'friday', 'saturday', 'sunday'):
            t = (cleaned.get(f'schedule_{day}') or '').strip()
            if t:
                schedule[day] = t

        cleaned['_schedule'] = schedule

        # ═══ 3. Schedule type bo'yicha avtomatik to'ldirish ═══
        schedule_type = cleaned.get('schedule_type')

        if schedule_type == 'odd' and not schedule:
            # Toq kunlar: Du, Ch, Ju
            schedule = {
                'monday': '14:00',
                'wednesday': '14:00',
                'friday': '14:00',
            }
            cleaned['_schedule'] = schedule

        elif schedule_type == 'even' and not schedule:
            # Juft kunlar: Se, Pa, Sha
            schedule = {
                'tuesday': '14:00',
                'thursday': '14:00',
                'saturday': '14:00',
            }
            cleaned['_schedule'] = schedule

        return cleaned

    # ═══════════════════════════════════════════════════════════
    # SAVE
    # ═══════════════════════════════════════════════════════════

    def save(self, commit=True):
        """Saqlash — schedule ni ham saqlash."""
        group = super().save(commit=False)

        # Schedule ni o'rnatish
        schedule = self.cleaned_data.get('_schedule', {})
        group.schedule = schedule

        # Code avtomatik (agar bo'sh bo'lsa)
        if not group.code and group.name:
            year = timezone.now().year
            base_code = f"{group.name.upper()}-{year}"
            code = base_code
            counter = 1
            while StudentGroup.objects.filter(
                code=code, is_deleted=False
            ).exclude(pk=group.pk).exists():
                code = f"{base_code}-{counter}"
                counter += 1
            group.code = code

        if commit:
            group.save()

        return group

# ═══════════════════════════════════════════════════════════════
# YORDAMCHI: Schedule type bo'yicha avtomatik to'ldirish
# ═══════════════════════════════════════════════════════════════

def apply_schedule_type(schedule_type, current_schedule=None):
    """
    Schedule type bo'yicha jadval tuzish.

    Args:
        schedule_type: 'odd', 'even', 'custom'
        current_schedule: mavjud schedule (odd/even uchun default vaqt olish)

    Returns:
        dict: {'monday': '14:00', ...}
    """
    if schedule_type == 'odd':
        # Toq kunlar: Du, Ch, Ju
        default_time = '14:00'
        if current_schedule and 'monday' in current_schedule:
            default_time = current_schedule['monday']

        return {
            'monday': default_time,
            'wednesday': default_time,
            'friday': default_time,
        }

    elif schedule_type == 'even':
        # Juft kunlar: Se, Pa, Sha
        default_time = '14:00'
        if current_schedule and 'tuesday' in current_schedule:
            default_time = current_schedule['tuesday']

        return {
            'tuesday': default_time,
            'thursday': default_time,
            'saturday': default_time,
        }

    return {}  # custom — bo'sh

# ═══════════════════════════════════════════════════════════════
# 1. COURSE VIEWS
# ═══════════════════════════════════════════════════════════════

class CourseListView(AdminRequiredMixin, AdminContextMixin, ListView):
    """
    Kurslar ro'yxati — filtr, qidiruv, sort, pagination, eksport.

    XUSUSIYATLAR:
    - Qidiruv va filtrlar
    - Sort va pagination
    - CSV eksport
    - Excel (xlsx) eksport
    - Print uchun tayyor
    """

    model = Course
    template_name = 'admin_user/courses/list.html'
    context_object_name = 'courses'
    paginate_by = 12

    # ═══════════════════════════════════════════════════════════
    # GET — eksport bo'lsa ushlab qolish
    # ═══════════════════════════════════════════════════════════

    def get(self, request, *args, **kwargs):
        """GET so'rov — eksport parametri bo'lsa fayl qaytaradi."""
        export_type = request.GET.get('export', '').strip().lower()

        if export_type == 'csv':
            return self._export_csv()
        elif export_type == 'excel':
            return self._export_excel()
        elif export_type == 'pdf':
            return self._export_pdf()

        return super().get(request, *args, **kwargs)

    # ═══════════════════════════════════════════════════════════
    # QUERYSET
    # ═══════════════════════════════════════════════════════════

    def get_paginate_by(self, queryset):
        try:
            n = int(self.request.GET.get('per_page', 12))
            return n if n in (12, 24, 48, 96) else 12
        except (TypeError, ValueError):
            return 12

    def get_queryset(self):
        """Kurslar queryset — filtrlar bilan."""
        ps = CourseListPageSettings.load()

        qs = (
            Course.objects
            .filter(is_deleted=False)
            .select_related('category', 'teacher')
            .annotate(
                students_count_annot=Count('enrollments', distinct=True),
                months_count_annot=Count('months', distinct=True),
                lessons_count_annot=Count('lessons', distinct=True),
            )
        )

        # "YANGI" badge
        new_threshold = timezone.now() - timedelta(days=ps.badge_new_days)
        qs = qs.annotate(
            is_new_flag=Case(
                When(created_at__gte=new_threshold, then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            )
        )

        # Qidiruv
        search = self.request.GET.get('q', '').strip()
        if search:
            qs = qs.filter(
                Q(title__icontains=search) |
                Q(short_description__icontains=search) |
                Q(description__icontains=search) |
                Q(teacher__first_name__icontains=search) |
                Q(teacher__last_name__icontains=search)
            )

        # Status
        status = self.request.GET.get('status', '').strip()
        if status:
            qs = qs.filter(status=status)

        # Kategoriya
        category = self.request.GET.get('category', '').strip()
        if category:
            qs = qs.filter(category_id=category)

        # Daraja
        level = self.request.GET.get('level', '').strip()
        if level:
            qs = qs.filter(level=level)

        # Til
        lang = self.request.GET.get('language', '').strip()
        if lang:
            qs = qs.filter(language=lang)

        # Narx
        price = self.request.GET.get('price', '').strip()
        if price == 'free':
            qs = qs.filter(is_free=True)
        elif price == 'paid':
            qs = qs.filter(is_free=False)

        # Sana
        date_filter = self.request.GET.get('date', '').strip()
        if date_filter == 'today':
            qs = qs.filter(created_at__date=timezone.now().date())
        elif date_filter == 'week':
            qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=7))
        elif date_filter == 'month':
            qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=30))

        # Featured
        if self.request.GET.get('featured') == '1':
            qs = qs.filter(is_featured=True)

        # Sort
        sort = self.request.GET.get('sort', '-created_at')
        allowed = {
            '-created_at', 'created_at', 'title', '-title',
            '-enrollment_count', '-rating',
        }
        if sort in allowed:
            qs = qs.order_by(sort)

        return qs

    # ═══════════════════════════════════════════════════════════
    # CONTEXT
    # ═══════════════════════════════════════════════════════════

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ps = CourseListPageSettings.load()
        all_courses = Course.objects.filter(is_deleted=False)
        avg_rating = all_courses.aggregate(a=Avg('rating'))['a'] or 0

        ctx.update({
            'page_settings': ps,
            'page_obj': ctx['page_obj'],
            'stats': {
                'total': all_courses.count(),
                'published': all_courses.filter(status='published').count(),
                'draft': all_courses.filter(status='draft').count(),
                'pending': all_courses.filter(status='pending').count(),
                'archived': all_courses.filter(status='archived').count(),
                'featured': all_courses.filter(is_featured=True).count(),
                'students': Enrollment.objects.filter(status='active').count(),
                'lessons': Lesson.objects.filter(is_deleted=False).count(),
                'months': CourseMonth.objects.count(),
                'avg_rating': round(float(avg_rating), 1),
            },
            'categories': CourseCategory.objects.filter(is_active=True),
            'level_choices': Course._meta.get_field('level').choices,
            'language_choices': Course._meta.get_field('language').choices,
            'status_choices': Course._meta.get_field('status').choices,
            'active_filters': self._active_filters(ps),
            'search': self.request.GET.get('q', ''),
            'sort': self.request.GET.get('sort', '-created_at'),
            'per_page': self.get_paginate_by(None),
            'per_page_options': [12, 24, 48, 96],
            'now': timezone.now(),
            'now_minus_new': int((
                                         timezone.now() - timedelta(days=ps.badge_new_days)
                                 ).timestamp()),
        })
        return ctx

    # ═══════════════════════════════════════════════════════════
    # ACTIVE FILTERS (chip lar uchun)
    # ═══════════════════════════════════════════════════════════

    def _active_filters(self, ps):
        r = self.request.GET
        out = []

        if r.get('q'):
            out.append({
                'key': 'q',
                'label': f'"{r["q"]}"',
                'value': r['q'],
            })

        if r.get('status'):
            d = dict(Course._meta.get_field('status').choices).get(
                r['status'], r['status']
            )
            out.append({'key': 'status', 'label': d, 'value': r['status']})

        if r.get('category'):
            cat = CourseCategory.objects.filter(pk=r['category']).first()
            if cat:
                out.append({
                    'key': 'category',
                    'label': cat.name,
                    'value': r['category'],
                })

        if r.get('level'):
            d = dict(Course._meta.get_field('level').choices).get(
                r['level'], r['level']
            )
            out.append({'key': 'level', 'label': d, 'value': r['level']})

        if r.get('language'):
            d = dict(Course._meta.get_field('language').choices).get(
                r['language'], r['language']
            )
            out.append({
                'key': 'language',
                'label': d,
                'value': r['language'],
            })

        if r.get('price'):
            label = (
                ps.filter_price_free
                if r['price'] == 'free'
                else ps.filter_price_paid
            )
            out.append({'key': 'price', 'label': label, 'value': r['price']})

        if r.get('date'):
            date_map = {
                'today': 'Bugun',
                'week': 'Bu hafta',
                'month': 'Bu oy',
            }
            out.append({
                'key': 'date',
                'label': date_map.get(r['date'], r['date']),
                'value': r['date'],
            })

        return out

    # ═══════════════════════════════════════════════════════════
    # CSV EKSPORT
    # ═══════════════════════════════════════════════════════════

    def _export_csv(self):
        """
        Kurslarni CSV formatda yuklab berish.
        Excel uchun BOM (\ufeff) qo'shiladi.
        """
        import csv

        response = HttpResponse(content_type='text/csv; charset=utf-8')
        filename = f"courses_{timezone.now().strftime('%Y%m%d_%H%M')}.csv"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        # Excel UTF-8 ni to'g'ri o'qishi uchun BOM
        response.write('\ufeff')

        writer = csv.writer(response, quoting=csv.QUOTE_MINIMAL)
        writer.writerow([
            'ID', 'Nomi', 'Kategoriya', "O'qituvchi", 'Daraja',
            'Til', 'Narx', 'Talabalar', 'Darslar', 'Oylar',
            'Holat', 'Reyting', 'Yaratilgan',
        ])

        qs = self._get_export_queryset()
        for course in qs:
            writer.writerow([
                course.pk,
                course.title,
                course.category.name if course.category else '—',
                (
                    course.teacher.get_full_name()
                    if course.teacher else '—'
                ),
                course.get_level_display(),
                course.get_language_display(),
                float(course.current_price),
                course.students_count_annot or 0,
                course.lessons_count_annot or 0,
                course.months_count_annot or 0,
                course.get_status_display(),
                float(course.rating or 0),
                course.created_at.strftime('%d.%m.%Y %H:%M'),
            ])

        return response

    # ═══════════════════════════════════════════════════════════
    # EXCEL EKSPORT (openpyxl kerak)
    # ═══════════════════════════════════════════════════════════

    def _export_excel(self):
        """
        Kurslarni Excel (xlsx) formatda yuklab berish.
        openpyxl kutubxonasi kerak: pip install openpyxl
        """
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, PatternFill, Alignment
        except ImportError:
            # openpyxl yo'q — CSV ga qaytish
            messages.warning(
                self.request,
                "Excel kutubxonasi o'rnatilmagan. CSV yuklab olindi."
            )
            return self._export_csv()

        wb = Workbook()
        ws = wb.active
        ws.title = "Kurslar"

        # Sarlavha
        headers = [
            'ID', 'Nomi', 'Kategoriya', "O'qituvchi", 'Daraja',
            'Til', 'Narx', 'Talabalar', 'Darslar', 'Oylar',
            'Holat', 'Reyting', 'Yaratilgan',
        ]
        ws.append(headers)

        # Sarlavha stili
        header_fill = PatternFill(
            start_color='4F46E5', end_color='4F46E5', fill_type='solid'
        )
        header_font = Font(bold=True, color='FFFFFF', size=11)
        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal='center', vertical='center')

        # Ma'lumotlar
        qs = self._get_export_queryset()
        for course in qs:
            ws.append([
                course.pk,
                course.title,
                course.category.name if course.category else '—',
                (
                    course.teacher.get_full_name()
                    if course.teacher else '—'
                ),
                course.get_level_display(),
                course.get_language_display(),
                float(course.current_price),
                course.students_count_annot or 0,
                course.lessons_count_annot or 0,
                course.months_count_annot or 0,
                course.get_status_display(),
                float(course.rating or 0),
                course.created_at.strftime('%d.%m.%Y %H:%M'),
            ])

        # Ustunlar kengligi
        for col in ws.columns:
            max_length = 0
            column = col[0].column_letter
            for cell in col:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except Exception:
                    pass
            ws.column_dimensions[column].width = min(max_length + 2, 50)

        # Response
        response = HttpResponse(
            content_type=(
                'application/vnd.openxmlformats-officedocument'
                '.spreadsheetml.sheet'
            )
        )
        filename = f"courses_{timezone.now().strftime('%Y%m%d_%H%M')}.xlsx"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        wb.save(response)
        return response

    # ═══════════════════════════════════════════════════════════
    # PDF EKSPORT (print uchun HTML)
    # ═══════════════════════════════════════════════════════════

    def _export_pdf(self):
        """
        PDF uchun print-friendly HTML sahifa.
        Brauzer Ctrl+P → Save as PDF qilish mumkin.
        """
        courses = list(self._get_export_queryset()[:500])
        now = timezone.localtime().strftime('%d.%m.%Y %H:%M')

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Kurslar ro'yxati — {now}</title>
            <style>
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                body {{
                    font-family: 'Segoe UI', Arial, sans-serif;
                    padding: 20px;
                    color: #1a1a1a;
                }}
                h1 {{
                    font-size: 20px;
                    margin-bottom: 4px;
                    color: #4F46E5;
                }}
                .subtitle {{
                    font-size: 12px;
                    color: #666;
                    margin-bottom: 16px;
                }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                    font-size: 11px;
                }}
                th {{
                    background: #4F46E5;
                    color: white;
                    padding: 8px 6px;
                    text-align: left;
                    font-weight: 600;
                }}
                td {{
                    padding: 6px;
                    border-bottom: 1px solid #e5e7eb;
                }}
                tr:nth-child(even) {{ background: #f9fafb; }}
                .footer {{
                    margin-top: 20px;
                    font-size: 10px;
                    color: #999;
                    text-align: center;
                }}
                @media print {{
                    body {{ padding: 0; }}
                    .no-print {{ display: none; }}
                }}
            </style>
        </head>
        <body>
            <h1>📚 Kurslar ro'yxati</h1>
            <p class="subtitle">
                Jami: {len(courses)} ta kurs · {now}
            </p>
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Nomi</th>
                        <th>Kategoriya</th>
                        <th>O'qituvchi</th>
                        <th>Daraja</th>
                        <th>Narx</th>
                        <th>Talabalar</th>
                        <th>Holat</th>
                    </tr>
                </thead>
                <tbody>
        """

        for i, course in enumerate(courses, 1):
            html += f"""
                    <tr>
                        <td>{i}</td>
                        <td><b>{course.title}</b></td>
                        <td>{course.category.name if course.category else '—'}</td>
                        <td>{course.teacher.get_full_name() if course.teacher else '—'}</td>
                        <td>{course.get_level_display()}</td>
                        <td>{float(course.current_price):,.0f} so'm</td>
                        <td>{course.students_count_annot or 0}</td>
                        <td>{course.get_status_display()}</td>
                    </tr>
            """

        html += f"""
                </tbody>
            </table>
            <p class="footer">
                DIGION LMS · {now}
            </p>
            <script>
                window.onload = () => setTimeout(() => window.print(), 300);
            </script>
        </body>
        </html>
        """

        return HttpResponse(html)

    # ═══════════════════════════════════════════════════════════
    # YORDAMCHI: Export uchun queryset
    # ═══════════════════════════════════════════════════════════

    def _get_export_queryset(self):
        """
        Eksport uchun queryset (pagination'siz).
        Filtrlar qo'llaniladi.
        """
        return (
            Course.objects
            .filter(is_deleted=False)
            .select_related('category', 'teacher')
            .annotate(
                students_count_annot=Count('enrollments', distinct=True),
                months_count_annot=Count('months', distinct=True),
                lessons_count_annot=Count('lessons', distinct=True),
            )
            .order_by('-created_at')
        )

class CourseDetailView(AdminRequiredMixin, AdminContextMixin, DetailView):
    model = Course
    template_name = 'admin_user/courses/detail.html'
    context_object_name = 'course'

    def get_queryset(self):
        return Course.objects.filter(is_deleted=False)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        course = self.object
        today = timezone.now().date()

        # ═══ OYLAR — soft-delete filtri bilan ═══
        months = (course.months
                  .annotate(
            # Faqat live darslar
            lessons_count=Count(
                'lessons',
                filter=Q(lessons__is_deleted=False),  # ⭐ MUHIM
                distinct=True,
            ),
            completed_count=Count(
                'lessons',
                filter=Q(lessons__is_deleted=False,
                         lessons__status='completed'),  # ⭐ MUHIM
                distinct=True,
            ),
        )
                  .prefetch_related('lessons')
                  .order_by('month_number'))

        # ═══ DARSLAR — soft-delete filtri bilan ═══
        lessons_qs = (course.lessons
                      .filter(is_deleted=False)  # ⭐ MUHIM
                      .select_related('month')
                      .order_by(F('month__month_number').asc(nulls_last=True),
                                'lesson_number'))

        # ═══ GURUHLAR ═══
        groups = course.course_groups.annotate(
            students_count_annot=Count('students', distinct=True),
        )

        # ═══ TALABALAR ═══
        enrollments = (course.enrollments
        .select_related('student__user', 'group')
        .filter(status='active')
        .order_by('-enrolled_at')[:30])

        # ═══ UYGA VAZIFALAR — faqat live lesson'lar ═══
        homeworks = (Homework.objects
        .filter(lesson__course=course,
                lesson__is_deleted=False)  # ⭐ MUHIM
        .select_related('lesson')
        .order_by('-created_at')[:15])

        # ═══ TESTLAR ═══
        quizzes = (Quiz.objects
        .filter(course=course)
        .annotate(
            questions_count_annot=Count('questions', distinct=True),
            attempts_count_annot=Count('attempts', distinct=True))
        [:15])

        # ═══ FAOLIYAT ═══
        activities = []
        try:
            activities = (AuditLog.objects
            .filter(content_type__model='course', object_id=course.pk)
            .select_related('user')
            .order_by('-created_at')[:20])
        except Exception:
            pass

        # ═══ TOP TALABALAR ═══
        top_students = []
        try:
            top_students = (StudentProfile.objects
            .filter(enrollments__course=course)
            .select_related('user')
            .annotate(score_total=Sum('homework_submissions__score', default=0))
            .order_by('-score_total')[:5])
        except Exception:
            pass

        # ═══ SERTIFIKATLAR ═══
        certificates = []
        try:
            certificates = (Certificate.objects
            .filter(enrollment__course=course)
            .select_related('enrollment__student__user')[:10])
        except Exception:
            pass

        # ═══ CHART ═══
        chart_labels, chart_data = [], []
        for i in range(6, -1, -1):
            day = today - timedelta(days=i)
            chart_labels.append(day.strftime('%d.%m'))
            try:
                chart_data.append(AuditLog.objects.filter(
                    content_type__model='course', object_id=course.pk,
                    created_at__date=day).count())
            except Exception:
                chart_data.append(0)

        ctx.update({
            'stats': {
                'total_months': months.count(),
                'total_lessons': lessons_qs.count(),
                'total_students': course.enrollments.filter(status='active').count(),
                'total_homework': homeworks.count(),
                'total_quizzes': quizzes.count(),
                'total_groups': groups.count(),
                'avg_rating': course.average_rating,
                'completion_rate': course.completion_rate,
                'progress_percent': course.progress_percent,
                'days_remaining': course.days_remaining,
                'completed_students': course.enrollments.filter(status='completed').count(),
                'frozen_students': course.enrollments.filter(status='paused').count(),
            },
            'months': months,
            'lessons': lessons_qs[:80],
            'groups': groups,
            'enrollments': enrollments,
            'homeworks': homeworks,
            'quizzes': quizzes,
            'activities': activities,
            'top_students': top_students,
            'certificates': certificates,
            'chart_labels': chart_labels,
            'chart_data': chart_data,
            'level_choices': CourseLevel.choices,
            'language_choices': CourseLanguage.choices,
            'status_choices': CourseStatus.choices,
        })
        return ctx


class CourseCreateView(AdminRequiredMixin, AdminContextMixin, AuditLogMixin,
                       CreateView):
    model = Course
    form_class = CourseForm
    template_name = 'admin_user/courses/form.html'
    audit_action = 'create'

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        try:
            with transaction.atomic():
                response = super().form_valid(form)
                self.log_action(self.object, f"Yangi kurs: {self.object.title}")

                # Avtomatik oylar yaratish
                start = self.object.start_date or date.today()
                for i in range(1, self.object.duration_months + 1):
                    CourseMonth.objects.create(
                        course=self.object, month_number=i,
                        title=f"{i}-oy",
                        start_date=start + timedelta(days=30 * (i - 1)),
                        end_date=start + timedelta(days=30 * i - 1),
                    )
                messages.success(self.request, "✅ Kurs muvaffaqiyatli yaratildi!")
                return response
        except Exception as e:
            messages.error(self.request, f"❌ Xatolik: {e}")
            return self.form_invalid(form)

    def get_success_url(self):
        if self.request.POST.get('save_and_new'):
            return reverse('courses_admin:create')
        return reverse('courses_admin:detail', kwargs={'pk': self.object.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update({
            'page_settings': CourseFormPageSettings.load(),
            'mode': 'create',
            'categories': CourseCategory.objects.filter(is_active=True),
            'teachers': CustomUser.objects.filter(role='teacher', is_active=True)
                                       .order_by('first_name'),
        })
        return ctx


class CourseUpdateView(AdminRequiredMixin, AdminContextMixin, AuditLogMixin,
                       UpdateView):
    model = Course
    form_class = CourseForm
    template_name = 'admin_user/courses/form.html'
    audit_action = 'update'

    def get_queryset(self):
        return Course.objects.filter(is_deleted=False)

    def form_valid(self, form):
        try:
            with transaction.atomic():
                response = super().form_valid(form)
                self.log_action(self.object, f"Kurs tahrirlandi: {self.object.title}")
                messages.success(self.request, "✅ Kurs ma'lumotlari yangilandi!")
                return response
        except Exception as e:
            messages.error(self.request, f"❌ Xatolik: {e}")
            return self.form_invalid(form)

    def get_success_url(self):
        if self.request.POST.get('save_and_new'):
            return reverse('courses_admin:create')
        return reverse('courses_admin:detail', kwargs={'pk': self.object.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update({
            'page_settings': CourseFormPageSettings.load(),
            'mode': 'edit',
            'course': self.object,
            'categories': CourseCategory.objects.filter(is_active=True),
            'teachers': CustomUser.objects.filter(role='teacher', is_active=True)
                                       .order_by('first_name'),
        })
        return ctx


class CourseDeleteView(AdminRequiredMixin, AuditLogMixin, View):
    """Soft delete — POST only."""

    def post(self, request, pk):
        course = get_object_or_404(Course, pk=pk, is_deleted=False)
        try:
            course.soft_delete(request.user)
            self.log_action(course, f"Kurs o'chirildi: {course.title}")
            return JsonResponse({'success': True, 'message': "Kurs o'chirildi"})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)


class CourseDuplicateView(AdminRequiredMixin, AuditLogMixin, View):
    """Kursni nusxalash — POST only."""

    def post(self, request, pk):
        ps = CourseListPageSettings.load()
        course = get_object_or_404(Course, pk=pk, is_deleted=False)
        try:
            with transaction.atomic():
                new_course = Course.objects.create(
                    title=f"{course.title} {ps.msg_duplicate_suffix}",
                    short_description=course.short_description,
                    description=course.description,
                    category=course.category,
                    teacher=course.teacher,
                    start_date=course.start_date,
                    end_date=course.end_date,
                    duration_months=course.duration_months,
                    language=course.language,
                    level=course.level,
                    status='draft',
                    price=course.price,
                    discounted_price=course.discounted_price,
                    is_active=True,
                    is_featured=False,
                    created_by=request.user,
                )
                self.log_action(new_course, f"Kurs nusxalandi: {new_course.title}")
                return JsonResponse({
                    'success': True, 'new_id': new_course.pk,
                    'message': ps.msg_duplicated,
                })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)


# ═══════════════════════════════════════════════════════════════
# 2. COURSE MONTH VIEWS — TO'LIQ TO'PLAMI
# ═══════════════════════════════════════════════════════════════

class MonthCreateView(AdminRequiredMixin, AdminContextMixin, AjaxFormMixin,
                      AuditLogMixin, CreateView):
    """Yangi oy qo'shish — professional."""

    model = CourseMonth
    form_class = CourseMonthForm
    template_name = 'admin_user/courses/month_form.html'
    audit_action = 'create'

    def dispatch(self, request, *args, **kwargs):
        self.course = get_object_or_404(
            Course.objects.filter(is_deleted=False),
            pk=kwargs.get('course_pk')
        )
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        try:
            with transaction.atomic():
                form.instance.course = self.course

                # Keyingi raqam (race condition himoyasi)
                last = (
                    CourseMonth.objects
                    .select_for_update()
                    .filter(course=self.course)
                    .order_by('-month_number')
                    .first()
                )
                form.instance.month_number = (last.month_number + 1) if last else 1

                self.object = form.save()

                self.log_action(
                    self.object,
                    f"Yangi oy: {self.object.month_number}-oy — {self.object.title}"
                )

            msg = f"✅ {self.object.month_number}-oy qo'shildi!"

            if self.is_ajax():
                return JsonResponse({
                    'success': True,
                    'id': self.object.pk,
                    'month_number': self.object.month_number,
                    'title': self.object.title,
                    'message': msg,
                    'redirect_url': reverse(
                        'courses_admin:detail',
                        kwargs={'pk': self.course.pk}
                    ),
                })

            messages.success(self.request, msg)
            return redirect('courses_admin:detail', pk=self.course.pk)

        except IntegrityError as e:
            error_msg = f"Bu raqam bilan oy mavjud: {e}"
            if self.is_ajax():
                return JsonResponse({'success': False, 'error': error_msg}, status=400)
            messages.error(self.request, f"❌ {error_msg}")
            return self.form_invalid(form)

        except Exception as e:
            error_msg = f"Xatolik: {str(e)}"
            if self.is_ajax():
                return JsonResponse({'success': False, 'error': error_msg}, status=400)
            messages.error(self.request, f"❌ {error_msg}")
            return self.form_invalid(form)

    def form_invalid(self, form):
        """Forma xato bo'lganda — batafsil xato xabari."""
        # Xato matnlarini yig'ish
        error_list = []
        for field, errs in form.errors.items():
            for err in errs:
                if field == '__all__':
                    error_list.append(str(err))
                else:
                    label = form.fields[field].label if field in form.fields else field
                    error_list.append(f"{label}: {err}")

        if self.is_ajax():
            errors = {field: [str(e) for e in errs] for field, errs in form.errors.items()}
            return JsonResponse({
                'success': False,
                'errors': errors,
                'message': " | ".join(error_list) if error_list else "Formada xatolik",
            }, status=400)

        # Oddiy POST — aniq xato xabari
        if error_list:
            for err in error_list[:3]:  # faqat birinchi 3 tasi
                messages.error(self.request, f"❌ {err}")
        else:
            messages.error(self.request, "❌ Iltimos, formani tekshiring.")

        return super().form_invalid(form)
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        months_qs = self.course.months.order_by('month_number')
        last = months_qs.last()
        next_number = (last.month_number + 1) if last else 1
        total_lessons = sum(m.total_lessons for m in months_qs)

        ctx.update({
            'mode': 'create',
            'course': self.course,
            'month': None,
            'next_number': next_number,
            'existing_months': months_qs,
            'stats': {
                'total_months': months_qs.count(),
                'total_lessons': total_lessons,
                'max_months': self.course.duration_months,
                'remaining': max(0, self.course.duration_months - months_qs.count()),
            },
        })
        return ctx


class MonthUpdateView(AdminRequiredMixin, AdminContextMixin, AjaxFormMixin,
                      AuditLogMixin, UpdateView):
    """Oyni tahrirlash — professional."""

    model = CourseMonth
    form_class = CourseMonthForm
    template_name = 'admin_user/courses/month_form.html'
    pk_url_kwarg = 'pk'
    audit_action = 'update'

    def dispatch(self, request, *args, **kwargs):
        self.month = get_object_or_404(
            CourseMonth.objects.select_related('course'),
            pk=kwargs.get('pk')
        )
        if self.month.course.is_deleted:
            messages.error(request, "Bu kurs o'chirilgan!")
            return redirect('courses_admin:list')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        try:
            with transaction.atomic():
                # Eski qiymatlar
                old_data = {
                    'title': self.month.title,
                    'description': self.month.description,
                    'goals': self.month.goals,
                    'start_date': str(self.month.start_date) if self.month.start_date else None,
                    'end_date': str(self.month.end_date) if self.month.end_date else None,
                }

                self.object = form.save()

                # Yangi qiymatlar
                new_data = {
                    'title': self.object.title,
                    'description': self.object.description,
                    'goals': self.object.goals,
                    'start_date': str(self.object.start_date) if self.object.start_date else None,
                    'end_date': str(self.object.end_date) if self.object.end_date else None,
                }

                # Faqat o'zgarganlar
                changes = {
                    k: {'old': old_data[k], 'new': new_data[k]}
                    for k in old_data
                    if old_data[k] != new_data[k]
                }

                self.log_action(
                    self.object,
                    f"Oy tahrirlandi: {self.object.month_number}-oy — {self.object.title}",
                    changes=changes,
                )

            msg = "✅ Oy yangilandi!"

            if self.is_ajax():
                return JsonResponse({
                    'success': True,
                    'id': self.object.pk,
                    'message': msg,
                    'changes': list(changes.keys()),
                    'redirect_url': reverse(
                        'courses_admin:detail',
                        kwargs={'pk': self.object.course.pk}
                    ),
                })

            messages.success(self.request, msg)
            return redirect('courses_admin:detail', pk=self.object.course.pk)

        except Exception as e:
            error_msg = f"Xatolik: {str(e)}"
            if self.is_ajax():
                return JsonResponse({'success': False, 'error': error_msg}, status=400)
            messages.error(self.request, f"❌ {error_msg}")
            return self.form_invalid(form)

    def form_invalid(self, form):
        """Forma xato bo'lganda — batafsil xato xabari."""
        error_list = []
        for field, errs in form.errors.items():
            for err in errs:
                if field == '__all__':
                    error_list.append(str(err))
                else:
                    label = form.fields[field].label if field in form.fields else field
                    error_list.append(f"{label}: {err}")

        if self.is_ajax():
            errors = {field: [str(e) for e in errs] for field, errs in form.errors.items()}
            return JsonResponse({
                'success': False,
                'errors': errors,
                'message': " | ".join(error_list) if error_list else "Formada xatolik",
            }, status=400)

        if error_list:
            for err in error_list[:3]:
                messages.error(self.request, f"❌ {err}")
        else:
            messages.error(self.request, "❌ Iltimos, formani tekshiring.")

        return super().form_invalid(form)
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        months_qs = self.month.course.months.order_by('month_number')
        ctx.update({
            'mode': 'edit',
            'month': self.month,
            'course': self.month.course,
            'existing_months': months_qs,
            'stats': {
                'total_months': months_qs.count(),
                'month_lessons': self.month.total_lessons,
                'month_progress': self.month.progress_percent,
                'month_completed': self.month.is_completed,
            },
        })
        return ctx


class MonthDeleteView(AdminRequiredMixin, AuditLogMixin, View):
    """Oyni o'chirish — AJAX only."""

    def post(self, request, pk):
        month = get_object_or_404(
            CourseMonth.objects.select_related('course'),
            pk=pk
        )

        if month.course.is_deleted:
            return JsonResponse({
                'success': False,
                'error': "Kurs o'chirilgan"
            }, status=400)

        lessons_count = month.lessons.count()
        force = request.POST.get('force') == '1'

        if lessons_count > 0 and not force:
            return JsonResponse({
                'success': False,
                'error': f"Bu oyda {lessons_count} ta dars bor!",
                'requires_confirm': True,
                'lessons_count': lessons_count,
            }, status=400)

        try:
            with transaction.atomic():
                month_title = month.title
                month_number = month.month_number
                course_pk = month.course.pk

                month.delete()

                try:
                    from django.contrib.contenttypes.models import ContentType
                    AuditLog.objects.create(
                        user=request.user,
                        action='delete',
                        content_type=ContentType.objects.get_for_model(CourseMonth),
                        object_id=pk,
                        description=f"Oy o'chirildi: {month_number}-oy — {month_title}",
                    )
                except Exception:
                    pass

            return JsonResponse({
                'success': True,
                'message': f"'{month_title}' o'chirildi",
                'lessons_deleted': lessons_count,
                'redirect_url': reverse(
                    'courses_admin:detail',
                    kwargs={'pk': course_pk}
                ),
            })

        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f"O'chirishda xatolik: {str(e)}"
            }, status=400)


class MonthQuickStatsView(AdminRequiredMixin, View):
    """Oy statistikasi — AJAX uchun."""

    def get(self, request, pk):
        month = get_object_or_404(
            CourseMonth.objects.select_related('course'),
            pk=pk
        )

        try:
            return JsonResponse({
                'success': True,
                'month': {
                    'id': month.pk,
                    'number': month.month_number,
                    'title': month.title,
                    'description': month.description,
                    'goals': month.goals,
                    'lessons_count': month.total_lessons,
                    'completed_lessons': month.completed_lessons,
                    'progress': month.progress_percent,
                    'is_completed': month.is_completed,
                    'is_active': month.is_active,
                    'start_date': month.start_date.isoformat() if month.start_date else None,
                    'end_date': month.end_date.isoformat() if month.end_date else None,
                    'course': {
                        'id': month.course.pk,
                        'title': month.course.title,
                    },
                }
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=400)

# ═══════════════════════════════════════════════════════════════
# 3. LESSON VIEWS
# ═══════════════════════════════════════════════════════════════
class LessonListView(AdminRequiredMixin, AdminContextMixin, ListView):
    """
    Darslar ro'yxati — barcha kurslar bo'yicha.

    Xususiyatlar:
    - Qidiruv (sarlavha, kurs, mavzu)
    - Filtrlar (kurs, oy, status, tur)
    - Sort
    - Pagination
    - Statistika
    """
    model = Lesson
    template_name = 'admin_user/courses/lesson_list.html'
    context_object_name = 'lessons'
    paginate_by = 20

    def get_paginate_by(self, queryset):
        try:
            n = int(self.request.GET.get('per_page', 20))
            return n if n in (20, 40, 80, 100) else 20
        except (TypeError, ValueError):
            return 20

    def get_queryset(self):
        qs = (Lesson.objects
              .filter(is_deleted=False)
              .select_related('course', 'month')
              .order_by('-lesson_date', '-created_at'))

        # ═══ Qidiruv ═══
        search = self.request.GET.get('q', '').strip()
        if search:
            qs = qs.filter(
                Q(title__icontains=search) |
                Q(topic__icontains=search) |
                Q(short_description__icontains=search) |
                Q(course__title__icontains=search)
            )

        # ═══ Filtrlar ═══
        course_id = self.request.GET.get('course', '').strip()
        if course_id:
            qs = qs.filter(course_id=course_id)

        month_id = self.request.GET.get('month', '').strip()
        if month_id:
            qs = qs.filter(month_id=month_id)

        status = self.request.GET.get('status', '').strip()
        if status:
            qs = qs.filter(status=status)

        lesson_type = self.request.GET.get('type', '').strip()
        if lesson_type:
            qs = qs.filter(lesson_type=lesson_type)

        # ═══ Sort ═══
        sort = self.request.GET.get('sort', '-lesson_date')
        allowed = {
            '-lesson_date', 'lesson_date',
            'lesson_number', '-lesson_number',
            'title', '-title',
            'created_at', '-created_at',
        }
        if sort in allowed:
            qs = qs.order_by(sort)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        all_lessons = Lesson.objects.filter(is_deleted=False)

        stats = {
            'total': all_lessons.count(),
            'planned': all_lessons.filter(status='planned').count(),
            'in_progress': all_lessons.filter(status='in_progress').count(),
            'completed': all_lessons.filter(status='completed').count(),
            'with_homework': all_lessons.filter(
                id__in=Homework.objects.values_list('lesson_id', flat=True)
            ).count(),
            'with_quiz': all_lessons.filter(
                id__in=Quiz.objects.values_list('lesson_id', flat=True)
            ).count(),
        }

        ctx.update({
            'stats': stats,
            'courses': Course.objects.filter(is_deleted=False).order_by('title'),
            'months': CourseMonth.objects.select_related('course').order_by(
                'course__title', 'month_number'
            ),
            'status_choices': LessonStatus.choices,
            'type_choices': LessonType.choices,
            'search': self.request.GET.get('q', ''),
            'course_filter': self.request.GET.get('course', ''),
            'month_filter': self.request.GET.get('month', ''),
            'status_filter': self.request.GET.get('status', ''),
            'type_filter': self.request.GET.get('type', ''),
            'sort': self.request.GET.get('sort', '-lesson_date'),
            'per_page': self.get_paginate_by(None),
            'per_page_options': [20, 40, 80, 100],
            'now': timezone.now(),
        })
        return ctx

class LessonDetailView(AdminRequiredMixin, AdminContextMixin, DetailView):
    model = Lesson
    template_name = 'admin_user/courses/lesson_detail.html'
    context_object_name = 'lesson'

    def get_queryset(self):
        return Lesson.objects.filter(is_deleted=False).select_related('course', 'month')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        lesson = self.object
        ctx.update({
            'homework': getattr(lesson, 'homework', None),
            'quiz': getattr(lesson, 'test', None),
            'attendance': (lesson.attendance.select_related('student__user')[:30]
                           if hasattr(lesson, 'attendance') else []),
            'group_assignments': lesson.group_assignments
                                       .select_related('group')[:20],
        })
        return ctx


class LessonCreateView(AdminRequiredMixin, AdminContextMixin, AjaxFormMixin,
                       AuditLogMixin, CreateView):
    model = Lesson
    form_class = LessonForm
    template_name = 'admin_user/courses/lesson_form.html'
    audit_action = 'create'

    def dispatch(self, request, *args, **kwargs):
        month_pk = kwargs.get('month_pk')
        if not month_pk:
            messages.error(request, "Oy tanlanmagan!")
            return redirect('courses_admin:list')
        self.month = get_object_or_404(CourseMonth, pk=month_pk)
        self.course = self.month.course
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw['course'] = self.course
        return kw

    def form_valid(self, form):
        form.instance.course = self.course
        form.instance.month = self.month
        try:
            with transaction.atomic():
                self.object = form.save()
                self.log_action(self.object, f"Yangi dars: {self.object.title}")

                if self.is_ajax():
                    return JsonResponse({
                        'success': True, 'id': self.object.pk,
                        'message': f"'{self.object.title}' qo'shildi!",
                        'redirect_url': reverse('courses_admin:lesson_detail',
                                                kwargs={'pk': self.object.pk}),
                    })
                messages.success(self.request, f"✅ '{self.object.title}' qo'shildi!")
                return redirect('courses_admin:lesson_detail', pk=self.object.pk)
        except Exception as e:
            if self.is_ajax():
                return JsonResponse({'success': False, 'error': str(e)}, status=400)
            messages.error(self.request, f"❌ Xatolik: {e}")
            return self.form_invalid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update({
            'mode': 'create', 'course': self.course, 'month': self.month,
            'groups': StudentGroup.objects.filter(course=self.course,
                                                   is_deleted=False),
        })
        return ctx


class LessonUpdateView(AdminRequiredMixin, AdminContextMixin, AjaxFormMixin,
                       AuditLogMixin, UpdateView):
    model = Lesson
    form_class = LessonForm
    template_name = 'admin_user/courses/lesson_form.html'
    audit_action = 'update'

    def get_queryset(self):
        return Lesson.objects.filter(is_deleted=False)

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw['course'] = self.object.course
        return kw

    def form_valid(self, form):
        try:
            with transaction.atomic():
                self.object = form.save()
                self.log_action(self.object, f"Dars tahrirlandi: {self.object.title}")
                if self.is_ajax():
                    return JsonResponse({'success': True, 'message': "Dars yangilandi ✅"})
                messages.success(self.request, "✅ Dars yangilandi!")
                return redirect('courses_admin:lesson_detail', pk=self.object.pk)
        except Exception as e:
            if self.is_ajax():
                return JsonResponse({'success': False, 'error': str(e)}, status=400)
            messages.error(self.request, f"❌ Xatolik: {e}")
            return self.form_invalid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update({
            'mode': 'edit', 'lesson': self.object,
            'course': self.object.course, 'month': self.object.month,
            'groups': StudentGroup.objects.filter(course=self.object.course,
                                                   is_deleted=False),
        })
        return ctx


class LessonDeleteView(AdminRequiredMixin, AuditLogMixin, View):
    def post(self, request, pk):
        lesson = get_object_or_404(Lesson, pk=pk, is_deleted=False)
        try:
            lesson.soft_delete(request.user)
            self.log_action(lesson, f"Dars o'chirildi: {lesson.title}")
            return JsonResponse({'success': True, 'message': "Dars o'chirildi"})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)


class LessonMarkCompleteView(AdminRequiredMixin, View):
    """
    Darsni tugallangan deb belgilash + AUTO-FLOW:
    - Uyga vazifa guruhga yuboriladi (Telegram)
    - Status o'zgaradi
    - Audit log yoziladi
    """

    def post(self, request, pk):
        lesson = get_object_or_404(Lesson, pk=pk, is_deleted=False)
        group_ids = request.POST.getlist('group_ids')

        try:
            with transaction.atomic():
                lesson.status = 'completed'
                lesson.lesson_date = timezone.now().date()
                lesson.save(update_fields=['status', 'lesson_date'])

                sent_total, failed_total, errors = 0, 0, []
                homework = getattr(lesson, 'homework', None)

                if homework and group_ids:
                    homework.is_approved = True
                    homework.approved_by = request.user
                    homework.approved_at = timezone.now()
                    homework.save()

                    try:
                        from apps.service.notification_service import send_homework_to_group
                        for gid in group_ids:
                            grp = StudentGroup.objects.filter(id=gid).first()
                            if not grp:
                                continue
                            res = send_homework_to_group(homework, grp, request.user)
                            sent_total += res.get('sent_count', 0)
                            failed_total += res.get('failed_count', 0)
                            homework.sent_to_groups.add(grp)
                        homework.is_sent = True
                        homework.sent_at = timezone.now()
                        homework.save()
                    except Exception as e:
                        errors.append(f"Telegram: {e}")

                # Audit
                try:
                    AuditLog.objects.create(
                        user=request.user, action='update',
                        content_type=ContentType.objects.get_for_model(Lesson),
                        object_id=lesson.pk,
                        description=f"Dars tugatildi: {lesson.title}",
                    )
                except Exception:
                    pass

                return JsonResponse({
                    'success': True,
                    'message': f"Dars tugatildi. {sent_total} talabaga yuborildi",
                    'sent_count': sent_total,
                    'failed_count': failed_total,
                    'errors': errors,
                })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)


# ═══════════════════════════════════════════════════════════════
# 4. HOMEWORK VIEWS
# ═══════════════════════════════════════════════════════════════

class HomeworkFormView(AdminRequiredMixin, AdminContextMixin, AuditLogMixin, View):
    """Uyga vazifa formasi — GET: ko'rsatish, POST: saqlash."""

    template_name = 'admin_user/courses/homework_form.html'

    def get(self, request, lesson_pk):
        lesson = get_object_or_404(
            Lesson.objects.select_related('course', 'month'),
            pk=lesson_pk, is_deleted=False,
        )
        existing = getattr(lesson, 'homework', None)
        form = HomeworkForm(instance=existing, lesson=lesson)

        return render(request, self.template_name,
                      self._ctx(lesson, existing, form))

    def post(self, request, lesson_pk):
        lesson = get_object_or_404(
            Lesson.objects.select_related('course', 'month'),
            pk=lesson_pk, is_deleted=False,
        )
        existing = getattr(lesson, 'homework', None)

        form = HomeworkForm(
            request.POST,
            request.FILES,
            instance=existing,
            lesson=lesson,
        )

        # ─── FORM INVALID ───
        if not form.is_valid():
            # Har bir maydon xatosini aniq ko'rsatish
            for field, errors in form.errors.items():
                for err in errors:
                    if field == '__all__':
                        messages.error(request, f"❌ {err}")
                    else:
                        label = form.fields[field].label if field in form.fields else field
                        messages.error(request, f"❌ {label}: {err}")
            return render(request, self.template_name,
                          self._ctx(lesson, existing, form))

        # ─── SAVE ───
        try:
            with transaction.atomic():
                hw = form.save(commit=False)
                hw.lesson = lesson
                if not hw.created_by_id:
                    hw.created_by = request.user
                hw.save()

                # ⭐ MUHIM: M2M (extra_quizzes) saqlash
                form.save_m2m()

                self.log_action(hw, f"Uyga vazifa saqlandi: {hw.title}")
                messages.success(request, "✅ Uyga vazifa saqlandi!")
                return redirect('courses_admin:lesson_detail', pk=lesson.pk)

        except Exception as e:
            import traceback
            traceback.print_exc()
            messages.error(request, f"❌ Xatolik: {e}")
            return render(request, self.template_name,
                          self._ctx(lesson, existing, form))

    def _ctx(self, lesson, existing, form):
        """Context — barcha kerakli ma'lumotlar."""
        quizzes = (
            Quiz.objects
            .filter(course=lesson.course, is_active=True)
            .order_by('-created_at')
        )

        # Tanlangan qo'shimcha testlar (tahrirlashda)
        selected_quiz_ids = []
        if existing and existing.pk:
            try:
                selected_quiz_ids = list(
                    existing.extra_quizzes.values_list('pk', flat=True)
                )
            except Exception:
                selected_quiz_ids = []

        return {
            'current_url': 'courses',
            'lesson': lesson,
            'homework': existing,
            'form': form,
            'quizzes': quizzes,
            'selected_quiz_ids': selected_quiz_ids,
            'type_choices': Homework._meta.get_field('homework_type').choices,
        }
# ═══════════════════════════════════════════════════════════════
# 5. QUIZ VIEWS
# ═══════════════════════════════════════════════════════════════

class QuizFormView(AdminRequiredMixin, AdminContextMixin, AuditLogMixin, View):
    """
    Test yaratish/tahrirlash + savollar ro'yxati.
    GET: form + mavjud savollar
    POST: saqlash → shu sahifaga qaytish (savollar qo'shish uchun)
    """
    template_name = 'admin_user/courses/quiz_form.html'

    # ═══════════════════════════════════════════════════════════
    # GET — sahifani ko'rsatish
    # ═══════════════════════════════════════════════════════════
    def get(self, request, lesson_pk):
        lesson = get_object_or_404(
            Lesson.objects.select_related('course', 'month'),
            pk=lesson_pk,
            is_deleted=False,
        )
        existing = getattr(lesson, 'test', None)
        form = QuizForm(instance=existing)

        return render(
            request,
            self.template_name,
            self._ctx(lesson, existing, form),
        )

    # ═══════════════════════════════════════════════════════════
    # POST — saqlash
    # ═══════════════════════════════════════════════════════════
    def post(self, request, lesson_pk):
        lesson = get_object_or_404(
            Lesson.objects.select_related('course', 'month'),
            pk=lesson_pk,
            is_deleted=False,
        )
        existing = getattr(lesson, 'test', None)
        form = QuizForm(request.POST, instance=existing)

        # ═══ VALIDATSIYA XATOLARI ═══
        if not form.is_valid():
            # 1. Terminal'ga to'liq chiqarish
            print("\n" + "=" * 70)
            print("❌ QUIZ FORM XATOLARI:")
            print("=" * 70)
            for field, errors in form.errors.items():
                for err in errors:
                    print(f"   [{field}]: {err}")
            print("-" * 70)
            print("POST data:", {k: v for k, v in request.POST.items()})
            print("=" * 70 + "\n")

            # 2. Foydalanuvchiga aniq xabar
            for field, errors in form.errors.items():
                for err in errors:
                    if field == '__all__':
                        messages.error(request, f"❌ {err}")
                    else:
                        try:
                            label = form.fields[field].label or field
                        except (KeyError, AttributeError):
                            label = field
                        messages.error(request, f"❌ {label}: {err}")

            return render(
                request,
                self.template_name,
                self._ctx(lesson, existing, form),
            )

        # ═══ SAQLASH ═══
        try:
            with transaction.atomic():
                quiz = form.save(commit=False)
                quiz.course = lesson.course
                quiz.lesson = lesson
                quiz.is_active = True
                if not quiz.created_by_id:
                    quiz.created_by = request.user
                quiz.save()

                self.log_action(quiz, f"Test saqlandi: {quiz.title}")
                messages.success(
                    request,
                    "✅ Test saqlandi! Endi savollar qo'shing."
                )

                # ⭐ SHU SAHIFAGA qaytish (savollar qo'shish uchun)
                return redirect('courses_admin:quiz_form', lesson_pk=lesson.pk)

        except Exception as e:
            import traceback
            traceback.print_exc()
            messages.error(request, f"❌ Saqlashda xatolik: {e}")
            return render(
                request,
                self.template_name,
                self._ctx(lesson, existing, form),
            )

    # ═══════════════════════════════════════════════════════════
    # CONTEXT
    # ═══════════════════════════════════════════════════════════
    def _ctx(self, lesson, existing, form):
        """
        Shablon uchun barcha kerakli ma'lumotlar.
        """
        # Savollar ro'yxati (tahrirlashda)
        questions = []
        if existing and existing.pk:
            questions = list(
                existing.questions
                .prefetch_related('options')
                .order_by('order', 'id')
            )

        return {
            'current_url': 'courses',
            'lesson': lesson,
            'quiz': existing,
            'form': form,
            'questions': questions,
            'difficulty_choices': Quiz._meta.get_field('difficulty').choices,
        }



class QuestionCreateView(AdminRequiredMixin, View):
    def post(self, request, quiz_pk):
        quiz = get_object_or_404(Quiz, pk=quiz_pk)
        text = (request.POST.get('text') or '').strip()
        if not text:
            return JsonResponse({'success': False, 'error': "Savol matni bo'sh"}, status=400)

        last = quiz.questions.order_by('-order').first()
        order = (last.order + 1) if last else 1

        q = Question.objects.create(
            quiz=quiz, text=text,
            question_type=request.POST.get('question_type', 'single'),
            points=_safe_int(request.POST.get('points'), 1),
            order=order,
            explanation=(request.POST.get('explanation') or '').strip(),
        )
        return JsonResponse({'success': True, 'id': q.pk, 'message': "Savol qo'shildi"})


class QuestionDeleteView(AdminRequiredMixin, View):
    def post(self, request, pk):
        q = get_object_or_404(Question, pk=pk)
        q.delete()
        return JsonResponse({'success': True, 'message': "Savol o'chirildi"})


class ChoiceCreateView(AdminRequiredMixin, View):
    def post(self, request, question_pk):
        q = get_object_or_404(Question, pk=question_pk)
        text = (request.POST.get('text') or '').strip()
        if not text:
            return JsonResponse({'success': False, 'error': "Variant matni bo'sh"}, status=400)

        is_correct = request.POST.get('is_correct') == '1'
        if is_correct and q.question_type == 'single':
            q.options.update(is_correct=False)

        last = q.options.order_by('-order').first()
        order = (last.order + 1) if last else 1

        c = AnswerOption.objects.create(
            question=q, text=text, is_correct=is_correct, order=order,
        )
        return JsonResponse({'success': True, 'id': c.pk, 'message': "Variant qo'shildi"})


class ChoiceDeleteView(AdminRequiredMixin, View):
    def post(self, request, pk):
        c = get_object_or_404(AnswerOption, pk=pk)
        c.delete()
        return JsonResponse({'success': True, 'message': "Variant o'chirildi"})


# ═══════════════════════════════════════════════════════════════
# 6. GROUP VIEWS
# ═══════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════
# 6. GROUP VIEWS — TO'LIQ PROFESSIONAL
# ═══════════════════════════════════════════════════════════════

class GroupListView(AdminRequiredMixin, AdminContextMixin, ListView):
    """
    Guruhlar ro'yxati — professional.

    Xususiyatlar:
    - Qidiruv (nom, kod, kurs, o'qituvchi)
    - Filtrlar (status, kurs, o'qituvchi)
    - Sort
    - Pagination
    - Statistika
    """
    model = StudentGroup
    template_name = 'admin_user/courses/group_list.html'
    context_object_name = 'groups'
    paginate_by = 12

    def get_paginate_by(self, queryset):
        try:
            n = int(self.request.GET.get('per_page', 12))
            return n if n in (12, 24, 48, 96) else 12
        except (TypeError, ValueError):
            return 12

    def get_queryset(self):
        # ⭐ Subquery'lar — GroupLesson to'g'ri bog'lanishi uchun
        lessons_count_sq = (
            GroupLesson.objects
            .filter(group_id=OuterRef('pk'))
            .values('group_id')
            .annotate(c=Count('id'))
            .values('c')
        )
        completed_count_sq = (
            GroupLesson.objects
            .filter(group_id=OuterRef('pk'), is_completed=True)
            .values('group_id')
            .annotate(c=Count('id'))
            .values('c')
        )

        qs = (StudentGroup.objects
        .filter(is_deleted=False)
        .select_related('course', 'teacher', 'assistant')
        .annotate(
            students_count_annot=Count('students', distinct=True),
            lessons_count_annot=Coalesce(
                Subquery(lessons_count_sq, output_field=IntegerField()), 0
            ),
            completed_lessons_annot=Coalesce(
                Subquery(completed_count_sq, output_field=IntegerField()), 0
            ),
        ))

        # Qidiruv (o'zgarmaydi)
        search = self.request.GET.get('q', '').strip()
        if search:
            qs = qs.filter(
                Q(name__icontains=search) |
                Q(code__icontains=search) |
                Q(description__icontains=search) |
                Q(course__title__icontains=search) |
                Q(teacher__first_name__icontains=search) |
                Q(teacher__last_name__icontains=search) |
                Q(teacher__phone_number__icontains=search)
            )

        # Filtrlar (o'zgarmaydi)
        status = self.request.GET.get('status', '').strip()
        if status:
            qs = qs.filter(status=status)

        course_id = self.request.GET.get('course', '').strip()
        if course_id:
            qs = qs.filter(course_id=course_id)

        teacher_id = self.request.GET.get('teacher', '').strip()
        if teacher_id:
            qs = qs.filter(teacher_id=teacher_id)

        # Sort
        sort = self.request.GET.get('sort', '-created_at')
        allowed = {
            '-created_at', 'created_at', 'name', '-name',
            '-students_count_annot', '-lessons_count_annot',
        }
        if sort in allowed:
            qs = qs.order_by(sort)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        all_groups = StudentGroup.objects.filter(is_deleted=False)

        # ⭐ Xavfsiz statistika — try/except bilan
        try:
            total_students_count = (
                StudentProfile.objects
                .filter(course_groups__in=all_groups)  # ⭐ M2M to'g'ri
                .distinct()
                .count()
            )
        except Exception:
            total_students_count = 0

        try:
            total_lessons_count = GroupLesson.objects.count()  # ⭐ Hammasi
        except Exception:
            total_lessons_count = 0

        stats = {
            'total': all_groups.count(),
            'active': all_groups.filter(status='active').count(),
            'paused': all_groups.filter(status='paused').count(),
            'finished': all_groups.filter(status='finished').count(),
            'archived': all_groups.filter(status='archived').count(),
            'total_students': total_students_count,  # ⭐ Yangi
            'total_lessons': total_lessons_count,  # ⭐ Yangi
        }

        ctx.update({
            'stats': stats,
            'courses': Course.objects.filter(is_deleted=False).order_by('title'),
            'teachers': CustomUser.objects.filter(
                role='teacher', is_active=True
            ).order_by('first_name'),
            'status_choices': StudentGroup._meta.get_field('status').choices,
            'search': self.request.GET.get('q', ''),
            'status_filter': self.request.GET.get('status', ''),
            'course_filter': self.request.GET.get('course', ''),
            'teacher_filter': self.request.GET.get('teacher', ''),
            'sort': self.request.GET.get('sort', '-created_at'),
            'per_page': self.get_paginate_by(None),
            'per_page_options': [12, 24, 48, 96],
            'now': timezone.now(),
        })
        return ctx

class GroupDetailView(AdminRequiredMixin, AdminContextMixin, DetailView):
    """
    Guruh tafsilotlari — professional.

    - Talabalar ro'yxati (statistika bilan)
    - Darslar jadvali
    - Jadval ko'rinishi
    - Statistika
    """
    model = StudentGroup
    template_name = 'admin_user/courses/group_detail.html'
    context_object_name = 'group'

    def get_queryset(self):
        return (StudentGroup.objects
                .filter(is_deleted=False)
                .select_related('course', 'teacher', 'assistant'))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        group = self.object
        # ⭐ Mavjud bo'lmagan talabalar (modal uchun)
        available_students_data = []   # ⭐ MUHIM: oldindan e'lon qilish
        try:
            current_student_ids = list(group.students.values_list('id', flat=True))
            available_students = (StudentProfile.objects
                .exclude(id__in=current_student_ids)
                .select_related('user')
                .filter(user__is_active=True)
                .order_by('user__first_name', 'user__last_name')[:500])
            available_students_data = [
                {
                    'id': s.id,
                    'name': s.user.get_full_name() or s.user.phone_number,
                    'phone': getattr(s.user, 'phone_number', '') or '',
                    'avatar': (
                        (s.user.first_name[:1] if s.user.first_name else '?')
                        + (s.user.last_name[:1] if s.user.last_name else '')
                    ).upper(),
                }
                for s in available_students
            ]
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"available_students xato: {e}")
            available_students_data = []

        # ═══ Talabalar (statistika bilan) ═══
        students = (group.students
                    .select_related('user')
                    .annotate(
                        total_score_annot=Sum(
                            'homework_submissions__score', default=0
                        ),
                        submissions_count_annot=Count(
                            'homework_submissions', distinct=True
                        ),
                    )
                    .order_by('-total_score_annot'))

        # ═══ Darslar ═══
        lessons_qs = (GroupLesson.objects
                      .filter(group_id=group.pk)
                      .select_related(
                          'lesson', 'lesson__month', 'lesson__homework'
                      )
                      .order_by('lesson_date', 'order_in_group'))

        # ═══ Statistika ═══
        total_lessons = lessons_qs.count()
        completed_lessons = lessons_qs.filter(is_completed=True).count()
        upcoming_lessons = lessons_qs.filter(
            lesson_date__gte=timezone.now().date()
        ).count()

        # ═══ Jadval ko'rinishi (kunlar bo'yicha) ═══
        # ═══ Jadval ko'rinishi (kunlar bo'yicha) ═══
        day_map = {
            'monday': 0, 'tuesday': 1, 'wednesday': 2,
            'thursday': 3, 'friday': 4, 'saturday': 5, 'sunday': 6,
        }
        day_names_uz = {
            'monday': 'Dushanba', 'tuesday': 'Seshanba',
            'wednesday': 'Chorshanba', 'thursday': 'Payshanba',
            'friday': 'Juma', 'saturday': 'Shanba',
            'sunday': 'Yakshanba',
        }
        schedule = group.schedule or {}
        schedule_items = []
        for day, time in sorted(
                schedule.items(),
                key=lambda x: day_map.get(x[0], 99)
        ):
            schedule_items.append({
                'day_code': day,
                'day_name': day_names_uz.get(day, day),  # ⭐ TUZATILDI
                'time': time,
            })

        # ═══ Rang ═══
        group_color = group.color or '#06b6d4'

        # ═══ Statistika dict ═══
        stats = {
            'total_students': students.count(),
            'max_students': group.max_students,
            'capacity_percent': group.capacity_percent,
            'total_lessons': total_lessons,
            'completed_lessons': completed_lessons,
            'upcoming_lessons': upcoming_lessons,
            'progress_percent': (
                round((completed_lessons / total_lessons) * 100, 1)
                if total_lessons else 0
            ),
            'average_score': group.average_score,
            'total_coins': group.total_coins,
            'active_week': group.active_week,
            'has_capacity': group.has_capacity,
        }

        ctx.update({
            'students': students,
            'lessons': lessons_qs[:80],
            'total_lessons': total_lessons,
            'completed_lessons': completed_lessons,
            'stats': stats,
            'schedule_items': schedule_items,
            'group_color': group_color,
            'day_names': {
                'monday': 'Dushanba', 'tuesday': 'Seshanba',
                'wednesday': 'Chorshanba', 'thursday': 'Payshanba',
                'friday': 'Juma', 'saturday': 'Shanba',
                'sunday': 'Yakshanba',
            },
            'status_choices': StudentGroup._meta.get_field('status').choices,
            'available_students_json': available_students_data,
        })
        # ⭐ Mavjud bo'lmagan talabalar (modal uchun)

        return ctx


class GroupLessonHomeworkSendView(AdminRequiredMixin, View):
    """Guruhdagi dars uyga vazifasini adminning aniq so'rovi bilan yuborish."""

    def post(self, request, group_pk, gl_pk):
        group = get_object_or_404(
            StudentGroup, pk=group_pk, is_deleted=False
        )
        group_lesson = get_object_or_404(
            GroupLesson.objects.select_related(
                'lesson', 'lesson__homework'
            ),
            pk=gl_pk,
            group=group,
            is_deleted=False,
        )
        homework = getattr(group_lesson.lesson, 'homework', None)

        if not homework:
            messages.error(request, "Bu darsga uyga vazifa biriktirilmagan.")
        elif not homework.is_approved:
            messages.error(
                request,
                "Uyga vazifa tasdiqlanmagan. Avval vazifani tasdiqlang.",
            )
        else:
            from .tasks import send_homework_to_group_job

            result = send_homework_to_group_job(
                group_lesson.pk, manual=True
            )
            if not result.get('ok'):
                reason = result.get('reason')
                if reason == 'already_sent':
                    messages.warning(
                        request,
                        "Bu darsning uyga vazifasi allaqachon yuborilgan "
                        "yoki yuborilmoqda.",
                    )
                else:
                    messages.error(
                        request,
                        "Uyga vazifani yuborib bo'lmadi. "
                        "Xatolik jurnalini tekshiring.",
                    )
            elif result.get('status') == 'sent':
                messages.success(
                    request,
                    f"Uyga vazifa {result['sent']} nafar talabaga yuborildi.",
                )
            elif result.get('status') == 'partial':
                messages.warning(
                    request,
                    f"{result['sent']} nafar talabaga yuborildi, "
                    f"{result['failed']} nafariga yuborilmadi.",
                )
            else:
                messages.error(
                    request,
                    "Uyga vazifa hech bir talabaga yuborilmadi. "
                    "Telegram ulanishlarini tekshiring.",
                )

        return redirect('courses_admin:group_detail', pk=group.pk)


class GroupCreateView(AdminRequiredMixin, AdminContextMixin, AuditLogMixin,
                      CreateView):
    """
    Yangi guruh yaratish — professional.

    - Transaction
    - Audit log
    - Jadvalni JSON ga o'tkazish
    - Xato boshqaruvi
    """
    model = StudentGroup
    form_class = GroupForm
    template_name = 'admin_user/courses/group_form.html'
    audit_action = 'create'

    def form_valid(self, form):
        try:
            with transaction.atomic():
                # Guruhni saqlash (jadval ham GroupForm.save da)
                self.object = form.save()

                # Audit log
                self.log_action(
                    self.object,
                    f"Yangi guruh: {self.object.name} "
                    f"({self.object.students_count} talaba)"
                )

            messages.success(
                self.request,
                f"✅ '{self.object.name}' guruhi yaratildi!"
            )
            return redirect('courses_admin:group_detail', pk=self.object.pk)

        except IntegrityError as e:
            error_msg = f"Dublikat xato: {str(e)}"
            messages.error(self.request, f"❌ {error_msg}")
            return self.form_invalid(form)

        except Exception as e:
            error_msg = f"Xatolik: {str(e)}"
            messages.error(self.request, f"❌ {error_msg}")
            return self.form_invalid(form)

    def form_invalid(self, form):
        """Forma xatolari — aniq ko'rsatish."""
        error_list = []
        for field, errs in form.errors.items():
            for err in errs:
                if field == '__all__':
                    error_list.append(str(err))
                else:
                    label = form.fields[field].label if field in form.fields else field
                    error_list.append(f"{label}: {err}")

        if error_list:
            for err in error_list[:3]:
                messages.error(self.request, f"❌ {err}")
        else:
            messages.error(self.request, "❌ Iltimos, formani tekshiring.")

        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update({
            'mode': 'create',
            'courses': Course.objects.filter(is_deleted=False).order_by('title'),
            'teachers': CustomUser.objects.filter(
                role='teacher', is_active=True
            ).order_by('first_name'),
            'schedule_days': [
                ('monday', 'Dushanba', 'schedule_monday'),
                ('tuesday', 'Seshanba', 'schedule_tuesday'),
                ('wednesday', 'Chorshanba', 'schedule_wednesday'),
                ('thursday', 'Payshanba', 'schedule_thursday'),
                ('friday', 'Juma', 'schedule_friday'),
                ('saturday', 'Shanba', 'schedule_saturday'),
                ('sunday', 'Yakshanba', 'schedule_sunday'),
            ],
            'color_options': [
                ('#06b6d4', 'Cyan'),
                ('#6366f1', 'Indigo'),
                ('#8b5cf6', 'Violet'),
                ('#ec4899', 'Pink'),
                ('#f43f5e', 'Rose'),
                ('#f59e0b', 'Amber'),
                ('#10b981', 'Emerald'),
                ('#14b8a6', 'Teal'),
                ('#3b82f6', 'Blue'),
                ('#64748b', 'Slate'),
            ],
        })
        return ctx


class GroupUpdateView(AdminRequiredMixin, AdminContextMixin, AuditLogMixin,
                      UpdateView):
    """
    Guruhni tahrirlash — professional.

    - O'zgarishlar kuzatuvi (changes tracking)
    - Transaction
    - Audit log
    """
    model = StudentGroup
    form_class = GroupForm
    template_name = 'admin_user/courses/group_form.html'
    audit_action = 'update'

    def get_queryset(self):
        return StudentGroup.objects.filter(is_deleted=False)

    def form_valid(self, form):
        try:
            with transaction.atomic():
                # Eski qiymatlar (o'zgarishlarni kuzatish uchun)
                old_data = {
                    'name': self.object.name,
                    'code': self.object.code,
                    'course_id': self.object.course_id,
                    'teacher_id': self.object.teacher_id,
                    'status': self.object.status,
                    'max_students': self.object.max_students,
                    'color': self.object.color,
                    'room': self.object.room,
                    'schedule': self.object.schedule,
                }

                self.object = form.save()

                # Yangi qiymatlar
                new_data = {
                    'name': self.object.name,
                    'code': self.object.code,
                    'course_id': self.object.course_id,
                    'teacher_id': self.object.teacher_id,
                    'status': self.object.status,
                    'max_students': self.object.max_students,
                    'color': self.object.color,
                    'room': self.object.room,
                    'schedule': self.object.schedule,
                }

                # Faqat o'zgarganlar
                changes = {
                    k: {'old': old_data[k], 'new': new_data[k]}
                    for k in old_data
                    if old_data[k] != new_data[k]
                }

                self.log_action(
                    self.object,
                    f"Guruh tahrirlandi: {self.object.name}",
                    changes=changes,
                )

            messages.success(
                self.request,
                f"✅ '{self.object.name}' guruhi yangilandi!"
            )
            return redirect('courses_admin:group_detail', pk=self.object.pk)

        except IntegrityError as e:
            error_msg = f"Dublikat xato: {str(e)}"
            messages.error(self.request, f"❌ {error_msg}")
            return self.form_invalid(form)

        except Exception as e:
            error_msg = f"Xatolik: {str(e)}"
            messages.error(self.request, f"❌ {error_msg}")
            return self.form_invalid(form)

    def form_invalid(self, form):
        error_list = []
        for field, errs in form.errors.items():
            for err in errs:
                if field == '__all__':
                    error_list.append(str(err))
                else:
                    label = form.fields[field].label if field in form.fields else field
                    error_list.append(f"{label}: {err}")

        if error_list:
            for err in error_list[:3]:
                messages.error(self.request, f"❌ {err}")
        else:
            messages.error(self.request, "❌ Iltimos, formani tekshiring.")

        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update({
            'mode': 'edit',
            'group': self.object,
            'courses': Course.objects.filter(is_deleted=False).order_by('title'),
            'teachers': CustomUser.objects.filter(
                role='teacher', is_active=True
            ).order_by('first_name'),
            'schedule_days': [
                ('monday', 'Dushanba', 'schedule_monday'),
                ('tuesday', 'Seshanba', 'schedule_tuesday'),
                ('wednesday', 'Chorshanba', 'schedule_wednesday'),
                ('thursday', 'Payshanba', 'schedule_thursday'),
                ('friday', 'Juma', 'schedule_friday'),
                ('saturday', 'Shanba', 'schedule_saturday'),
                ('sunday', 'Yakshanba', 'schedule_sunday'),
            ],
            'color_options': [
                ('#06b6d4', 'Cyan'),
                ('#6366f1', 'Indigo'),
                ('#8b5cf6', 'Violet'),
                ('#ec4899', 'Pink'),
                ('#f43f5e', 'Rose'),
                ('#f59e0b', 'Amber'),
                ('#10b981', 'Emerald'),
                ('#14b8a6', 'Teal'),
                ('#3b82f6', 'Blue'),
                ('#64748b', 'Slate'),
            ],
        })
        return ctx


class GroupDeleteView(AdminRequiredMixin, AuditLogMixin, View):
    """
    Guruhni o'chirish (soft delete) — professional.

    - POST only
    - Transaction
    - Audit log
    - Talabalar sonini tekshirish
    """

    def post(self, request, pk):
        group = get_object_or_404(StudentGroup, pk=pk, is_deleted=False)

        # Talabalar bor? — tasdiqlash
        students_count = group.students_count
        force = request.POST.get('force') == '1'

        if students_count > 0 and not force:
            return JsonResponse({
                'success': False,
                'error': f"Bu guruhda {students_count} ta talaba bor!",
                'requires_confirm': True,
                'students_count': students_count,
            }, status=400)

        try:
            with transaction.atomic():
                name = group.name
                group.soft_delete(request.user)
                self.log_action(
                    group,
                    f"Guruh o'chirildi: {name} ({students_count} talaba)"
                )

            return JsonResponse({
                'success': True,
                'message': f"'{name}' guruhi o'chirildi",
                'redirect_url': reverse('courses_admin:group_list'),
            })

        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f"O'chirishda xatolik: {str(e)}"
            }, status=400)


class GroupScheduleUpdateView(AdminRequiredMixin, AuditLogMixin, View):
    """
    Jadvalni yangilash — AJAX.

    XUSUSIYATLAR:
    - Schedule JSON validatsiyasi (HH:MM)
    - Transaction — atomik saqlash
    - ⭐ QAYTA REJALASHTIRISH: kelajakdagi homework tasklari yangi jadvalga moslashadi
    - Audit log
    """
    ALLOWED_DAYS = (
        'monday', 'tuesday', 'wednesday', 'thursday',
        'friday', 'saturday', 'sunday',
    )

    def post(self, request, pk):
        group = get_object_or_404(StudentGroup, pk=pk, is_deleted=False)

        # ─── 1. VALIDATSIYA ───
        schedule = {}
        errors = []

        for day in self.ALLOWED_DAYS:
            t = (request.POST.get(f'schedule_{day}') or '').strip()
            if not t:
                continue

            parts = t.split(':')
            if len(parts) != 2:
                errors.append(f"{day}: HH:MM formatida yozing")
                continue

            try:
                h, m = int(parts[0]), int(parts[1])
                if not (0 <= h < 24 and 0 <= m < 60):
                    errors.append(f"{day}: noto'g'ri vaqt")
                    continue
                schedule[day] = f"{h:02d}:{m:02d}"
            except ValueError:
                errors.append(f"{day}: noto'g'ri format")

        if errors:
            return JsonResponse({
                'success': False,
                'error': '; '.join(errors),
            }, status=400)

        # ─── 2. SAQLASH + QO'LLANILADIGAN YUBORISH HOLATINI YANGILASH ───
        old_schedule = group.schedule or {}
        schedule_changed = old_schedule != schedule

        try:
            with transaction.atomic():
                group.schedule = schedule
                group.save(update_fields=['schedule', 'updated_at'])

                # Jadval o'zgarsa, eski avtomatik yuborish tasklarini bekor qilish.
                reschedule_stats = {'cancelled': 0, 'rescheduled': 0, 'errors': 0}
                if schedule_changed:
                    reschedule_stats = self._reschedule_future_homework(group)

                # Audit
                self.log_action(
                    group,
                    f"Jadval yangilandi: {group.name}",
                    changes={
                        'schedule': {'old': old_schedule, 'new': schedule},
                        'rescheduled': reschedule_stats,
                    }
                )

        except Exception as e:
            logger.exception(f"Schedule update xatosi ({pk}): {e}")
            return JsonResponse({
                'success': False,
                'error': f"Xatolik: {str(e)}",
            }, status=400)

        # ─── 3. JAVOB ───
        message = "Jadval yangilandi ✅"
        if schedule_changed and reschedule_stats['rescheduled'] > 0:
            message += (
                f" | {reschedule_stats['rescheduled']} ta vazifa "
                f"qayta rejalashtirildi"
            )
        if reschedule_stats['errors'] > 0:
            message += f" | ⚠️ {reschedule_stats['errors']} ta xato"

        return JsonResponse({
            'success': True,
            'message': message,
            'schedule': schedule,
            'reschedule': reschedule_stats if schedule_changed else None,
        })

    # ═══════════════════════════════════════════════════════════
    # ⭐ QAYTA REJALASHTIRISH LOGIKASI
    # ═══════════════════════════════════════════════════════════

    def _reschedule_future_homework(self, group):
        """
        Eski avtomatik tasklarni bekor qilib, vazifalarni qo'lda yuborishga tayyorlash.

        FAQAT:
        - bugun va kelajakdagi darslar
        - hali yuborilmagan (status='scheduled' yoki 'pending')

        QAYTA REJALASHTIRILMAYDI:
        - yuborilgan (sent/partial)
        - bekor qilingan (cancelled)
        """
        from apps.service.homework_scheduler import HomeworkScheduler
        from apps.courses.models import GroupLesson

        today = timezone.now().date()
        stats = {'cancelled': 0, 'rescheduled': 0, 'errors': 0}

        # Bugun va kelajakdagi yuborilmagan vazifalar
        pending_tasks = (
            GroupLesson.objects
            .filter(
                group=group,
                lesson_date__gte=today,                  # ⭐ kelajak
                homework_status__in=['scheduled', 'pending'],  # ⭐ hali yuborilmagan
                is_deleted=False,
            )
            .select_related('lesson', 'lesson__homework')
        )

        for gl in pending_tasks:
            try:
                # Eski taskni bekor qilish
                if gl.scheduled_task_id:
                    cancelled = HomeworkScheduler.cancel_scheduled(gl)
                    if cancelled:
                        stats['cancelled'] += 1

                gl.scheduled_task_id = None
                gl.homework_status = 'pending'
                gl.save(update_fields=[
                    'scheduled_task_id', 'homework_status', 'updated_at'
                ])

            except Exception as e:
                logger.exception(f"Reschedule xatosi (GL#{gl.pk}): {e}")
                stats['errors'] += 1

        logger.info(
            f"🖐 Manual delivery ready [{group.name}]: "
            f"cancelled={stats['cancelled']} "
            f"rescheduled={stats['rescheduled']} "
            f"errors={stats['errors']}"
        )

        return stats



class GroupGenerateLessonsView(AdminRequiredMixin, AuditLogMixin, View):
    """
    Jadvalga qarab GroupLesson larni avtomatik taqsimlash.

    - Transaction
    - Race condition himoyasi
    - Statistika
    - Audit log
    """

    def post(self, request, pk):
        group = get_object_or_404(StudentGroup, pk=pk, is_deleted=False)
        course = group.course

        if not course:
            return JsonResponse(
                {'success': False, 'error': "Guruhga kurs biriktirilmagan"},
                status=400,
            )

        schedule = group.schedule or {}
        if not schedule:
            return JsonResponse(
                {'success': False, 'error': "Jadval bo'sh. Avval jadval belgilang"},
                status=400,
            )

        day_map = {
            'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
            'friday': 4, 'saturday': 5, 'sunday': 6,
        }

        sorted_days = sorted(schedule.keys(), key=lambda d: day_map[d])
        start = group.lessons_start_date or timezone.now().date()

        try:
            with transaction.atomic():
                # Mavjud lesson'lar
                existing_ids = set(
                    GroupLesson.objects.filter(group_id=group.pk)
                    .values_list('lesson_id', flat=True)
                )

                # Kursdagi barcha live darslar
                lessons = (course.lessons
                           .filter(is_deleted=False)
                           .order_by('lesson_number'))

                if not lessons.exists():
                    return JsonResponse({
                        'success': False,
                        'error': "Kursda darslar yo'q",
                    }, status=400)

                created = 0
                skipped = 0

                for idx, lesson in enumerate(lessons):
                    if lesson.id in existing_ids:
                        skipped += 1
                        continue

                    day_name = sorted_days[idx % len(sorted_days)]
                    weeks_ahead = idx // len(sorted_days)
                    target = start + timedelta(weeks=weeks_ahead)
                    delta = (day_map[day_name] - target.weekday()) % 7
                    lesson_date = target + timedelta(days=delta)

                    # ⭐ group=group emas, group_id=group.pk:
                    GroupLesson.objects.create(
                        group_id=group.pk,  # ⭐ MUHIM
                        lesson=lesson,
                        lesson_date=lesson_date,
                        order_in_group=lesson.lesson_number,
                    )

                    created += 1

                # Audit
                self.log_action(
                    group,
                    f"Darslar taqsimlandi: {group.name} — {created} yangi, {skipped} mavjud"
                )

            return JsonResponse({
                'success': True,
                'created': created,
                'skipped': skipped,
                'total': created + skipped,
                'message': (
                    f"✅ {created} ta yangi dars taqsimlandi"
                    + (f" ({skipped} ta allaqachon bor edi)" if skipped else "")
                ),
            })

        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f"Xatolik: {str(e)}"
            }, status=400)


class GroupAddStudentView(AdminRequiredMixin, AuditLogMixin, View):
    """
    Guruhga talaba qo'shish — professional.

    - Capacity tekshirish
    - Transaction
    - Audit log
    - Duplikat tekshirish
    """

    def post(self, request, pk):
        group = get_object_or_404(StudentGroup, pk=pk, is_deleted=False)

        if not group.has_capacity:
            return JsonResponse({
                'success': False,
                'error': f"Guruh to'lgan! ({group.students_count}/{group.max_students})",
            }, status=400)

        sid = request.POST.get('student_id')
        if not sid:
            return JsonResponse({
                'success': False,
                'error': "Talaba tanlanmagan",
            }, status=400)

        student = get_object_or_404(StudentProfile, id=sid)

        # Duplikat tekshirish
        if group.students.filter(id=student.id).exists():
            return JsonResponse({
                'success': False,
                'error': f"{student.user.get_full_name()} allaqachon bu guruhda",
            }, status=400)

        try:
            with transaction.atomic():
                # 1. Talabani guruhga qo'shish (M2M)
                group.students.add(student)

                # 2. GroupMember yozuvini yaratish
                # ⭐ group_id=group.pk ishlatamiz (isinstance tekshiruvini chetlab o'tadi)
                GroupMember.objects.get_or_create(
                    group_id=group.pk,  # ✅ TO'G'RI
                    student=student,
                    defaults={'is_active': True},
                )

                self.log_action(
                    group,
                    f"Talaba qo'shildi: {student.user.get_full_name()} → {group.name}",
                )

            return JsonResponse({
                'success': True,
                'message': f"✅ {student.user.get_full_name()} qo'shildi",
                'students_count': group.students_count,
                'max_students': group.max_students,
            })

        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f"Qo'shishda xatolik: {str(e)}"
            }, status=400)


class GroupRemoveStudentView(AdminRequiredMixin, AuditLogMixin, View):
    """
    Guruhdan talabani chiqarish — professional.

    - Transaction
    - Audit log
    - GroupMember yangilash
    """

    def post(self, request, pk, student_id):
        group = get_object_or_404(StudentGroup, pk=pk, is_deleted=False)
        student = get_object_or_404(StudentProfile, id=student_id)

        if not group.students.filter(id=student.id).exists():
            return JsonResponse({
                'success': False,
                'error': "Talaba bu guruhda emas",
            }, status=400)

        try:
            with transaction.atomic():
                student_name = student.user.get_full_name()

                # 1. M2M dan olib tashlash
                group.students.remove(student)

                # 2. GroupMember'ni nofaol qilish
                # ⭐ group_id=group.pk ishlatamiz
                GroupMember.objects.filter(
                    group_id=group.pk,              # ✅ TO'G'RI
                    student_id=student.pk,          # ✅ student_id ham
                ).update(
                    is_active=False,
                    left_at=timezone.now().date(),
                )

                self.log_action(
                    group,
                    f"Talaba chiqarildi: {student_name} ← {group.name}",
                )

            return JsonResponse({
                'success': True,
                'message': f"✅ {student_name} chiqarildi",
                'students_count': group.students_count,
                'max_students': group.max_students,
            })

        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f"Chiqarishda xatolik: {str(e)}"
            }, status=400)
# ═══════════════════════════════════════════════════════════════
# 7. BULK ACTIONS
# ═══════════════════════════════════════════════════════════════

class CoursesBulkView(AdminRequiredMixin, AuditLogMixin, View):
    """Kurslar uchun ommaviy amallar — AJAX only."""

    ALLOWED = {'publish', 'unpublish', 'feature', 'unfeature', 'archive', 'delete'}

    def post(self, request):
        action = (request.POST.get('action') or '').strip()
        ids = request.POST.getlist('ids[]')

        if action not in self.ALLOWED:
            return JsonResponse({'success': False, 'error': "Noto'g'ri amal"}, status=400)
        if not ids:
            return JsonResponse({'success': False, 'error': "Hech narsa tanlanmagan"},
                                status=400)

        qs = Course.objects.filter(id__in=ids, is_deleted=False)
        count = 0
        try:
            with transaction.atomic():
                if action == 'publish':
                    count = qs.update(status='published', is_active=True)
                    msg = f"{count} ta kurs e'lon qilindi"
                elif action == 'unpublish':
                    count = qs.update(status='draft')
                    msg = f"{count} ta kurs e'londan olindi"
                elif action == 'feature':
                    count = qs.update(is_featured=True)
                    msg = f"{count} ta kurs tanlandi"
                elif action == 'unfeature':
                    count = qs.update(is_featured=False)
                    msg = f"{count} ta kurs tanlovdan olindi"
                elif action == 'archive':
                    count = qs.update(status='archived')
                    msg = f"{count} ta kurs arxivlandi"
                elif action == 'delete':
                    count = qs.count()
                    for c in qs:
                        c.soft_delete(request.user)

                try:
                    AuditLog.objects.create(
                        user=request.user, action='update',
                        content_type=ContentType.objects.get_for_model(Course),
                        description=f"Bulk {action}: {count} ta kurs",
                    )
                except Exception:
                    pass
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

        return JsonResponse({'success': True, 'message': msg, 'count': count})
class CourseTogglePublishView(AdminRequiredMixin, AuditLogMixin, View):
    """Kursni e'lon qilish / e'londan olish — AJAX only."""

    def post(self, request, pk):
        course = get_object_or_404(Course, pk=pk, is_deleted=False)

        try:
            with transaction.atomic():
                is_pub = course.status == 'published'
                new_status = 'draft' if is_pub else 'published'

                course.status = new_status
                if new_status == 'published':
                    course.is_active = True

                course.save(update_fields=['status', 'is_active', 'updated_at'])

                self.log_action(
                    course,
                    f"Kurs {'e\'londan olindi' if is_pub else 'e\'lon qilindi'}: {course.title}"
                )

                return JsonResponse({
                    'success': True,
                    'status': new_status,
                    'status_display': course.get_status_display(),
                    'message': "E'londan olindi" if is_pub else "E'lon qilindi ✅",
                })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)


# class QuizBulkImportView(AdminRequiredMixin, View):
#     """AJAX bulk import."""
#     def post(self, request, quiz_pk):
#         import json
#         quiz = get_object_or_404(Quiz, pk=quiz_pk)
#         fmt = request.POST.get('format')
#         payload = request.POST.get('payload')
#
#         try:
#             if fmt == 'json':
#                 data = json.loads(payload)
#             # ... boshqa formatlar
#         except Exception as e:
#             return JsonResponse({'ok': False, 'error': str(e)}, status=400)
#
#         created = 0
#         order = quiz.questions.count() + 1
#         for item in data:
#             q = Question.objects.create(
#                 quiz=quiz, text=item['text'],
#                 question_type=item.get('question_type', 'single').lower(),
#                 points=item.get('points', 1),
#                 order=order,
#                 explanation=item.get('explanation', ''),
#             )
#             for c in item.get('choices', []):
#                 AnswerOption.objects.create(
#                     question=q, text=c['text'],
#                     is_correct=c.get('is_correct', False),
#                 )
#             order += 1
#             created += 1
#
#         return JsonResponse({'ok': True, 'created': created})


# ═══════════════════════════════════════════════════════════════
# QUIZ BULK IMPORT — AI savollarni ommaviy qo'shish
# ═══════════════════════════════════════════════════════════════

import json as _json
import csv as _csv
from io import StringIO as _StringIO


class QuizBulkImportView(AdminRequiredMixin, AuditLogMixin, View):
    """
    Quiz'ga savollarni ommaviy qo'shish.

    POST parametrlari:
        format: 'json' | 'csv' | 'txt'
        payload: matn ko'rinishidagi ma'lumot

    Qaytaradi:
        {ok: true, created: N, errors: [...]} yoki {ok: false, error: "..."}
    """

    def post(self, request, quiz_pk):
        quiz = get_object_or_404(Quiz, pk=quiz_pk)

        fmt = (request.POST.get('format') or 'json').strip().lower()
        payload = request.POST.get('payload') or ''

        if not payload.strip():
            return JsonResponse({
                'ok': False,
                'error': "Ma'lumot bo'sh",
            }, status=400)

        # ─── 1. Format bo'yicha parse qilish ───
        try:
            if fmt == 'json':
                items, parse_errors = self._parse_json(payload)
            elif fmt == 'csv':
                items, parse_errors = self._parse_csv(payload)
            elif fmt == 'txt':
                items, parse_errors = self._parse_txt(payload)
            else:
                return JsonResponse({
                    'ok': False,
                    'error': f"Noto'g'ri format: {fmt}",
                }, status=400)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return JsonResponse({
                'ok': False,
                'error': f"Parse xatosi: {e}",
            }, status=400)

        if not items:
            return JsonResponse({
                'ok': False,
                'error': "Hech qanday savol topilmadi",
                'errors': parse_errors,
            }, status=400)

        # ─── 2. Bazaga saqlash ───
        try:
            with transaction.atomic():
                last = quiz.questions.order_by('-order').first()
                order = (last.order + 1) if last else 1

                created = 0
                save_errors = []

                for idx, item in enumerate(items):
                    try:
                        # Validate
                        text = (item.get('text') or '').strip()
                        if not text:
                            save_errors.append({
                                'index': idx + 1,
                                'error': "Savol matni bo'sh",
                            })
                            continue

                        # Normalize type
                        q_type = (item.get('question_type') or 'single').lower()
                        q_type_map = {
                            'single': 'single',
                            'multiple': 'multiple',
                            'true_false': 'true_false',
                            'truefalse': 'true_false',
                            'true-false': 'true_false',
                            'text': 'text',
                        }
                        q_type = q_type_map.get(q_type, 'single')

                        # Points
                        try:
                            points = int(item.get('points', 1))
                        except (ValueError, TypeError):
                            points = 1
                        points = max(1, min(100, points))

                        # Question yaratish
                        q = Question.objects.create(
                            quiz=quiz,
                            text=text,
                            question_type=q_type,
                            points=points,
                            order=order,
                            explanation=(item.get('explanation') or '').strip()[:5000],
                        )

                        # Choices
                        choices = item.get('choices') or []
                        # TEXT turi uchun faqat 1 ta "to'g'ri javob"
                        if q_type == 'text' and choices:
                            first = choices[0]
                            AnswerOption.objects.create(
                                question=q,
                                text=str(first.get('text', ''))[:500],
                                is_correct=True,
                                order=1,
                            )
                        else:
                            for c_idx, c in enumerate(choices, start=1):
                                c_text = str(c.get('text', '')).strip()
                                if not c_text:
                                    continue
                                AnswerOption.objects.create(
                                    question=q,
                                    text=c_text[:500],
                                    is_correct=bool(c.get('is_correct', False)),
                                    order=c_idx,
                                )

                        order += 1
                        created += 1

                    except Exception as e:
                        save_errors.append({
                            'index': idx + 1,
                            'error': str(e),
                        })

                # Log
                self.log_action(
                    quiz,
                    f"Bulk import: {created} ta savol qo'shildi ({fmt})",
                )

                return JsonResponse({
                    'ok': True,
                    'created': created,
                    'errors': save_errors,
                    'parse_errors': parse_errors,
                    'message': f"✅ {created} ta savol import qilindi",
                })

        except Exception as e:
            import traceback
            traceback.print_exc()
            return JsonResponse({
                'ok': False,
                'error': f"Saqlash xatosi: {e}",
            }, status=400)

    # ═══════════════════════════════════════════════════════════
    # FORMAT PARSERLAR
    # ═══════════════════════════════════════════════════════════

    def _parse_json(self, payload):
        """JSON format.

        [
          {
            "text": "2 + 2 = ?",
            "question_type": "SINGLE",
            "points": 1,
            "explanation": "...",
            "choices": [
              {"text": "4", "is_correct": true},
              {"text": "5", "is_correct": false}
            ]
          }
        ]
        """
        errors = []
        try:
            data = _json.loads(payload)
        except _json.JSONDecodeError as e:
            return [], [{'index': 0, 'error': f"JSON xato: {e.msg} (qator {e.lineno})"}]

        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            return [], [{'index': 0, 'error': "JSON array bo'lishi kerak"}]

        items = []
        for i, item in enumerate(data):
            if not isinstance(item, dict):
                errors.append({'index': i + 1, 'error': "Obyekt emas"})
                continue
            if not item.get('text'):
                errors.append({'index': i + 1, 'error': "text maydoni yo'q"})
                continue
            items.append(item)

        return items, errors

    def _parse_csv(self, payload):
        """CSV format.

        text,choice1,choice2,choice3,correct,points
        "2 + 2 = ?","4","5","3",1,1
        """
        errors = []
        items = []

        try:
            reader = _csv.reader(_StringIO(payload))
            rows = list(reader)
        except Exception as e:
            return [], [{'index': 0, 'error': f"CSV xato: {e}"}]

        if len(rows) < 2:
            return [], [{'index': 0, 'error': "CSV bo'sh yoki sarlavha yo'q"}]

        headers = [h.strip().lower() for h in rows[0]]

        # Header tekshirish
        if 'text' not in headers:
            return [], [{'index': 0, 'error': "text ustuni topilmadi"}]

        text_idx = headers.index('text')

        # Choice ustunlarini topish
        choice_cols = []
        for i, h in enumerate(headers):
            if h.startswith('choice'):
                choice_cols.append(i)

        # correct va points
        try:
            correct_idx = headers.index('correct')
        except ValueError:
            correct_idx = None

        try:
            points_idx = headers.index('points')
        except ValueError:
            points_idx = None

        for i, row in enumerate(rows[1:], start=1):
            if not row or all(not c.strip() for c in row):
                continue

            if text_idx >= len(row):
                errors.append({'index': i, 'error': "text ustuni bo'sh"})
                continue

            text = row[text_idx].strip()
            if not text:
                errors.append({'index': i, 'error': "text bo'sh"})
                continue

            # Points
            points = 1
            if points_idx is not None and points_idx < len(row):
                try:
                    points = int(float(row[points_idx]))
                except (ValueError, TypeError):
                    points = 1

            # Correct index (1-based)
            correct = 1
            if correct_idx is not None and correct_idx < len(row):
                try:
                    correct = int(float(row[correct_idx]))
                except (ValueError, TypeError):
                    correct = 1

            # Choices
            choices = []
            for j, c_idx in enumerate(choice_cols, start=1):
                if c_idx < len(row):
                    c_text = row[c_idx].strip()
                    if c_text:
                        choices.append({
                            'text': c_text,
                            'is_correct': (j == correct),
                        })

            if len(choices) < 2:
                errors.append({
                    'index': i,
                    'error': f"Kamida 2 variant kerak (topildi: {len(choices)})",
                })
                continue

            items.append({
                'text': text,
                'question_type': 'single',
                'points': points,
                'choices': choices,
            })

        return items, errors

    def _parse_txt(self, payload):
        """Matn format.

        2 + 2 = ?
        + 4
        - 5
        - 3
        ---
        Poytaxt qaysi shahar?
        + Toshkent
        - Samarqand
        """
        errors = []
        items = []

        # Savollarni "---" bilan ajratish
        blocks = payload.split('---')

        for i, block in enumerate(blocks, start=1):
            lines = [l.strip() for l in block.split('\n') if l.strip()]
            if not lines:
                continue

            item = {
                'text': '',
                'question_type': 'single',
                'points': 1,
                'choices': [],
            }

            for line in lines:
                if line.startswith('+'):
                    # To'g'ri variant
                    c_text = line[1:].strip()
                    if c_text:
                        item['choices'].append({
                            'text': c_text,
                            'is_correct': True,
                        })
                elif line.startswith('-'):
                    # Noto'g'ri variant
                    c_text = line[1:].strip()
                    if c_text:
                        item['choices'].append({
                            'text': c_text,
                            'is_correct': False,
                        })
                elif not item['text']:
                    # Savol matni (birinchi oddiy qator)
                    item['text'] = line.replace('Q:', '').strip()

            # Validatsiya
            if not item['text']:
                errors.append({'index': i, 'error': "Savol matni yo'q"})
                continue

            if len(item['choices']) < 2:
                errors.append({
                    'index': i,
                    'error': f"Kamida 2 variant kerak (topildi: {len(item['choices'])})",
                })
                continue

            # Multiple javob bo'lsa — question_type ni o'zgartirish
            correct_count = sum(1 for c in item['choices'] if c['is_correct'])
            if correct_count > 1:
                item['question_type'] = 'multiple'

            items.append(item)

        return items, errors


# ═══════════════════════════════════════════════════════════════
# QUIZ DETAIL VIEW — TO'LIQ
# ═══════════════════════════════════════════════════════════════

class QuizDetailView(AdminRequiredMixin, AdminContextMixin, DetailView):
    """Test tafsilotlari — to'liq statistika bilan."""
    model = Quiz
    template_name = 'admin_user/courses/quiz_detail.html'
    context_object_name = 'quiz'

    def get_queryset(self):
        return (Quiz.objects
                .filter(is_deleted=False)
                .select_related('course', 'lesson', 'category', 'created_by'))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        quiz = self.object

        # ═══ SAVOLLAR ═══
        questions = list(
            quiz.questions
            .prefetch_related('options')
            .order_by('order', 'id')
        )

        # ═══ STATISTIKA ═══
        total_points = sum(q.points for q in questions)
        total_choices = sum(q.options.count() for q in questions)

        # Difficulty breakdown
        type_breakdown = {}
        for q in questions:
            t = q.question_type or 'single'
            type_breakdown[t] = type_breakdown.get(t, 0) + 1

        # Attempts
        try:
            attempts_count = quiz.attempts.count()
            passes_count = quiz.attempts.filter(is_passed=True).count()
            success_rate = round(
                (passes_count / attempts_count * 100) if attempts_count else 0, 1
            )
            avg_score = quiz.attempts.aggregate(
                a=Avg('score')
            )['a'] or 0
        except Exception:
            attempts_count = 0
            passes_count = 0
            success_rate = 0
            avg_score = 0

        # Top students
        try:
            top_attempts = (quiz.attempts
                .filter(is_passed=True)
                .select_related('student__user')
                .order_by('-score', 'time_spent_seconds')[:5])
        except Exception:
            top_attempts = []

        ctx.update({
            'questions': questions,
            'stats': {
                'total_questions': len(questions),
                'total_points': total_points,
                'total_choices': total_choices,
                'attempts_count': attempts_count,
                'passes_count': passes_count,
                'success_rate': success_rate,
                'avg_score': round(float(avg_score), 1),
                'type_breakdown': type_breakdown,
            },
            'top_attempts': top_attempts,
            'difficulty_choices': Quiz._meta.get_field('difficulty').choices,
        })
        return ctx


class QuizUpdateView(AdminRequiredMixin, AuditLogMixin, View):
    """Tez tahrirlash — AJAX yoki redirect."""
    def get(self, request, pk):
        quiz = get_object_or_404(Quiz, pk=pk, is_deleted=False)
        if quiz.lesson:
            return redirect('courses_admin:quiz_form', lesson_pk=quiz.lesson.pk)
        messages.error(request, "Dars topilmadi")
        return redirect('courses_admin:quiz_detail', pk=pk)


class QuizDeleteView(AdminRequiredMixin, AuditLogMixin, View):
    """Testni soft-delete qilish."""
    def post(self, request, pk):
        quiz = get_object_or_404(Quiz, pk=pk, is_deleted=False)
        try:
            with transaction.atomic():
                title = quiz.title
                if hasattr(quiz, 'soft_delete'):
                    quiz.soft_delete(request.user)
                else:
                    quiz.is_deleted = True
                    quiz.save(update_fields=['is_deleted'])

                self.log_action(quiz, f"Test o'chirildi: {title}")

            return JsonResponse({
                'success': True,
                'message': f"'{title}' testi o'chirildi",
                'redirect_url': reverse('courses_admin:list'),
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)


class QuizToggleActiveView(AdminRequiredMixin, AuditLogMixin, View):
    """Testni aktivlashtirish/o'chirish."""
    def post(self, request, pk):
        quiz = get_object_or_404(Quiz, pk=pk, is_deleted=False)
        try:
            quiz.is_active = not quiz.is_active
            quiz.save(update_fields=['is_active'])
            self.log_action(
                quiz,
                f"Test {'aktivlashtirildi' if quiz.is_active else 'o\'chirildi'}: {quiz.title}"
            )
            return JsonResponse({
                'success': True,
                'is_active': quiz.is_active,
                'message': "Aktivlashtirildi ✅" if quiz.is_active else "O'chirildi",
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)


class QuizDuplicateView(AdminRequiredMixin, AuditLogMixin, View):
    """Testni nusxalash."""
    def post(self, request, pk):
        quiz = get_object_or_404(Quiz, pk=pk, is_deleted=False)
        try:
            with transaction.atomic():
                new_quiz = Quiz.objects.create(
                    title=f"{quiz.title} (nusxa)",
                    description=quiz.description,
                    instructions=quiz.instructions,
                    difficulty=quiz.difficulty,
                    duration_minutes=quiz.duration_minutes,
                    passing_score=quiz.passing_score,
                    max_attempts=quiz.max_attempts,
                    shuffle_questions=quiz.shuffle_questions,
                    shuffle_options=quiz.shuffle_options,
                    show_correct_answers=quiz.show_correct_answers,
                    show_results_immediately=quiz.show_results_immediately,
                    allow_back=quiz.allow_back,
                    allow_skip=quiz.allow_skip,
                    coins_reward=quiz.coins_reward,
                    xp_reward=quiz.xp_reward,
                    course=quiz.course,
                    category=quiz.category,
                    is_active=False,
                    created_by=request.user,
                )

                # Savollarni nusxalash
                for q in quiz.questions.prefetch_related('options').order_by('order'):
                    new_q = Question.objects.create(
                        quiz=new_quiz,
                        question_type=q.question_type,
                        text=q.text,
                        points=q.points,
                        order=q.order,
                        difficulty=q.difficulty,
                        explanation=q.explanation,
                        hint=q.hint,
                        correct_text=q.correct_text,
                        correct_number=q.correct_number,
                    )
                    for opt in q.options.order_by('order'):
                        AnswerOption.objects.create(
                            question=new_q,
                            text=opt.text,
                            is_correct=opt.is_correct,
                            order=opt.order,
                        )

                self.log_action(new_quiz, f"Test nusxalandi: {new_quiz.title}")
                return JsonResponse({
                    'success': True,
                    'new_id': new_quiz.pk,
                    'redirect_url': reverse('courses_admin:quiz_detail', kwargs={'pk': new_quiz.pk}),
                    'message': "✅ Nusxa yaratildi",
                })
        except Exception as e:
            import traceback
            traceback.print_exc()
            return JsonResponse({'success': False, 'error': str(e)}, status=400)


class QuizExportView(AdminRequiredMixin, View):
    """Testni JSON formatda eksport qilish."""
    def get(self, request, pk):
        import json
        quiz = get_object_or_404(Quiz, pk=pk, is_deleted=False)

        data = {
            'title': quiz.title,
            'description': quiz.description or '',
            'difficulty': quiz.difficulty,
            'duration_minutes': quiz.duration_minutes,
            'passing_score': quiz.passing_score,
            'max_attempts': quiz.max_attempts,
            'questions': [],
        }

        for q in quiz.questions.prefetch_related('options').order_by('order'):
            item = {
                'text': q.text,
                'question_type': q.question_type.upper() if q.question_type else 'SINGLE',
                'points': q.points,
                'explanation': q.explanation or '',
                'choices': [
                    {'text': c.text, 'is_correct': c.is_correct}
                    for c in q.options.order_by('order')
                ],
            }
            data['questions'].append(item)

        response = HttpResponse(
            json.dumps(data, ensure_ascii=False, indent=2),
            content_type='application/json; charset=utf-8'
        )
        safe_title = re.sub(r'[^\w\s-]', '', quiz.title)[:50].strip() or 'quiz'
        response['Content-Disposition'] = f'attachment; filename="{safe_title}.json"'
        return response
# ═══════════════════════════════════════════════════════════════
# HOMEWORK LIST VIEW — Barcha uyga vazifalar ro'yxati
# ═══════════════════════════════════════════════════════════════

class HomeworkListView(AdminRequiredMixin, AdminContextMixin, ListView):
    """
    Barcha uyga vazifalar ro'yxati.

    Xususiyatlar:
    - Qidiruv (sarlavha, dars, kurs)
    - Filtrlar (kurs, holat, turi)
    - Statistika
    - Pagination
    """
    model = Homework
    template_name = 'admin_user/courses/homework_list.html'
    context_object_name = 'homeworks'
    paginate_by = 20

    def get_paginate_by(self, queryset):
        try:
            n = int(self.request.GET.get('per_page', 20))
            return n if n in (20, 40, 80, 100) else 20
        except (TypeError, ValueError):
            return 20

    def get_queryset(self):
        qs = (Homework.objects
              .filter(is_deleted=False, lesson__is_deleted=False)
              .select_related('lesson', 'lesson__course', 'lesson__month', 'created_by')
              .order_by('-created_at'))

        # ═══ Qidiruv ═══
        search = self.request.GET.get('q', '').strip()
        if search:
            qs = qs.filter(
                Q(title__icontains=search) |
                Q(short_description__icontains=search) |
                Q(description__icontains=search) |
                Q(lesson__title__icontains=search) |
                Q(lesson__course__title__icontains=search)
            )

        # ═══ Filtrlar ═══
        course_id = self.request.GET.get('course', '').strip()
        if course_id:
            qs = qs.filter(lesson__course_id=course_id)

        status = self.request.GET.get('status', '').strip()
        if status == 'approved':
            qs = qs.filter(is_approved=True)
        elif status == 'pending':
            qs = qs.filter(is_approved=False)
        elif status == 'sent':
            qs = qs.filter(is_sent=True)
        elif status == 'not_sent':
            qs = qs.filter(is_sent=False)

        hw_type = self.request.GET.get('type', '').strip()
        if hw_type:
            qs = qs.filter(homework_type=hw_type)

        # ═══ Sort ═══
        sort = self.request.GET.get('sort', '-created_at')
        allowed = {'-created_at', 'created_at', 'title', '-title', 'deadline_days', '-deadline_days'}
        if sort in allowed:
            qs = qs.order_by(sort)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        all_hw = Homework.objects.filter(is_deleted=False, lesson__is_deleted=False)

        stats = {
            'total': all_hw.count(),
            'approved': all_hw.filter(is_approved=True).count(),
            'pending': all_hw.filter(is_approved=False).count(),
            'sent': all_hw.filter(is_sent=True).count(),
            'not_sent': all_hw.filter(is_sent=False).count(),
        }

        ctx.update({
            'stats': stats,
            'courses': Course.objects.filter(is_deleted=False).order_by('title'),
            'type_choices': Homework._meta.get_field('homework_type').choices,
            'search': self.request.GET.get('q', ''),
            'course_filter': self.request.GET.get('course', ''),
            'status_filter': self.request.GET.get('status', ''),
            'type_filter': self.request.GET.get('type', ''),
            'sort': self.request.GET.get('sort', '-created_at'),
            'per_page': self.get_paginate_by(None),
            'now': timezone.now(),
        })
        return ctx



# apps/courses/admin_views.py
# ... mavjud importlar ...

from django.utils import timezone  # allaqachon bor


# ═══════════════════════════════════════════════════════════════
# SCHEDULED HOMEWORK LIST — Rejalashtirilgan vazifalar
# ═══════════════════════════════════════════════════════════════

class ScheduledHomeworkListView(AdminRequiredMixin, AdminContextMixin, ListView):
    """
    Kelajakda yuboriladigan uyga vazifalar ro'yxati.

    Admin bu yerda ko'radi:
    - Qaysi guruhga, qaysi darsga
    - Qachon yuboriladi (ETA)
    - Nechta talaba oladi
    - Task holati
    """
    model = GroupLesson
    template_name = 'admin_user/courses/scheduled_list.html'
    context_object_name = 'items'
    paginate_by = 30

    def get_queryset(self):
        qs = (
            GroupLesson.objects
            .filter(
                homework_status__in=[
                    'pending', 'scheduled', 'failed', 'partial'
                ],
                is_deleted=False,
                group__is_deleted=False,
                lesson__homework__isnull=False,
            )
            .select_related(
                'group', 'group__course',
                'lesson', 'lesson__course', 'lesson__homework',
            )
            .order_by('lesson_date', 'order_in_group')
        )

        # Filtr: guruh
        group_id = self.request.GET.get('group', '').strip()
        if group_id:
            qs = qs.filter(group_id=group_id)

        # Filtr: kurs
        course_id = self.request.GET.get('course', '').strip()
        if course_id:
            qs = qs.filter(group__course_id=course_id)

        # Filtr: sana oralig'i
        date_from = self.request.GET.get('from', '').strip()
        if date_from:
            qs = qs.filter(lesson_date__gte=date_from)

        date_to = self.request.GET.get('to', '').strip()
        if date_to:
            qs = qs.filter(lesson_date__lte=date_to)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        # Statistika
        base_qs = GroupLesson.objects.filter(
            homework_status__in=[
                'pending', 'scheduled', 'failed', 'partial'
            ],
            is_deleted=False,
            group__is_deleted=False,
            lesson__homework__isnull=False,
        )

        for gl in ctx['items']:
            gl.students_count = gl.group.students_count

        ctx.update({
            'stats': {
                'total': base_qs.count(),
                'today': base_qs.filter(
                    lesson_date=timezone.now().date()
                ).count(),
                'tomorrow': base_qs.filter(
                    lesson_date=timezone.now().date() + timedelta(days=1)
                ).count(),
                'this_week': base_qs.filter(
                    lesson_date__gte=timezone.now().date(),
                    lesson_date__lte=timezone.now().date() + timedelta(days=7)
                ).count(),
            },
            'groups': StudentGroup.objects.filter(
                is_deleted=False
            ).order_by('name'),
            'courses': Course.objects.filter(
                is_deleted=False
            ).order_by('title'),
            'group_filter': self.request.GET.get('group', ''),
            'course_filter': self.request.GET.get('course', ''),
            'date_from': self.request.GET.get('from', ''),
            'date_to': self.request.GET.get('to', ''),
            'now': timezone.now(),
        })
        return ctx