# _________________________________________________
"""
apps/courses/models.py
================================================
DIGION LMS — Kurslar tizimi uchun to‘liq modellar.

XUSUSIYATLAR:
- Ko‘p tilli kurslar
- 9 oylik curriculum (oy → hafta → dars)
- Uyga vazifalar va topshiriqlar
- Testlar, savollar, javoblar
- Guruhlar va talabalar
- Progress tracking
- Sertifikatlar
- Reyting va yutuqlar
- Fayl boshqaruvi
- Video darslar
- Live darslar (Zoom/Google Meet)
- Chat va muloqot
- Analytics va statistika
- Audit log
- Cache
- Soft delete
"""


import os
import uuid
from datetime import timedelta, date
from decimal import Decimal
from typing import Optional, List, Dict, Any

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import (
    MinValueValidator, MaxValueValidator,
    FileExtensionValidator, RegexValidator,
)
from django.db import models, transaction
from django.db.models import (
    Count, Sum, Avg, Max, Min, Q, F,
    Case, When, Value, IntegerField,
    DecimalField, FloatField,
)
from django.db.models.functions import Coalesce, TruncDate, TruncMonth
from django.db.models.signals import post_save, pre_save, post_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _


# ═══════════════════════════════════════════════════════════════
# YORDAMCHI FUNKSIYALAR VA VALIDATORLAR
# ═══════════════════════════════════════════════════════════════

def validate_file_size(value, max_mb: int = 50):
    """Fayl hajmini tekshirish."""
    limit = max_mb * 1024 * 1024
    if value.size > limit:
        raise ValidationError(f"Fayl hajmi {max_mb} MB dan oshmasligi kerak.")


def validate_video_size(value):
    """Video hajmini tekshirish (200MB)."""
    validate_file_size(value, max_mb=200)


def validate_image_size(value):
    """Rasm hajmini tekshirish (5MB)."""
    validate_file_size(value, max_mb=5)



def course_cover_path(instance, filename: str) -> str:
    """Kurs muqovasi uchun yo‘l."""
    ext = filename.split('.')[-1]
    return f"courses/covers/{uuid.uuid4().hex}.{ext}"


def lesson_video_path(instance, filename: str) -> str:
    """Dars videosi uchun yo‘l."""
    ext = filename.split('.')[-1]
    return f"lessons/videos/{timezone.now().strftime('%Y/%m')}/{uuid.uuid4().hex}.{ext}"


def lesson_file_path(instance, filename: str) -> str:
    """Dars materiali uchun yo‘l."""
    ext = filename.split('.')[-1]
    return f"lessons/files/{timezone.now().strftime('%Y/%m')}/{uuid.uuid4().hex}.{ext}"


def homework_file_path(instance, filename: str) -> str:
    """Uyga vazifa fayli uchun yo‘l."""
    ext = filename.split('.')[-1]
    return f"homework/{timezone.now().strftime('%Y/%m')}/{uuid.uuid4().hex}.{ext}"


def submission_file_path(instance, filename: str) -> str:
    """Talaba topshirig‘i uchun yo‘l."""
    ext = filename.split('.')[-1]
    return f"submissions/{timezone.now().strftime('%Y/%m')}/{uuid.uuid4().hex}.{ext}"


def certificate_path(instance, filename: str) -> str:
    """Sertifikat uchun yo‘l."""
    ext = filename.split('.')[-1]
    return f"certificates/{instance.student.id}/{uuid.uuid4().hex}.{ext}"

# ═══════════════════════════════════════════════════════════════
# CUSTOM QUERYSET VA MANAGERLAR
# ═══════════════════════════════════════════════════════════════

class TimeStampedQuerySet(models.QuerySet):
    """Vaqt belgilariga ega queryset."""

    def recent(self, days: int = 7):
        threshold = timezone.now() - timedelta(days=days)
        return self.filter(created_at__gte=threshold)

    def today(self):
        return self.filter(created_at__date=timezone.now().date())

    def this_week(self):
        week_ago = timezone.now() - timedelta(days=7)
        return self.filter(created_at__gte=week_ago)

    def this_month(self):
        month_ago = timezone.now() - timedelta(days=30)
        return self.filter(created_at__gte=month_ago)


class CourseQuerySet(TimeStampedQuerySet):
    """Kurslar uchun queryset."""

    def active(self):
        return self.filter(is_active=True)

    def published(self):
        return self.filter(status='published', is_active=True)

    def ongoing(self):
        today = timezone.now().date()
        return self.filter(
            start_date__lte=today,
            end_date__gte=today,
            is_active=True,
        )

    def finished(self):
        return self.filter(end_date__lt=timezone.now().date())

    def upcoming(self):
        return self.filter(start_date__gt=timezone.now().date())

    def by_language(self, lang: str):
        return self.filter(language=lang)

    def by_level(self, level: str):
        return self.filter(level=level)

    def free(self):
        return self.filter(price=0)

    def paid(self):
        return self.filter(price__gt=0)

    def featured(self):
        return self.filter(is_featured=True, is_active=True)

    def search(self, query: str):
        return self.filter(
            Q(title__icontains=query) |
            Q(description__icontains=query) |
            Q(short_description__icontains=query) |
            Q(tags__name__icontains=query)
        ).distinct()

    def with_stats(self):
        return self.annotate(
            students_count=Count('enrollments', distinct=True),
            lessons_count=Count('lessons', distinct=True),
            avg_rating=Avg('reviews__rating'),
            total_reviews=Count('reviews', distinct=True),
        )


class CourseManager(models.Manager):
    """Kurslar manageri."""

    def get_queryset(self):
        return CourseQuerySet(self.model, using=self._db)

    def active(self):
        return self.get_queryset().active()

    def published(self):
        return self.get_queryset().published()

    def featured(self):
        return self.get_queryset().featured()


class LessonQuerySet(TimeStampedQuerySet):
    """Darslar uchun queryset."""

    def published(self):
        return self.filter(is_published=True)

    def by_course(self, course):
        return self.filter(course=course)

    def by_month(self, month):
        return self.filter(month=month)

    def by_week(self, week: int):
        return self.filter(week_number=week)

    def by_day(self, day: str):
        return self.filter(day_of_week=day)

    def completed(self):
        return self.filter(status='completed')

    def planned(self):
        return self.filter(status='planned')

    def upcoming(self):
        return self.filter(
            lesson_date__gte=timezone.now().date(),
            status__in=['planned', 'in_progress'],
        )

    def today(self):
        return self.filter(lesson_date=timezone.now().date())

    def this_week(self):
        today = timezone.now().date()
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        return self.filter(lesson_date__range=[start, end])


class HomeworkQuerySet(TimeStampedQuerySet):
    """Uyga vazifalar uchun queryset."""

    def approved(self):
        return self.filter(is_approved=True)

    def sent(self):
        return self.filter(is_sent=True)

    def active(self):
        return self.filter(
            is_approved=True,
            is_sent=True,
        )

    def pending_approval(self):
        return self.filter(is_approved=False)

    def by_course(self, course):
        return self.filter(lesson__month__course=course)

    def deadline_soon(self, hours: int = 24):
        """24 soat ichida muddati tugaydiganlar."""
        threshold = timezone.now() + timedelta(hours=hours)
        return self.filter(
            deadline__lte=threshold,
            deadline__gte=timezone.now(),
        )


class TestQuerySet(TimeStampedQuerySet):
    """Testlar uchun queryset."""

    def active(self):
        return self.filter(is_active=True)

    def by_course(self, course):
        return self.filter(course=course)

    def by_difficulty(self, difficulty: str):
        return self.filter(difficulty=difficulty)

    def free(self):
        return self.filter(is_free=True)

    def with_stats(self):
        return self.annotate(
            attempts_count=Count('attempts', distinct=True),
            avg_score=Avg('attempts__score'),
            passed_count=Count('attempts', filter=Q(attempts__is_passed=True)),
        )


# ═══════════════════════════════════════════════════════════════
# ABSTRACT MODELS
# ═══════════════════════════════════════════════════════════════

class TimeStampedModel(models.Model):
    """Vaqt belgilari bilan abstrakt model."""

    created_at = models.DateTimeField(
        auto_now_add=True, verbose_name=_("Yaratilgan")
    )
    updated_at = models.DateTimeField(
        auto_now=True, verbose_name=_("Tahrirlangan")
    )

    class Meta:
        abstract = True
        ordering = ['-created_at']


class SoftDeleteModel(models.Model):
    """Soft delete abstrakt model."""

    is_deleted = models.BooleanField(
        default=False, verbose_name=_("O‘chirilgan")
    )
    deleted_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("O‘chirilgan vaqt")
    )
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='%(class)s_deleted',
        verbose_name=_("Kim o‘chirdi"),
    )

    class Meta:
        abstract = True

    def soft_delete(self, user=None):
        """Yumshoq o‘chirish."""
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = user
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])

    def restore(self):
        """Qayta tiklash."""
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])


class SEOModel(models.Model):
    """SEO abstrakt model."""

    meta_title = models.CharField(
        max_length=200, blank=True, verbose_name=_("SEO sarlavha")
    )
    meta_description = models.TextField(
        max_length=500, blank=True, verbose_name=_("SEO tavsif")
    )
    meta_keywords = models.CharField(
        max_length=500, blank=True, verbose_name=_("SEO kalit so‘zlar")
    )
    slug = models.SlugField(
        max_length=250, unique=True, blank=True, verbose_name=_("Slug")
    )

    class Meta:
        abstract = True

    def generate_slug(self):
        """Slug generatsiya qilish."""
        if not self.slug:
            base_slug = slugify(self.title if hasattr(self, 'title') else self.name)
            self.slug = base_slug
            # Takrorlanmasligi uchun tekshirish
            Model = self.__class__
            counter = 1
            while Model.objects.filter(slug=self.slug).exclude(pk=self.pk).exists():
                self.slug = f"{base_slug}-{counter}"
                counter += 1


# ═══════════════════════════════════════════════════════════════
# 1. KURSLAR
# ═══════════════════════════════════════════════════════════════

class CourseCategory(TimeStampedModel):
    """Kurs kategoriyasi."""

    name = models.CharField(max_length=100, unique=True, verbose_name=_("Nomi"))
    slug = models.SlugField(max_length=120, unique=True, blank=True, verbose_name=_("Slug"))
    description = models.TextField(blank=True, verbose_name=_("Tavsif"))
    icon = models.CharField(
        max_length=100, default='fas fa-book',
        verbose_name=_("Ikonka")
    )
    color = models.CharField(
        max_length=20, default='#6366f1',
        verbose_name=_("Rang")
    )
    parent = models.ForeignKey(
        'self', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='children',
        verbose_name=_("Ota kategoriya")
    )
    order = models.PositiveIntegerField(default=0, verbose_name=_("Tartib"))
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))

    class Meta:
        verbose_name = _("Kurs kategoriyasi")
        verbose_name_plural = _("Kurs kategoriyalari")
        ordering = ['order', 'name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('course_category', kwargs={'slug': self.slug})

    @property
    def courses_count(self):
        return self.courses.filter(is_active=True).count()


class Tag(TimeStampedModel):
    """Teg — kurslarga biriktiriladi."""

    name = models.CharField(max_length=50, unique=True, verbose_name=_("Nomi"))
    slug = models.SlugField(max_length=60, unique=True, blank=True)
    color = models.CharField(max_length=20, default='#6b7280', verbose_name=_("Rang"))
    usage_count = models.PositiveIntegerField(default=0, verbose_name=_("Ishlatilgan"))

    class Meta:
        verbose_name = _("Teg")
        verbose_name_plural = _("Teglar")
        ordering = ['-usage_count', 'name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class CourseLanguage(models.TextChoices):
    """Kurs tili."""
    UZBEK = 'uz', _('O‘zbek')
    RUSSIAN = 'ru', _('Русский')
    ENGLISH = 'en', _('English')
    MIXED = 'mixed', _('Aralash')


class CourseLevel(models.TextChoices):
    """Kurs darajasi."""
    BEGINNER = 'beginner', _('Boshlang‘ich')
    INTERMEDIATE = 'intermediate', _('O‘rta')
    ADVANCED = 'advanced', _('Yuqori')
    EXPERT = 'expert', _('Ekspert')


class CourseStatus(models.TextChoices):
    """Kurs holati."""
    DRAFT = 'draft', _('Qoralama')
    PENDING = 'pending', _('Tasdiqlash kutilmoqda')
    PUBLISHED = 'published', _('E’lon qilingan')
    ARCHIVED = 'archived', _('Arxivlangan')


class Course(TimeStampedModel, SoftDeleteModel, SEOModel):
    """
    Kurs — 9 oylik yoki ixtiyoriy davomiylikdagi o'quv kursi.

    Asosiy kurs modeli. Har bir kursda:
    - Oylar (9 oy standart)
    - Har oyda 4 hafta
    - Har haftada 3 dars (Du, Se, Sha)
    - Har darsda testlar va uyga vazifalar
    """

    # Asosiy ma'lumotlar

    title = models.CharField(
        max_length=255, verbose_name=_("Kurs nomi"), db_index=True
    )
    short_description = models.CharField(
        max_length=300, blank=True,
        verbose_name=_("Qisqa tavsif")
    )
    description = models.TextField(
        blank=True, verbose_name=_("To'liq tavsif")
    )
    cover_image = models.ImageField(
        upload_to=course_cover_path, blank=True, null=True,
        validators=[validate_image_size],
        verbose_name=_("Muqova rasmi")
    )
    promo_video = models.URLField(
        blank=True, verbose_name=_("Taqdimot video")
    )

    # Kategoriya va teglar
    category = models.ForeignKey(
        CourseCategory, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='courses',
        verbose_name=_("Kategoriya")
    )
    tags = models.ManyToManyField(
        Tag, blank=True,
        related_name='courses',
        verbose_name=_("Teglar")
    )

    # O'qituvchi va muallif
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True,
        related_name='courses_teaching',
        verbose_name=_("O'qituvchi"),
        limit_choices_to={'role': 'teacher'},
    )
    co_teachers = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True,
        related_name='courses_co_teaching',
        verbose_name=_("Yordamchi o'qituvchilar"),
        limit_choices_to={'role': 'teacher'},
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True,
        related_name='courses_created',
        verbose_name=_("Kim yaratdi")
    )

    # Sanalar — IXTIYORIY
    start_date = models.DateField(
        null=True, blank=True,
        verbose_name=_("Boshlanish sanasi")
    )
    end_date = models.DateField(
        null=True, blank=True,
        verbose_name=_("Tugash sanasi")
    )
    duration_months = models.PositiveSmallIntegerField(
        default=9,
        validators=[MinValueValidator(1), MaxValueValidator(36)],
        verbose_name=_("Davomiyligi (oy)")
    )

    # Xususiyatlar
    language = models.CharField(
        max_length=10,
        choices=CourseLanguage.choices,
        default=CourseLanguage.UZBEK,
        verbose_name=_("Til")
    )
    level = models.CharField(
        max_length=20,
        choices=CourseLevel.choices,
        default=CourseLevel.BEGINNER,
        verbose_name=_("Daraja")
    )
    status = models.CharField(
        max_length=20,
        choices=CourseStatus.choices,
        default=CourseStatus.DRAFT,
        verbose_name=_("Holat")
    )

    # Narx va to'lov
    price = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'),
        verbose_name=_("Narxi (so'm)")
    )
    discounted_price = models.DecimalField(
        max_digits=12, decimal_places=2,
        null=True, blank=True,
        verbose_name=_("Chegirmali narx")
    )
    is_free = models.BooleanField(default=False, verbose_name=_("Bepul"))

    # Sozlamalar
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))
    is_featured = models.BooleanField(default=False, verbose_name=_("Tanlangan"))
    is_certificate_enabled = models.BooleanField(
        default=True, verbose_name=_("Sertifikat beriladi")
    )
    max_students = models.PositiveIntegerField(
        default=0, verbose_name=_("Maksimal talabalar"),
        help_text="0 = cheksiz"
    )

    # Progress sozlamalari
    passing_score = models.PositiveSmallIntegerField(
        default=60,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        verbose_name=_("O'tish bali (%)")
    )
    attendance_required = models.PositiveSmallIntegerField(
        default=75,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        verbose_name=_("Talab qilinadigan davomat (%)")
    )

    # Statistika
    view_count = models.PositiveIntegerField(default=0, verbose_name=_("Ko'rishlar"))
    enrollment_count = models.PositiveIntegerField(default=0, verbose_name=_("Yozilganlar"))
    completion_count = models.PositiveIntegerField(default=0, verbose_name=_("Tugatganlar"))

    # Reyting
    rating = models.DecimalField(
        max_digits=3, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(0), MaxValueValidator(5)],
        verbose_name=_("Reyting")
    )
    reviews_count = models.PositiveIntegerField(default=0, verbose_name=_("Sharhlar"))

    objects = CourseManager()
    all_objects = models.Manager()

    class Meta:
        verbose_name = _("Kurs")
        verbose_name_plural = _("Kurslar")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['status', 'is_active']),
            models.Index(fields=['-created_at']),
            models.Index(fields=['category', 'is_active']),
            models.Index(fields=['start_date', 'end_date']),
        ]

    def __str__(self):
        return self.title

    def clean(self):
        """Validatsiya."""
        super().clean()

        if self.start_date and self.end_date:
            if self.start_date > self.end_date:
                raise ValidationError({
                    'end_date': _("Tugash sanasi boshlanish sanasidan keyin bo'lishi kerak.")
                })

        if self.discounted_price and self.price:
            if self.discounted_price > self.price:
                raise ValidationError({
                    'discounted_price': _("Chegirmali narx asosiy narxdan katta bo'lishi mumkin emas.")
                })

    def save(self, *args, **kwargs):
        if not self.slug:
            self.generate_slug()
        if self.price == 0:
            self.is_free = True
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('course_detail', kwargs={'slug': self.slug})

    # ═══════════════════════════════════════════════════════
    # XUSUSIYATLAR — sana himoyasi bilan
    # ═══════════════════════════════════════════════════════

    @property
    def is_ongoing(self) -> bool:
        """Davom etayaptimi? Sanalar bo'lmasa — False."""
        if not self.start_date or not self.end_date:
            return False
        today = timezone.now().date()
        return self.start_date <= today <= self.end_date

    @property
    def is_upcoming(self) -> bool:
        """Boshlanmoqchimi? Sanalar bo'lmasa — False."""
        if not self.start_date:
            return False
        return self.start_date > timezone.now().date()

    @property
    def is_finished(self) -> bool:
        """Tugaganmi? Sanalar bo'lmasa — False."""
        if not self.end_date:
            return False
        return self.end_date < timezone.now().date()

    @property
    def progress_percent(self) -> float:
        """
        Kurs tugash foizi.
        Sanalar bo'lmasa — 0.0 qaytaradi.
        """
        if not self.start_date or not self.end_date:
            return 0.0

        today = timezone.now().date()

        # Hali boshlanmagan
        if self.start_date > today:
            return 0.0

        # Allaqachon tugagan
        if self.end_date < today:
            return 100.0

        total_days = (self.end_date - self.start_date).days
        if total_days <= 0:
            return 0.0

        passed_days = (today - self.start_date).days
        return round((passed_days / total_days) * 100, 1)

    @property
    def days_remaining(self) -> int:
        """Qolgan kunlar. Sanalar bo'lmasa — 0."""
        if not self.end_date:
            return 0
        today = timezone.now().date()
        if today > self.end_date:
            return 0
        return (self.end_date - today).days

    @property
    def days_total(self) -> int:
        """Umumiy kunlar soni. Sanalar bo'lmasa — 0."""
        if not self.start_date or not self.end_date:
            return 0
        return max(0, (self.end_date - self.start_date).days)

    @property
    def days_passed(self) -> int:
        """O'tgan kunlar soni. Sanalar bo'lmasa — 0."""
        if not self.start_date:
            return 0
        today = timezone.now().date()
        if today < self.start_date:
            return 0
        return (today - self.start_date).days

    @property
    def current_price(self) -> Decimal:
        """Hozirgi narx (chegirma bilan)."""
        return self.discounted_price or self.price

    @property
    def discount_percent(self) -> float:
        """Chegirma foizi."""
        if not self.discounted_price or not self.price:
            return 0.0
        try:
            return round(float((self.price - self.discounted_price) / self.price) * 100, 1)
        except (ZeroDivisionError, TypeError):
            return 0.0

    @property
    def total_lessons(self) -> int:
        """Jami darslar."""
        return self.lessons.count()

    @property
    def total_students(self) -> int:
        """Jami talabalar."""
        return self.enrollments.filter(status='active').count()

    @property
    def total_homework(self) -> int:
        """Jami uyga vazifalar."""
        return Homework.objects.filter(
            lesson__course=self, is_approved=True
        ).count()

    @property
    def total_tests(self) -> int:
        """Jami testlar."""
        return self.tests.filter(is_active=True).count()

    @property
    def average_rating(self) -> float:
        """O'rtacha reyting."""
        result = self.reviews.aggregate(avg=Avg('rating'))['avg']
        return round(float(result), 1) if result else 0.0

    @property
    def completion_rate(self) -> float:
        """Tugatish foizi."""
        if not self.enrollment_count:
            return 0.0
        return round((self.completion_count / self.enrollment_count) * 100, 1)

    @property
    def has_capacity(self) -> bool:
        """Bo'sh joy bormi?"""
        if self.max_students == 0:
            return True
        return self.total_students < self.max_students

    @property
    def duration_display(self) -> str:
        """Davomiylikni chiroyli ko'rsatish."""
        if self.duration_months:
            return f"{self.duration_months} oy"
        return "Belgilanmagan"

    @property
    def date_range_display(self) -> str:
        """Sana oralig'ini chiroyli ko'rsatish."""
        if self.start_date and self.end_date:
            return f"{self.start_date.strftime('%d.%m.%Y')} — {self.end_date.strftime('%d.%m.%Y')}"
        if self.start_date:
            return f"Boshlanish: {self.start_date.strftime('%d.%m.%Y')}"
        if self.end_date:
            return f"Tugash: {self.end_date.strftime('%d.%m.%Y')}"
        return "Sanalar belgilanmagan"

    # ═══════════════════════════════════════════════════════
    # METODLAR
    # ═══════════════════════════════════════════════════════

    def increment_view(self):
        """Ko'rishlar sonini +1."""
        Course.objects.filter(pk=self.pk).update(
            view_count=F('view_count') + 1
        )

    def get_months(self):
        """Oylar ro'yxati."""
        return self.months.order_by('month_number')

    def get_current_month(self):
        """Hozirgi oy. Sanalar bo'lmasa — None."""
        today = timezone.now().date()
        return self.months.filter(
            start_date__lte=today,
            end_date__gte=today,
        ).first()

    def get_current_week(self):
        """Hozirgi hafta raqami. Sanalar bo'lmasa — None."""
        current = self.get_current_month()
        if not current or not current.start_date:
            return None
        days_passed = (timezone.now().date() - current.start_date).days
        if days_passed < 0:
            return 1
        week = (days_passed // 7) + 1
        return min(week, 4)

    def get_today_lessons(self):
        """Bugungi darslar."""
        today = timezone.now().date()
        day_map = {
            0: 'monday',
            1: 'tuesday',
            2: 'wednesday',
            3: 'thursday',
            4: 'friday',
            5: 'saturday',
            6: 'sunday',
        }
        day = day_map.get(today.weekday())
        return self.lessons.filter(day_of_week=day)

    def get_upcoming_lessons(self, limit: int = 5):
        """Kelgusi darslar."""
        return self.lessons.filter(
            lesson_date__gte=timezone.now().date()
        ).order_by('lesson_date')[:limit]

    def get_statistics(self) -> Dict[str, Any]:
        """To'liq statistika."""
        return {
            'total_months': self.months.count(),
            'total_lessons': self.total_lessons,
            'total_homework': self.total_homework,
            'total_tests': self.total_tests,
            'total_students': self.total_students,
            'avg_rating': self.average_rating,
            'completion_rate': self.completion_rate,
            'progress_percent': self.progress_percent,
            'days_remaining': self.days_remaining,
    }

# ═══════════════════════════════════════════════════════════════
# 2. KURS OYI (9 oylik reja)
# ═══════════════════════════════════════════════════════════════

class CourseMonth(TimeStampedModel):
    """
    Kurs oyi — 9 oyga bo‘lingan kurs.
    Har oyda 4 hafta, har haftada 3 dars.
    """

    course = models.ForeignKey(
        Course, on_delete=models.CASCADE,
        related_name='months',
        verbose_name=_("Kurs")
    )
    month_number = models.PositiveSmallIntegerField(
        verbose_name=_("Oy raqami (1-9)"),
        validators=[MinValueValidator(1), MaxValueValidator(36)],
    )
    title = models.CharField(
        max_length=200, verbose_name=_("Oy nomi"),
        help_text=_("Masalan: Python asoslari")
    )
    description = models.TextField(blank=True, verbose_name=_("Tavsif"))
    goals = models.TextField(
        blank=True, verbose_name=_("Maqsadlar"),
        help_text=_("Bu oyda nimalar o‘rganiladi")
    )
    topics_covered = models.JSONField(
        default=list, blank=True,
        verbose_name=_("Yoritilgan mavzular"),
        help_text='["String methods", "Lists", ...]'
    )

    # Sanalar
    start_date = models.DateField(
        null=True, blank=True,
        verbose_name=_("Boshlanish sanasi")
    )
    end_date = models.DateField(
        null=True, blank=True,
        verbose_name=_("Tugash sanasi")
    )

    # Holat
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))
    is_completed = models.BooleanField(default=False, verbose_name=_("Tugagan"))

    # Meta
    icon = models.CharField(
        max_length=100, default='fas fa-calendar',
        verbose_name=_("Ikonka")
    )
    color = models.CharField(
        max_length=20, default='#6366f1',
        verbose_name=_("Rang")
    )

    class Meta:
        unique_together = ('course', 'month_number')
        ordering = ['course', 'month_number']
        verbose_name = _("Kurs oyi")
        verbose_name_plural = _("Kurs oylari")
        indexes = [
            models.Index(fields=['course', 'month_number']),
        ]

    def __str__(self):
        return f"{self.course.title} · {self.month_number}-oy: {self.title}"

    def clean(self):
        if self.start_date and self.end_date:
            if self.start_date > self.end_date:
                raise ValidationError({
                    'end_date': _("Tugash sanasi boshlanish sanasidan keyin bo‘lishi kerak.")
                })

    @property
    def total_weeks(self) -> int:
        """Haftalar soni."""
        return 4

    @property
    def total_lessons(self) -> int:
        """Darslar soni."""
        return self.lessons.count()

    @property
    def completed_lessons(self) -> int:
        """Tugagan darslar."""
        return self.lessons.filter(status='completed').count()

    @property
    def progress_percent(self) -> float:
        """Oy tugash foizi."""
        total = self.total_lessons
        if not total:
            return 0.0
        return round((self.completed_lessons / total) * 100, 1)

    @property
    def total_homework(self) -> int:
        """Uyga vazifalar."""
        return Homework.objects.filter(lesson__month=self).count()

    def get_weeks(self) -> List[int]:
        """Haftalar ro‘yxati."""
        return [1, 2, 3, 4]

    def get_lessons_by_week(self, week: int):
        """Hafta darslari."""
        return self.lessons.filter(week_number=week).order_by('day_of_week')

    def get_statistics(self):
        """Statistika."""
        return {
            'total_lessons': self.total_lessons,
            'completed_lessons': self.completed_lessons,
            'progress': self.progress_percent,
            'total_homework': self.total_homework,
        }


# ═══════════════════════════════════════════════════════════════
# 3. DARS (Lesson)
# ═══════════════════════════════════════════════════════════════

class LessonDay(models.TextChoices):
    """Dars kuni."""
    MONDAY = 'monday', _('Dushanba')
    TUESDAY = 'tuesday', _('Seshanba')
    WEDNESDAY = 'wednesday', _('Chorshanba')
    THURSDAY = 'thursday', _('Payshanba')
    FRIDAY = 'friday', _('Juma')
    SATURDAY = 'saturday', _('Shanba')
    SUNDAY = 'sunday', _('Yakshanba')


class LessonType(models.TextChoices):
    """Dars turi."""
    THEORY = 'theory', _('Nazariy')
    PRACTICE = 'practice', _('Amaliy')
    WORKSHOP = 'workshop', _('Seminar')
    PROJECT = 'project', _('Loyiha')
    REVIEW = 'review', _('Takrorlash')
    EXAM = 'exam', _('Imtihon')


class LessonStatus(models.TextChoices):
    """Dars holati."""
    PLANNED = 'planned', _('Rejalashtirilgan')
    IN_PROGRESS = 'in_progress', _('Davom etmoqda')
    COMPLETED = 'completed', _('O‘tilgan')
    SKIPPED = 'skipped', _('O‘tkazib yuborilgan')
    RESCHEDULED = 'rescheduled', _('Ko‘chirilgan')


# ═══════════════════════════════════════════════════════════════
# DARS — QAYTA ISHLANGAN (KURS DARAJASIDA, KETMA-KET)
# ═══════════════════════════════════════════════════════════════

class LessonManager(models.Manager):
    """Soft-delete filtri bilan manager."""
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class LessonAllManager(models.Manager):
    """Barcha lesson'lar (o'chirilgan ham)."""
    def get_queryset(self):
        return super().get_queryset()

class Lesson(TimeStampedModel, SoftDeleteModel):
    """
    Dars — KURS DARAJASIDA, oddiy ketma-ket raqam bilan.
    Har bir guruh o'z jadvali bo'yicha avtomatik oladi.
    """
    objects = LessonManager()
    all_objects = LessonAllManager()

    course = models.ForeignKey(
        Course, on_delete=models.CASCADE,
        related_name='lessons', verbose_name=_("Kurs")
    )

    # ⭐ SHU MAYDONNI QO'SHING (agar yo'q bo'lsa):
    lesson_number = models.PositiveIntegerField(
        default=1, db_index=True,
        verbose_name=_("Dars raqami"),
        help_text="1, 2, 3... ketma-ket"
    )

    # ⭐ YANGI: mavzu guruhi (ixtiyoriy) — "String methods", "Lists"
    topic = models.CharField(
        max_length=200, blank=True, verbose_name=_("Mavzu guruhi"),
        help_text="Masalan: String methods"
    )

    # ⭐ Eski week/day endi ICHKI hisob uchun (avto)
    month = models.ForeignKey(
        CourseMonth, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='lessons', verbose_name=_("Oy (avto)")
    )
    week_number = models.PositiveSmallIntegerField(
        default=1, verbose_name=_("Hafta (avto)")
    )
    day_of_week = models.CharField(
        max_length=10, choices=LessonDay.choices,
        default=LessonDay.MONDAY, verbose_name=_("Kun (avto)")
    )
    order = models.PositiveIntegerField(default=0, verbose_name=_("Tartib"))

    # ─── KONTENT ───
    title = models.CharField(max_length=255, verbose_name=_("Mavzu"))
    short_description = models.CharField(
        max_length=300, blank=True, verbose_name=_("Qisqa tavsif")
    )
    content = models.TextField(
        blank=True, verbose_name=_("To'liq nazariy matn"),
        help_text=_("Markdown yoki HTML — dars matni")
    )
    lesson_type = models.CharField(
        max_length=20, choices=LessonType.choices,
        default=LessonType.THEORY, verbose_name=_("Dars turi")
    )

    # ⭐ YANGI: Kodlar alohida chiroyli bloklarda
    # [{"title": "...", "language": "python", "code": "...", "explanation": "..."}]
    code_examples = models.JSONField(
        default=list, blank=True,
        verbose_name=_("Kod misollari"),
        help_text='[{"title": "String birlashtirish", "language": "python", "code": "a=\\"x\\"+\\"y\\"", "explanation": "Natija: xy"}]'
    )

    # ⭐ YANGI: Qo'shimcha bo'limlar (matn, ogohlantirish, maslahat)
    # [{"type": "note|warning|tip|info", "title": "...", "text": "..."}]
    extra_sections = models.JSONField(
        default=list, blank=True,
        verbose_name=_("Qo'shimcha bo'limlar"),
        help_text='[{"type": "note", "title": "Diqqat", "text": "..."}]'
    )

    # ⭐ YANGI: Qo'shimcha materiallar/havolalar
    # [{"title": "...", "url": "...", "type": "pdf|video|link|book"}]
    extra_materials = models.JSONField(
        default=list, blank=True,
        verbose_name=_("Qo'shimcha materiallar"),
        help_text='[{"title": "PDF qo\'llanma", "url": "/media/...", "type": "pdf"}]'
    )

    # Multimedia (eski maydonlar saqlanadi)
    video_url = models.URLField(blank=True, null=True, verbose_name=_("Video URL"))
    video_file = models.FileField(
        upload_to=lesson_video_path, blank=True, null=True,
        verbose_name=_("Video fayl")
    )
    attachments = models.JSONField(default=list, blank=True, verbose_name=_("Fayllar"))

    # Test va uyga vazifa (OneToOne — keyinroq formada to'ldiriladi)
    # Bu ular bilan `homework` va `test` related_name orqali bog'lanadi

    # Vaqt (avto hisoblanadi)
    lesson_date = models.DateField(null=True, blank=True, verbose_name=_("Sana"))
    duration_minutes = models.PositiveSmallIntegerField(
        default=90, verbose_name=_("Davomiyligi (daqiqa)")
    )

    # Holat
    status = models.CharField(
        max_length=20, choices=LessonStatus.choices,
        default=LessonStatus.PLANNED, verbose_name=_("Holat")
    )
    is_published = models.BooleanField(default=True, verbose_name=_("E'lon qilingan"))
    is_mandatory = models.BooleanField(default=True, verbose_name=_("Majburiy"))

    view_count = models.PositiveIntegerField(default=0, verbose_name=_("Ko'rishlar"))

    class Meta:
        # ⭐ MUHIM: endi "course + lesson_number" unique (order emas)
        unique_together = ('course', 'lesson_number')
        ordering = ['course', 'lesson_number']
        verbose_name = _("Dars")
        verbose_name_plural = _("Darslar")
        indexes = [
            models.Index(fields=['course', 'lesson_number']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.course.title} · {self.lesson_number}-dars: {self.title}"

    def save(self, *args, **kwargs):
        # Avtomatik raqam berish
        if not self.lesson_number:
            last = Lesson.objects.filter(course=self.course).order_by('-lesson_number').first()
            self.lesson_number = (last.lesson_number + 1) if last else 1

        # Hafta/kun avto hisoblash (displey uchun)
        if self.lesson_number:
            self.week_number = ((self.lesson_number - 1) // 3) + 1
            day_idx = (self.lesson_number - 1) % 3
            self.day_of_week = ['monday', 'wednesday', 'friday'][day_idx]

        self.order = self.lesson_number
        super().save(*args, **kwargs)

    # models.py — Lesson klassiga qo'shing (save() metodidan keyin)

    @property
    def has_homework(self) -> bool:
        return hasattr(self, 'homework')

    @property
    def has_test(self) -> bool:
        return hasattr(self, 'test')

    @property
    def has_video(self) -> bool:
        return bool(self.video_url or self.video_file)

    @property
    def has_live(self) -> bool:
        return False  # hozircha

    @property
    def is_today(self) -> bool:
        return self.lesson_date == timezone.now().date()

    @property
    def is_past(self) -> bool:
        return bool(self.lesson_date and self.lesson_date < timezone.now().date())

# ═══════════════════════════════════════════════════════════════
# 4. UYGA VAZIFA (Homework)
# ═══════════════════════════════════════════════════════════════

class HomeworkType(models.TextChoices):
    """Uyga vazifa turi."""
    WRITING = 'writing', _('Yozma')
    CODING = 'coding', _('Kod yozish')
    PROJECT = 'project', _('Loyiha')
    READING = 'reading', _('O‘qish')
    VIDEO = 'video', _('Video')
    MIXED = 'mixed', _('Aralash')


class Homework(TimeStampedModel, SoftDeleteModel):
    """
    Uyga vazifa — har bir darsga biriktirilgan.

    Workflow:
    1. Dars o‘tildi → Admin tasdiqlaydi
    2. Telegram → guruhga yuboriladi
    3. Talaba bajaradi va topshiradi
    4. Admin baholaydi
    """

    # Bog‘lanish
    lesson = models.OneToOneField(
        Lesson, on_delete=models.CASCADE,
        related_name='homework',
        verbose_name=_("Dars")
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True,
        related_name='homeworks_created',
        verbose_name=_("Kim yaratdi")
    )

    # Kontent
    title = models.CharField(max_length=255, verbose_name=_("Sarlavha"))
    short_description = models.CharField(
        max_length=300, blank=True,
        verbose_name=_("Qisqa tavsif")
    )
    description = models.TextField(verbose_name=_("Batafsil tavsif"))
    instructions = models.TextField(
        blank=True, verbose_name=_("Ko‘rsatmalar"),
        help_text=_("Qadam-baqadam ko‘rsatmalar")
    )
    homework_type = models.CharField(
        max_length=20,
        choices=HomeworkType.choices,
        default=HomeworkType.CODING,
        verbose_name=_("Turi")
    )

    # Fayllar
    task_file = models.FileField(
        upload_to=homework_file_path,
        blank=True, null=True,
        validators=[validate_file_size],
        verbose_name=_("Vazifa fayli")
    )
    starter_code = models.TextField(
        blank=True, verbose_name=_("Boshlang‘ich kod")
    )
    solution_code = models.TextField(
        blank=True, verbose_name=_("Namuna yechim"),
        help_text=_("Faqat admin/o‘qituvchi uchun")
    )
    reference_materials = models.JSONField(
        default=list, blank=True,
        verbose_name=_("Foydali materiallar")
    )

    # Mezonlar
    deadline_days = models.PositiveSmallIntegerField(
        default=3, verbose_name=_("Muddat (kun)"),
        validators=[MinValueValidator(1), MaxValueValidator(30)]
    )
    max_score = models.PositiveSmallIntegerField(
        default=100, verbose_name=_("Maksimal ball"),
        validators=[MinValueValidator(1), MaxValueValidator(1000)]
    )
    coins_reward = models.PositiveIntegerField(
        default=10, verbose_name=_("Coin mukofoti")
    )
    xp_reward = models.PositiveIntegerField(
        default=50, verbose_name=_("Tajriba ochkolari (XP)")
    )

    # Test (ixtiyoriy)
    quiz = models.ForeignKey(
        'Quiz', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='homeworks',
        verbose_name=_("Bog‘liq test")
    )

    # Tasdiqlash va yuborish
    is_approved = models.BooleanField(
        default=False, verbose_name=_("Tasdiqlangan")
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='homeworks_approved',
        verbose_name=_("Kim tasdiqladi")
    )
    approved_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Tasdiqlangan vaqt")
    )
    is_sent = models.BooleanField(
        default=False, verbose_name=_("Yuborilgan")
    )
    sent_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Yuborilgan vaqt")
    )
    sent_to_groups = models.ManyToManyField(
        'user.StudentGroup', blank=True,
        related_name='sent_homeworks',
        verbose_name=_("Yuborilgan guruhlar")
    )

    # Statistika
    views_count = models.PositiveIntegerField(
        default=0, verbose_name=_("Ko‘rishlar")
    )
    submissions_count = models.PositiveIntegerField(
        default=0, verbose_name=_("Topshirganlar")
    )
    avg_score = models.DecimalField(
        max_digits=5, decimal_places=2,
        default=Decimal('0.00'),
        verbose_name=_("O‘rtacha ball")
    )
    extra_quizzes = models.ManyToManyField(
        'Quiz', blank=True,
        related_name='extra_in_homeworks',
        verbose_name=_("Qo'shimcha testlar"),
        help_text="Asosiy testdan tashqari qo'shimcha testlar"
    )

    # ═══ YANGI: FOYDALI HAVOLALAR ═══
    extra_links = models.JSONField(
        default=list, blank=True,
        verbose_name=_("Foydali havolalar"),
        help_text='[{"title": "...", "url": "...", "type": "docs|video|article|book"}]'
    )
    # ═══ YANGI MAYDONLAR ═══
    difficulty = models.CharField(
        max_length=20, default='medium',
        choices=[
            ('easy', 'Oson'),
            ('medium', "O'rta"),
            ('hard', 'Qiyin'),
        ],
        verbose_name=_("Qiyinlik darajasi")
    )
    estimated_minutes = models.PositiveSmallIntegerField(
        default=60, verbose_name=_("Taxminiy vaqt (daqiqa)")
    )
    is_group_work = models.BooleanField(
        default=False, verbose_name=_("Guruh ishi")
    )
    min_group_size = models.PositiveSmallIntegerField(
        default=2, verbose_name=_("Min. guruh hajmi")
    )
    max_group_size = models.PositiveSmallIntegerField(
        default=5, verbose_name=_("Maks. guruh hajmi")
    )
    allow_late_submission = models.BooleanField(
        default=False, verbose_name=_("Kech topshirishga ruxsat")
    )
    late_penalty_percent = models.PositiveSmallIntegerField(
        default=10, verbose_name=_("Kechikish jarimasi (%)")
    )
    extra_links = models.JSONField(
        default=list, blank=True, verbose_name=_("Foydali havolalar")
    )
    extra_sections = models.JSONField(
        default=list, blank=True, verbose_name=_("Qo'shimcha bo'limlar")
    )
    extra_quizzes = models.ManyToManyField(
        'Quiz', blank=True,
        related_name='extra_in_homeworks',
        verbose_name=_("Qo'shimcha testlar")
    )

    # ═══ YANGI: QO'SHIMCHA BO'LIMLAR ═══
    extra_sections = models.JSONField(
        default=list, blank=True,
        verbose_name=_("Qo'shimcha bo'limlar"),
        help_text='[{"type": "note|warning|tip|info", "title": "...", "text": "..."}]'
    )

    # ═══ YANGI: KO'P FAYL ═══
    attachments = models.JSONField(
        default=list, blank=True,
        verbose_name=_("Qo'shimcha fayllar"),
        help_text='[{"name": "...", "url": "...", "size": 123, "type": "pdf"}]'
    )

    # ═══ YANGI: XUSUSIYATLAR ═══
    is_group_work = models.BooleanField(
        default=False, verbose_name=_("Guruh ishi")
    )
    min_group_size = models.PositiveSmallIntegerField(
        default=2, verbose_name=_("Minimal guruh hajmi")
    )
    max_group_size = models.PositiveSmallIntegerField(
        default=5, verbose_name=_("Maksimal guruh hajmi")
    )
    allow_late_submission = models.BooleanField(
        default=False, verbose_name=_("Kech topshirishga ruxsat")
    )
    late_penalty_percent = models.PositiveSmallIntegerField(
        default=10, verbose_name=_("Kechikish jarimasi (%)")
    )
    estimated_minutes = models.PositiveSmallIntegerField(
        default=60, verbose_name=_("Taxminiy vaqt (daqiqa)")
    )
    difficulty = models.CharField(
        max_length=20, default='medium',
        choices=[('easy', 'Oson'), ('medium', 'O\'rta'), ('hard', 'Qiyin')],
        verbose_name=_("Qiyinlik darajasi")
    )

    class Meta:
        verbose_name = _("Uyga vazifa")
        verbose_name_plural = _("Uyga vazifalar")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['is_approved', 'is_sent']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('homework_detail', kwargs={'pk': self.pk})

    @property
    def is_active(self) -> bool:
        """Faolmi?"""
        return self.is_approved and self.is_sent

    @property
    def total_students(self) -> int:
        """Jami talabalar — submissions orqali."""
        try:
            return self.submissions.values('student').distinct().count()
        except Exception:
            return 0

    @property
    def completed_count(self) -> int:
        """Bajarganlar soni."""
        return self.submissions.filter(score__isnull=False).count()

    @property
    def pending_count(self) -> int:
        """Kutilayotganlar soni."""
        return self.submissions.filter(score__isnull=True).count()

    @property
    def completion_rate(self) -> float:
        """Bajarish foizi."""
        total = self.total_students
        if not total:
            return 0.0
        return round((self.completed_count / total) * 100, 1)

    def get_deadline(self, student=None):
        """Deadline hisoblash."""
        if not self.sent_at:
            return None
        return self.sent_at + timedelta(days=self.deadline_days)

    def is_deadline_passed(self) -> bool:
        """Muddat o‘tganmi?"""
        deadline = self.get_deadline()
        if not deadline:
            return False
        return timezone.now() > deadline


# ═══════════════════════════════════════════════════════════════
# 5. UYGA VAZIFA TOPSHIRIG‘I
# ═══════════════════════════════════════════════════════════════

class SubmissionStatus(models.TextChoices):
    """Topshirish holati."""
    PENDING = 'pending', _('Tekshirilmoqda')
    GRADED = 'graded', _('Baholangan')
    LATE = 'late', _('Kechikkan')
    RESUBMIT = 'resubmit', _('Qayta topshirish')
    REJECTED = 'rejected', _('Rad etilgan')


class HomeworkSubmission(TimeStampedModel):
    """Talabaning uyga vazifani topshirishi."""

    homework = models.ForeignKey(
        Homework, on_delete=models.CASCADE,
        related_name='submissions',
        verbose_name=_("Vazifa")
    )
    student = models.ForeignKey(
        'user.StudentProfile',
        on_delete=models.CASCADE,
        related_name='homework_submissions',
        verbose_name=_("Talaba")
    )

    # Javob
    answer_text = models.TextField(
        blank=True, verbose_name=_("Javob matni")
    )
    answer_code = models.TextField(
        blank=True, verbose_name=_("Javob kodi")
    )
    answer_file = models.FileField(
        upload_to=submission_file_path,
        blank=True, null=True,
        validators=[validate_file_size],
        verbose_name=_("Javob fayli")
    )
    attachments = models.JSONField(
        default=list, blank=True,
        verbose_name=_("Qo‘shimcha fayllar")
    )

    # Vaqt
    submitted_at = models.DateTimeField(
        auto_now_add=True, verbose_name=_("Topshirilgan vaqt")
    )
    deadline = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Muddat")
    )
    time_spent_minutes = models.PositiveIntegerField(
        default=0, verbose_name=_("Sarflangan vaqt (daqiqa)")
    )
    is_late = models.BooleanField(default=False, verbose_name=_("Kechikkan"))

    # Baholash
    status = models.CharField(
        max_length=20,
        choices=SubmissionStatus.choices,
        default=SubmissionStatus.PENDING,
        verbose_name=_("Holat")
    )
    score = models.PositiveSmallIntegerField(
        null=True, blank=True,
        verbose_name=_("Ball")
    )
    feedback = models.TextField(
        blank=True, verbose_name=_("Ustoz izohi")
    )
    graded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='submissions_graded',
        verbose_name=_("Kim baholadi")
    )
    graded_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Baholangan vaqt")
    )
    coins_awarded = models.PositiveIntegerField(
        default=0, verbose_name=_("Berilgan coinlar")
    )
    xp_awarded = models.PositiveIntegerField(
        default=0, verbose_name=_("Berilgan XP")
    )

    # Qayta topshirish
    resubmit_count = models.PositiveSmallIntegerField(
        default=0, verbose_name=_("Qayta topshirish soni")
    )
    is_latest = models.BooleanField(
        default=True, verbose_name=_("Oxirgi versiya")
    )

    class Meta:
        unique_together = ('homework', 'student', 'is_latest')
        ordering = ['-submitted_at']
        verbose_name = _("Uyga vazifa topshirig‘i")
        verbose_name_plural = _("Uyga vazifa topshirig‘lari")
        indexes = [
            models.Index(fields=['student', '-submitted_at']),
            models.Index(fields=['status', 'is_late']),
        ]

    def __str__(self):
        return f"{self.student.user.get_full_name()} · {self.homework.title}"

    def get_absolute_url(self):
        return reverse('submission_detail', kwargs={'pk': self.pk})

    @property
    def percent(self) -> float:
        """Ball foizi."""
        if self.score is None:
            return 0.0
        max_score = self.homework.max_score
        if not max_score:
            return 0.0
        return round((self.score / max_score) * 100, 1)

    @property
    def grade_letter(self) -> str:
        """Harf baho."""
        pct = self.percent
        if pct >= 90: return 'A'
        if pct >= 80: return 'B'
        if pct >= 70: return 'C'
        if pct >= 60: return 'D'
        return 'F'

    @property
    def grade_color(self) -> str:
        """Baho rangi."""
        colors = {
            'A': '#10b981', 'B': '#3b82f6',
            'C': '#f59e0b', 'D': '#f97316', 'F': '#ef4444',
        }
        return colors.get(self.grade_letter, '#6b7280')

    @property
    def is_graded(self) -> bool:
        """Baholanganmi?"""
        return self.score is not None

    @property
    def is_passed(self) -> bool:
        """O‘tganmi?"""
        return self.percent >= 60

    @transaction.atomic
    def grade(self, score: int, graded_by, feedback: str = ''):
        """Baholash."""
        self.score = score
        self.feedback = feedback
        self.graded_by = graded_by
        self.graded_at = timezone.now()
        self.status = SubmissionStatus.GRADED

        # Coin va XP hisoblash
        if self.percent >= 60:
            self.coins_awarded = self.homework.coins_reward
            self.xp_awarded = self.homework.xp_reward
        else:
            self.coins_awarded = 0
            self.xp_awarded = self.homework.xp_reward // 2

        self.save()

        # Talabaga coin qo‘shish
        if self.coins_awarded:
            from apps.user.models import StudentProfile
            StudentProfile.objects.filter(pk=self.student.pk).update(
                coins=F('coins') + self.coins_awarded
            )

    def resubmit(self, answer_text: str = '', answer_code: str = ''):
        """Qayta topshirish."""
        # Eskisini is_latest=False qilish
        HomeworkSubmission.objects.filter(
            homework=self.homework,
            student=self.student,
            is_latest=True,
        ).update(is_latest=False)

        # Yangi yaratish
        new = HomeworkSubmission.objects.create(
            homework=self.homework,
            student=self.student,
            answer_text=answer_text,
            answer_code=answer_code,
            resubmit_count=self.resubmit_count + 1,
            is_latest=True,
            deadline=self.deadline,
            is_late=timezone.now() > self.deadline if self.deadline else False,
        )
        return new


# ═══════════════════════════════════════════════════════════════
# 6. TEST (Quiz)
# ═══════════════════════════════════════════════════════════════

class QuizDifficulty(models.TextChoices):
    """Test qiyinligi."""
    EASY = 'easy', _('Oson')
    MEDIUM = 'medium', _('O‘rta')
    HARD = 'hard', _('Qiyin')
    EXPERT = 'expert', _('Ekspert')


class Quiz(TimeStampedModel, SoftDeleteModel):
    """Test."""

    # Bog‘lanish
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE,
        related_name='tests',
        verbose_name=_("Kurs"),
        null=True, blank=True,
    )
    lesson = models.OneToOneField(
        Lesson, on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='test',
        verbose_name=_("Dars")
    )
    category = models.ForeignKey(
    'user.QuizCategory',
    on_delete=models.SET_NULL,
    null=True, blank=True,
    related_name='course_quizzes',    # ← O'ZGARTIR
    verbose_name=_("Kategoriya")
)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True,
        related_name='quizzes_created',
        verbose_name=_("Kim yaratdi")
    )

    # Asosiy
    title = models.CharField(max_length=255, verbose_name=_("Test nomi"))
    description = models.TextField(blank=True, verbose_name=_("Tavsif"))
    instructions = models.TextField(
        blank=True, verbose_name=_("Ko‘rsatmalar")
    )
    difficulty = models.CharField(
        max_length=20,
        choices=QuizDifficulty.choices,
        default=QuizDifficulty.MEDIUM,
        verbose_name=_("Qiyinlik")
    )

    # Sozlamalar
    duration_minutes = models.PositiveIntegerField(
        default=30,
        validators=[MinValueValidator(1), MaxValueValidator(300)],
        verbose_name=_("Davomiyligi (daqiqa)")
    )
    passing_score = models.PositiveSmallIntegerField(
        default=60,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        verbose_name=_("O‘tish bali (%)")
    )
    max_attempts = models.PositiveSmallIntegerField(
        default=3, verbose_name=_("Maksimal urinishlar")
    )

    # Ko‘rinish
    shuffle_questions = models.BooleanField(
        default=False, verbose_name=_("Savollarni aralashtirish")
    )
    shuffle_options = models.BooleanField(
        default=False, verbose_name=_("Javoblarni aralashtirish")
    )
    show_correct_answers = models.BooleanField(
        default=True, verbose_name=_("To‘g‘ri javoblarni ko‘rsatish")
    )
    show_results_immediately = models.BooleanField(
        default=True, verbose_name=_("Natijani darhol ko‘rsatish")
    )
    allow_back = models.BooleanField(
        default=True, verbose_name=_("Orqaga qaytish")
    )
    allow_skip = models.BooleanField(
        default=False, verbose_name=_("Savolni o‘tkazib yuborish")
    )

    # Mukofotlar
    coins_reward = models.PositiveIntegerField(
        default=0, verbose_name=_("Coin mukofoti")
    )
    xp_reward = models.PositiveIntegerField(
        default=0, verbose_name=_("XP mukofoti")
    )

    # Holat
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))
    is_free = models.BooleanField(default=False, verbose_name=_("Bepul"))
    is_practice = models.BooleanField(
        default=False, verbose_name=_("Mashq rejimi")
    )

    # Statistika
    attempts_count = models.PositiveIntegerField(
        default=0, verbose_name=_("Urinishlar soni")
    )
    passes_count = models.PositiveIntegerField(
        default=0, verbose_name=_("O‘tganlar")
    )
    average_score = models.DecimalField(
        max_digits=5, decimal_places=2,
        default=Decimal('0.00'),
        verbose_name=_("O‘rtacha ball")
    )

    class Meta:
        verbose_name = _("Test")
        verbose_name_plural = _("Testlar")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['course', 'is_active']),
            models.Index(fields=['difficulty']),
        ]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('quiz_detail', kwargs={'pk': self.pk})

    @property
    def total_questions(self) -> int:
        """Savollar soni."""
        return self.questions.count()

    @property
    def total_points(self) -> int:
        """Umumiy ballar."""
        return self.questions.aggregate(
            total=Coalesce(Sum('points'), 0)
        )['total']

    @property
    def success_rate(self) -> float:
        """Muvaffaqiyat foizi."""
        total = self.attempts_count
        if not total:
            return 0.0
        return round((self.passes_count / total) * 100, 1)

    @property
    def difficulty_color(self) -> str:
        """Qiyinlik rangi."""
        colors = {
            'easy': '#10b981',
            'medium': '#f59e0b',
            'hard': '#ef4444',
            'expert': '#8b5cf6',
        }
        return colors.get(self.difficulty, '#6b7280')


# ═══════════════════════════════════════════════════════════════
# 7. SAVOL (Question)
# ═══════════════════════════════════════════════════════════════

class QuestionType(models.TextChoices):
    """Savol turi."""
    SINGLE_CHOICE = 'single', _('Bitta javob')
    MULTIPLE_CHOICE = 'multiple', _('Ko‘p javob')
    TRUE_FALSE = 'true_false', _('To‘g‘ri/Noto‘g‘ri')
    TEXT = 'text', _('Matnli javob')
    NUMBER = 'number', _('Raqamli javob')
    MATCHING = 'matching', _('Moslashtirish')
    ORDERING = 'ordering', _('Tartiblash')
    CODE = 'code', _('Kod yozish')


class Question(TimeStampedModel):
    """Savol."""

    quiz = models.ForeignKey(
        Quiz, on_delete=models.CASCADE,
        related_name='questions',
        verbose_name=_("Test")
    )
    question_type = models.CharField(
        max_length=20,
        choices=QuestionType.choices,
        default=QuestionType.SINGLE_CHOICE,
        verbose_name=_("Savol turi")
    )
    text = models.TextField(verbose_name=_("Savol matni"))
    image = models.ImageField(
        upload_to='quiz_questions/',
        blank=True, null=True,
        validators=[validate_image_size],
        verbose_name=_("Rasm")
    )
    video_url = models.URLField(
        blank=True, null=True, verbose_name=_("Video")
    )

    # Ball va tartib
    points = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        verbose_name=_("Ball")
    )
    order = models.PositiveIntegerField(default=0, verbose_name=_("Tartib"))
    difficulty = models.CharField(
        max_length=20,
        choices=QuizDifficulty.choices,
        default=QuizDifficulty.MEDIUM,
        verbose_name=_("Qiyinlik")
    )

    # Qo‘shimcha
    explanation = models.TextField(
        blank=True, verbose_name=_("Tushuntirish"),
        help_text=_("Javobdan keyin ko‘rsatiladi")
    )
    hint = models.TextField(blank=True, verbose_name=_("Yordam"))

    # Boshqa tur uchun
    correct_text = models.CharField(
        max_length=500, blank=True,
        verbose_name=_("To‘g‘ri javob matni")
    )
    correct_number = models.DecimalField(
        max_digits=12, decimal_places=4,
        null=True, blank=True,
        verbose_name=_("To‘g‘ri raqam")
    )
    number_tolerance = models.DecimalField(
        max_digits=12, decimal_places=4,
        default=Decimal('0.01'),
        verbose_name=_("Raqam xatoligi")
    )

    # Kod savol uchun
    code_language = models.CharField(
        max_length=20, blank=True, verbose_name=_("Kod tili")
    )
    starter_code = models.TextField(
        blank=True, verbose_name=_("Boshlang‘ich kod")
    )
    expected_output = models.TextField(
        blank=True, verbose_name=_("Kutilgan natija")
    )

    class Meta:
        ordering = ['order', 'id']
        verbose_name = _("Savol")
        verbose_name_plural = _("Savollar")
        indexes = [models.Index(fields=['quiz', 'order'])]

    def __str__(self):
        return self.text[:60]

    @property
    def has_correct_option(self) -> bool:
        """To‘g‘ri javob bormi?"""
        return self.options.filter(is_correct=True).exists()

    def get_correct_options(self):
        """To‘g‘ri variantlar."""
        return self.options.filter(is_correct=True)


# ═══════════════════════════════════════════════════════════════
# 8. JAVOB VARIANTI (AnswerOption)
# ═══════════════════════════════════════════════════════════════

class AnswerOption(TimeStampedModel):
    """Javob varianti."""

    question = models.ForeignKey(
        Question, on_delete=models.CASCADE,
        related_name='options',
        verbose_name=_("Savol")
    )
    text = models.CharField(max_length=500, verbose_name=_("Javob"))
    image = models.ImageField(
        upload_to='quiz_options/',
        blank=True, null=True,
        verbose_name=_("Rasm")
    )
    is_correct = models.BooleanField(
        default=False, verbose_name=_("To‘g‘ri javob")
    )
    order = models.PositiveIntegerField(default=0, verbose_name=_("Tartib"))

    # Matching uchun
    match_text = models.CharField(
        max_length=500, blank=True,
        verbose_name=_("Mos javob")
    )

    class Meta:
        ordering = ['order', 'id']
        verbose_name = _("Javob varianti")
        verbose_name_plural = _("Javob variantlari")

    def __str__(self):
        mark = "✓" if self.is_correct else "✗"
        return f"{mark} {self.text[:50]}"


# ═══════════════════════════════════════════════════════════════
# 9. TEST URINISHI (QuizAttempt)
# ═══════════════════════════════════════════════════════════════

class AttemptStatus(models.TextChoices):
    """Urinish holati."""
    IN_PROGRESS = 'in_progress', _('Davom etmoqda')
    COMPLETED = 'completed', _('Yakunlangan')
    ABANDONED = 'abandoned', _('Tashlab ketilgan')
    TIME_EXPIRED = 'expired', _('Vaqt tugagan')


class QuizAttempt(TimeStampedModel):
    """Test urinishi."""

    quiz = models.ForeignKey(
        Quiz, on_delete=models.CASCADE,
        related_name='attempts',
        verbose_name=_("Test")
    )
    student = models.ForeignKey(
        'user.StudentProfile',
        on_delete=models.CASCADE,
        related_name='quiz_attempts',
        verbose_name=_("Talaba")
    )

    # Holat
    status = models.CharField(
        max_length=20,
        choices=AttemptStatus.choices,
        default=AttemptStatus.IN_PROGRESS,
        verbose_name=_("Holat")
    )
    started_at = models.DateTimeField(
        auto_now_add=True, verbose_name=_("Boshlangan")
    )
    completed_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Tugagan")
    )
    time_spent_seconds = models.PositiveIntegerField(
        default=0, verbose_name=_("Sarflangan vaqt (sek)")
    )

    # Natija
    score = models.PositiveSmallIntegerField(
        default=0, verbose_name=_("Ball")
    )
    max_score = models.PositiveSmallIntegerField(
        default=0, verbose_name=_("Maks. ball")
    )
    correct_count = models.PositiveSmallIntegerField(
        default=0, verbose_name=_("To‘g‘ri javoblar")
    )
    wrong_count = models.PositiveSmallIntegerField(
        default=0, verbose_name=_("Xato javoblar")
    )
    skipped_count = models.PositiveSmallIntegerField(
        default=0, verbose_name=_("O‘tkazib yuborilganlar")
    )
    is_passed = models.BooleanField(
        default=False, verbose_name=_("O‘tgan")
    )
    coins_awarded = models.PositiveIntegerField(
        default=0, verbose_name=_("Berilgan coinlar")
    )
    xp_awarded = models.PositiveIntegerField(
        default=0, verbose_name=_("Berilgan XP")
    )

    # Qo‘shimcha
    attempt_number = models.PositiveSmallIntegerField(
        default=1, verbose_name=_("Urinish raqami")
    )
    ip_address = models.GenericIPAddressField(
        null=True, blank=True, verbose_name=_("IP manzil")
    )
    user_agent = models.TextField(
        blank=True, verbose_name=_("Brauzer")
    )

    class Meta:
        ordering = ['-started_at']
        verbose_name = _("Test urinishi")
        verbose_name_plural = _("Test urinishlari")
        indexes = [
            models.Index(fields=['student', '-started_at']),
            models.Index(fields=['quiz', '-started_at']),
        ]

    def __str__(self):
        return f"{self.student.user.get_full_name()} · {self.quiz.title}"

    @property
    def percent(self) -> float:
        """Foiz."""
        if not self.max_score:
            return 0.0
        return round((self.score / self.max_score) * 100, 1)

    @property
    def grade_letter(self) -> str:
        """Harf baho."""
        pct = self.percent
        if pct >= 90: return 'A'
        if pct >= 80: return 'B'
        if pct >= 70: return 'C'
        if pct >= 60: return 'D'
        return 'F'

    @property
    def time_spent_display(self) -> str:
        """Sarflangan vaqt."""
        s = self.time_spent_seconds
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h} soat {m} daq"
        return f"{m} daq {s} sek"

    @transaction.atomic
    def complete(self):
        """Yakunlash."""
        self.status = AttemptStatus.COMPLETED
        self.completed_at = timezone.now()
        self.is_passed = self.percent >= self.quiz.passing_score

        # Coin va XP
        if self.is_passed:
            self.coins_awarded = self.quiz.coins_reward
            self.xp_awarded = self.quiz.xp_reward
        else:
            self.coins_awarded = 0
            self.xp_awarded = 0

        self.save()

        # Statistikani yangilash
        Quiz.objects.filter(pk=self.quiz.pk).update(
            attempts_count=F('attempts_count') + 1,
        )
        if self.is_passed:
            Quiz.objects.filter(pk=self.quiz.pk).update(
                passes_count=F('passes_count') + 1,
            )


# ═══════════════════════════════════════════════════════════════
# 10. TEST JAVOBI (AttemptAnswer)
# ═══════════════════════════════════════════════════════════════

class AttemptAnswer(TimeStampedModel):
    """Talabaning bir savolga bergan javobi."""

    attempt = models.ForeignKey(
        QuizAttempt, on_delete=models.CASCADE,
        related_name='answers',
        verbose_name=_("Urinish")
    )
    question = models.ForeignKey(
        Question, on_delete=models.CASCADE,
        verbose_name=_("Savol")
    )
    selected_options = models.ManyToManyField(
        AnswerOption, blank=True,
        related_name='selected_in',
        verbose_name=_("Tanlangan variantlar")
    )

    # Boshqa turdagi javoblar
    text_answer = models.TextField(
        blank=True, verbose_name=_("Matnli javob")
    )
    number_answer = models.DecimalField(
        max_digits=12, decimal_places=4,
        null=True, blank=True,
        verbose_name=_("Raqamli javob")
    )
    code_answer = models.TextField(
        blank=True, verbose_name=_("Kod javobi")
    )

    # Baholash
    is_correct = models.BooleanField(
        default=False, verbose_name=_("To‘g‘ri")
    )
    points_earned = models.PositiveSmallIntegerField(
        default=0, verbose_name=_("Olingan ball")
    )
    answered_at = models.DateTimeField(
        auto_now_add=True, verbose_name=_("Javob vaqti")
    )
    time_spent_seconds = models.PositiveIntegerField(
        default=0, verbose_name=_("Sarflangan vaqt")
    )
    is_skipped = models.BooleanField(
        default=False, verbose_name=_("O‘tkazib yuborilgan")
    )

    class Meta:
        unique_together = ('attempt', 'question')
        verbose_name = _("Test javobi")
        verbose_name_plural = _("Test javoblari")

    def __str__(self):
        return f"{self.question.text[:40]} → {self.is_correct}"


# ═══════════════════════════════════════════════════════════════
# 11. GURUH (StudentGroup)
# ═══════════════════════════════════════════════════════════════

class GroupStatus(models.TextChoices):
    """Guruh holati."""
    ACTIVE = 'active', _('Aktiv')
    PAUSED = 'paused', _('To‘xtatilgan')
    FINISHED = 'finished', _('Tugagan')
    ARCHIVED = 'archived', _('Arxivlangan')


class StudentGroup(TimeStampedModel, SoftDeleteModel):
    """
    Talabalar guruhi — masalan B6, B7.
    Bir nechta kursga yozilishi mumkin.
    """

    # Asosiy
    name = models.CharField(
        max_length=100, unique=True, verbose_name=_("Guruh nomi")
    )
    code = models.CharField(
        max_length=20, unique=True, blank=True,
        verbose_name=_("Guruh kodi"),
        help_text=_("Masalan: B6-2025")
    )
    description = models.TextField(blank=True, verbose_name=_("Tavsif"))

    # Bog‘lanishlar
    course = models.ForeignKey(
        Course, on_delete=models.SET_NULL,
        null=True, blank=True,
          related_name='course_groups',
        verbose_name=_("Asosiy kurs")
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
         related_name='course_groups_taught',
        verbose_name=_("O‘qituvchi"),
        limit_choices_to={'role': 'teacher'}
    )
    assistant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='course_groups_assisted',
        verbose_name=_("Yordamchi")
    )

    # Talabalar
    students = models.ManyToManyField(
        'user.StudentProfile',
        blank=True,
          related_name='course_groups',
        verbose_name=_("Talabalar")
    )

    # Sozlamalar
    max_students = models.PositiveIntegerField(
        default=20, verbose_name=_("Maksimal talabalar")
    )
    status = models.CharField(
        max_length=20,
        choices=GroupStatus.choices,
        default=GroupStatus.ACTIVE,
        verbose_name=_("Holat")
    )

    # Sanalar
    start_date = models.DateField(
        null=True, blank=True, verbose_name=_("Boshlanish")
    )
    end_date = models.DateField(
        null=True, blank=True, verbose_name=_("Tugash")
    )

    # Dars vaqti
    schedule = models.JSONField(
        default=dict, blank=True,
        verbose_name=_("Jadval"),
        help_text='{"monday": "14:00", "tuesday": "14:00", "saturday": "10:00"}'
    )
    room = models.CharField(
        max_length=100, blank=True, verbose_name=_("Xona")
    )

    # Dizayn
    color = models.CharField(
        max_length=20, default='#6366f1', verbose_name=_("Rang")
    )
    cover_image = models.ImageField(
        upload_to='groups/covers/',
        blank=True, null=True,
        verbose_name=_("Muqova")
    )

    # Telegram
    telegram_group_id = models.BigIntegerField(
        null=True, blank=True, verbose_name=_("Telegram guruh ID")
    )
    telegram_invite_link = models.URLField(
        blank=True, verbose_name=_("Telegram taklif havolasi")
    )

    # Statistika
    total_lessons = models.PositiveIntegerField(
        default=0, verbose_name=_("Darslar soni")
    )
    completed_lessons = models.PositiveIntegerField(
        default=0, verbose_name=_("Tugagan darslar")
    )
    SCHEDULE_TYPE_CHOICES = (
        ('odd', 'Toq kunlar (Du · Ch · Ju)'),
        ('even', 'Juft kunlar (Se · Pa · Sha)'),
        ('custom', 'Qo\'lda sozlash'),
    )
    schedule_type = models.CharField(
        max_length=10, choices=SCHEDULE_TYPE_CHOICES,
        default='odd', verbose_name=_("Dars kunlari turi"),
        help_text="Toq kunlar: Dushanba, Chorshanba, Juma"
    )

    # ⭐ YANGI: darslar boshlanish sanasi
    lessons_start_date = models.DateField(
        null=True, blank=True, verbose_name=_("Darslar boshlanish sanasi")
    )

    class Meta:
        verbose_name = _("Talabalar guruhi")
        verbose_name_plural = _("Talabalar guruhlari")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['course']),
        ]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('group_detail', kwargs={'pk': self.pk})

    def save(self, *args, **kwargs):
        if not self.code and self.name:
            year = timezone.now().year
            self.code = f"{self.name.upper()}-{year}"
        super().save(*args, **kwargs)

    # ═══ Xususiyatlar ═══

    @property
    def students_count(self) -> int:
        """Talabalar soni."""
        return self.students.filter(user__is_active=True).count()

    @property
    def has_capacity(self) -> bool:
        """Bo‘sh joy bormi?"""
        return self.students_count < self.max_students

    @property
    def capacity_percent(self) -> float:
        """To‘lish foizi."""
        if not self.max_students:
            return 0.0
        return round((self.students_count / self.max_students) * 100, 1)

    @property
    def average_score(self) -> float:
        """O‘rtacha ball."""
        result = HomeworkSubmission.objects.filter(
            student__in=self.students.all(),
            score__isnull=False,
        ).aggregate(avg=Avg('score'))['avg']
        return round(float(result), 1) if result else 0.0

    @property
    def average_attendance(self) -> float:
        """O‘rtacha davomat."""
        # Hisoblash
        return 0.0

    @property
    def total_coins(self) -> int:
        """Jami coinlar."""
        return self.students.aggregate(
            total=Coalesce(Sum('coins'), 0)
        )['total']

    @property
    def active_week(self) -> int:
        """Hozirgi hafta."""
        if not self.start_date:
            return 0
        days_passed = (timezone.now().date() - self.start_date).days
        return max(1, (days_passed // 7) + 1)

    @property
    def schedule_display(self) -> str:
        """Jadval ko‘rinishi."""
        if not self.schedule:
            return "Belgilanmagan"
        parts = []
        day_names = {
            'monday': 'Du', 'tuesday': 'Se', 'wednesday': 'Ch',
            'thursday': 'Pa', 'friday': 'Ju', 'saturday': 'Sha', 'sunday': 'Ya',
        }
        for day, time in self.schedule.items():
            parts.append(f"{day_names.get(day, day)} {time}")
        return " · ".join(parts)

    # ═══ Metodlar ═══

    def add_student(self, student):
        """Talabani qo‘shish."""
        if not self.has_capacity:
            raise ValidationError("Guruh to‘lgan!")
        self.students.add(student)
        return True

    def remove_student(self, student):
        """Talabani chiqarish."""
        self.students.remove(student)
        return True

    def get_lessons(self):
        """Guruh darslari."""
        return self.lessons.order_by('lesson_date', 'start_time')

    def get_upcoming_lessons(self, limit: int = 5):
        """Kelgusi darslar."""
        return self.lessons.filter(
            lesson_date__gte=timezone.now().date()
        ).order_by('lesson_date')[:limit]

    def get_today_lessons(self):
        """Bugungi darslar."""
        return self.lessons.filter(lesson_date=timezone.now().date())

    def get_ranking(self, limit: int = 10):
        """Guruh reytingi."""
        from apps.user.models import StudentProfile
        students = self.students.annotate(
            total_score=Coalesce(Sum('homework_submissions__score'), 0),
            total_coins=Coalesce(Sum('coins'), 0),
        ).order_by('-total_score', '-coins')[:limit]
        return students

    def get_statistics(self) -> Dict[str, Any]:
        """Statistika."""
        return {
            'students_count': self.students_count,
            'capacity_percent': self.capacity_percent,
            'average_score': self.average_score,
            'total_coins': self.total_coins,
            'active_week': self.active_week,
            'total_lessons': self.total_lessons,
            'completed_lessons': self.completed_lessons,
        }


# ═══════════════════════════════════════════════════════════════
# 12. GURUH TALABASI (ManyToMany through)
# ═══════════════════════════════════════════════════════════════

class GroupMember(TimeStampedModel):
    """Guruh a’zosi — qo‘shimcha ma’lumotlar bilan."""

    ROLE_CHOICES = (
        ('student', 'Talaba'),
        ('leader', 'Guruh sardori'),
        ('assistant', 'Yordamchi'),
    )

    group = models.ForeignKey(
        'user.StudentGroup', on_delete=models.CASCADE,
        related_name='members',
        verbose_name=_("Guruh")
    )
    student = models.ForeignKey(
        'user.StudentProfile',
        on_delete=models.CASCADE,
        related_name='group_memberships',
        verbose_name=_("Talaba")
    )
    role = models.CharField(
        max_length=20, choices=ROLE_CHOICES,
        default='student', verbose_name=_("Roli")
    )
    joined_at = models.DateField(
        default=timezone.now, verbose_name=_("Qo‘shilgan sana")
    )
    left_at = models.DateField(
        null=True, blank=True, verbose_name=_("Chiqib ketgan")
    )
    is_active = models.BooleanField(
        default=True, verbose_name=_("Faol")
    )
    notes = models.TextField(blank=True, verbose_name=_("Izohlar"))

    class Meta:
        unique_together = ('group', 'student')
        verbose_name = _("Guruh a’zosi")
        verbose_name_plural = _("Guruh a’zolari")

    def __str__(self):
        return f"{self.student.user.get_full_name()} → {self.group.name}"


# ═══════════════════════════════════════════════════════════════
# 13. KURSGA YOZILISH (Enrollment)
# ═══════════════════════════════════════════════════════════════

class EnrollmentStatus(models.TextChoices):
    """Yozilish holati."""
    PENDING = 'pending', _('Kutilmoqda')
    ACTIVE = 'active', _('Aktiv')
    PAUSED = 'paused', _('To‘xtatilgan')
    COMPLETED = 'completed', _('Tugatgan')
    DROPPED = 'dropped', _('Tashlab ketgan')
    EXPIRED = 'expired', _('Muddati tugagan')


class Enrollment(TimeStampedModel):
    """Talabaning kursga yozilishi."""

    student = models.ForeignKey(
        'user.StudentProfile',
        on_delete=models.CASCADE,
        related_name='enrollments',
        verbose_name=_("Talaba")
    )
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE,
        related_name='enrollments',
        verbose_name=_("Kurs")
    )
    group = models.ForeignKey(
        'user.StudentGroup', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='enrollments',
        verbose_name=_("Guruh")
    )

    # Holat
    status = models.CharField(
        max_length=20,
        choices=EnrollmentStatus.choices,
        default=EnrollmentStatus.ACTIVE,
        verbose_name=_("Holat")
    )

    # Sanalar
    enrolled_at = models.DateTimeField(
        auto_now_add=True, verbose_name=_("Yozilgan vaqt")
    )
    started_at = models.DateField(
        null=True, blank=True, verbose_name=_("Boshlagan")
    )
    completed_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Tugatgan")
    )

    # Progress
    progress_percent = models.DecimalField(
        max_digits=5, decimal_places=2,
        default=Decimal('0.00'),
        verbose_name=_("Progress (%)")
    )
    lessons_completed = models.PositiveIntegerField(
        default=0, verbose_name=_("Tugagan darslar")
    )
    homework_submitted = models.PositiveIntegerField(
        default=0, verbose_name=_("Topshirilgan vazifalar")
    )
    homework_graded = models.PositiveIntegerField(
        default=0, verbose_name=_("Baholangan vazifalar")
    )

    # Natija
    total_score = models.PositiveIntegerField(
        default=0, verbose_name=_("Umumiy ball")
    )
    average_score = models.DecimalField(
        max_digits=5, decimal_places=2,
        default=Decimal('0.00'),
        verbose_name=_("O‘rtacha ball")
    )
    grade = models.CharField(
        max_length=5, blank=True, verbose_name=_("Yakuniy baho")
    )
    is_passed = models.BooleanField(
        default=False, verbose_name=_("O‘tgan")
    )

    # To‘lov
    is_paid = models.BooleanField(default=False, verbose_name=_("To‘langan"))
    paid_amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        default=Decimal('0.00'),
        verbose_name=_("To‘langan summa")
    )

    # Sertifikat
    certificate_issued = models.BooleanField(
        default=False, verbose_name=_("Sertifikat berilgan")
    )
    certificate_file = models.FileField(
        upload_to=certificate_path,
        blank=True, null=True,
        verbose_name=_("Sertifikat fayli")
    )
    certificate_id = models.CharField(
        max_length=50, blank=True, unique=False,
        verbose_name=_("Sertifikat ID")
    )

    class Meta:
        unique_together = ('student', 'course')
        ordering = ['-enrolled_at']
        verbose_name = _("Kursga yozilish")
        verbose_name_plural = _("Kursga yozilishlar")
        indexes = [
            models.Index(fields=['student', 'course']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.student.user.get_full_name()} → {self.course.title}"

    @property
    def progress(self) -> float:
        """Progress foizi."""
        return float(self.progress_percent)

    @property
    def days_since_enrolled(self) -> int:
        """Yozilgandan keyin kunlar."""
        return (timezone.now() - self.enrolled_at).days

    @property
    def is_active(self) -> bool:
        """Aktivmi?"""
        return self.status == EnrollmentStatus.ACTIVE

    def update_progress(self):
        """Progressni yangilash."""
        total_lessons = self.course.total_lessons
        if not total_lessons:
            return
        self.progress_percent = Decimal(
            str(round((self.lessons_completed / total_lessons) * 100, 2))
        )
        self.save(update_fields=['progress_percent'])

    def issue_certificate(self):
        """Sertifikat berish."""
        if not self.is_passed:
            raise ValidationError("Kurs o‘tilmagan!")
        self.certificate_issued = True
        self.certificate_id = f"CERT-{self.id}-{uuid.uuid4().hex[:8].upper()}"
        self.save(update_fields=['certificate_issued', 'certificate_id'])


# ═══════════════════════════════════════════════════════════════
# 14. DAVOMAT (Attendance)
# ═══════════════════════════════════════════════════════════════

class AttendanceStatus(models.TextChoices):
    """Davomat holati."""
    PRESENT = 'present', _('Kelgan')
    ABSENT = 'absent', _('Kelmagan')
    LATE = 'late', _('Kechikkan')
    EXCUSED = 'excused', _('Sababli')
    ONLINE = 'online', _('Online')


class Attendance(TimeStampedModel):
    """Davomat yozuvi."""

    lesson = models.ForeignKey(
        Lesson, on_delete=models.CASCADE,
        related_name='attendance',
        verbose_name=_("Dars")
    )
    student = models.ForeignKey(
        'user.StudentProfile',
        on_delete=models.CASCADE,
        related_name='attendances',
        verbose_name=_("Talaba")
    )
    status = models.CharField(
        max_length=20,
        choices=AttendanceStatus.choices,
        default=AttendanceStatus.PRESENT,
        verbose_name=_("Holat")
    )
    marked_at = models.DateTimeField(
        auto_now_add=True, verbose_name=_("Belgilangan vaqt")
    )
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True,
        related_name='attendance_marked',
        verbose_name=_("Kim belgiladi")
    )
    notes = models.TextField(blank=True, verbose_name=_("Izoh"))
    check_in_time = models.TimeField(
        null=True, blank=True, verbose_name=_("Kelgan vaqt")
    )
    check_out_time = models.TimeField(
        null=True, blank=True, verbose_name=_("Ketgan vaqt")
    )

    class Meta:
        unique_together = ('lesson', 'student')
        ordering = ['-marked_at']
        verbose_name = _("Davomat")
        verbose_name_plural = _("Davomat yozuvlari")
        indexes = [
            models.Index(fields=['lesson', 'student']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.student.user.get_full_name()} · {self.lesson.title}"


# ═══════════════════════════════════════════════════════════════
# 15. KURS SHARHI (Review)
# ═══════════════════════════════════════════════════════════════

class Review(TimeStampedModel):
    """Kursga sharh."""

    course = models.ForeignKey(
        Course, on_delete=models.CASCADE,
        related_name='reviews',
        verbose_name=_("Kurs")
    )
    student = models.ForeignKey(
        'user.StudentProfile',
        on_delete=models.CASCADE,
        related_name='course_reviews',
        verbose_name=_("Talaba")
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        verbose_name=_("Reyting")
    )
    title = models.CharField(
        max_length=200, blank=True, verbose_name=_("Sarlavha")
    )
    comment = models.TextField(verbose_name=_("Sharh"))
    is_anonymous = models.BooleanField(
        default=False, verbose_name=_("Anonim")
    )
    is_approved = models.BooleanField(
        default=True, verbose_name=_("Tasdiqlangan")
    )
    helpful_count = models.PositiveIntegerField(
        default=0, verbose_name=_("Foydali")
    )

    class Meta:
        unique_together = ('course', 'student')
        ordering = ['-created_at']
        verbose_name = _("Kurs sharhi")
        verbose_name_plural = _("Kurs sharhlari")

    def __str__(self):
        return f"{self.course.title} - {self.rating}⭐"

    @property
    def stars_display(self) -> str:
        """Yulduzlar."""
        return "⭐" * self.rating


# ═══════════════════════════════════════════════════════════════
# 16. KURS SERTIFIKATI
# ═══════════════════════════════════════════════════════════════

class Certificate(TimeStampedModel):
    """Kurs sertifikati."""

    enrollment = models.OneToOneField(
        Enrollment, on_delete=models.CASCADE,
        related_name='certificate',
        verbose_name=_("Yozilish")
    )
    certificate_number = models.CharField(
        max_length=50, unique=True, verbose_name=_("Sertifikat raqami")
    )
    issued_date = models.DateField(
        default=timezone.now, verbose_name=_("Berilgan sana")
    )
    expiry_date = models.DateField(
        null=True, blank=True, verbose_name=_("Amal qilish muddati")
    )
    file = models.FileField(
        upload_to=certificate_path,
        blank=True, null=True,
        verbose_name=_("PDF fayl")
    )
    grade = models.CharField(
        max_length=5, blank=True, verbose_name=_("Baho")
    )
    score = models.PositiveIntegerField(
        default=0, verbose_name=_("Ball")
    )
    verification_code = models.CharField(
        max_length=50, unique=True, blank=True,
        verbose_name=_("Tekshirish kodi")
    )
    is_verified = models.BooleanField(
        default=True, verbose_name=_("Tasdiqlangan")
    )

    class Meta:
        verbose_name = _("Sertifikat")
        verbose_name_plural = _("Sertifikatlar")
        ordering = ['-issued_date']

    def __str__(self):
        return f"{self.certificate_number} · {self.enrollment.student.user.get_full_name()}"

    def save(self, *args, **kwargs):
        if not self.certificate_number:
            year = timezone.now().year
            unique = uuid.uuid4().hex[:6].upper()
            self.certificate_number = f"DIGION-{year}-{unique}"
        if not self.verification_code:
            self.verification_code = uuid.uuid4().hex[:12].upper()
        super().save(*args, **kwargs)

    def verify(self):
        """Sertifikatni tekshirish."""
        return {
            'valid': self.is_verified,
            'number': self.certificate_number,
            'student': self.enrollment.student.user.get_full_name(),
            'course': self.enrollment.course.title,
            'issued': self.issued_date,
        }


# ═══════════════════════════════════════════════════════════════
# 17. KURS MODULI (Bonus)
# ═══════════════════════════════════════════════════════════════

class CourseModule(TimeStampedModel):
    """Kurs moduli — guruhlar uchun."""

    course = models.ForeignKey(
        Course, on_delete=models.CASCADE,
        related_name='modules',
        verbose_name=_("Kurs")
    )
    title = models.CharField(max_length=200, verbose_name=_("Nomi"))
    description = models.TextField(blank=True, verbose_name=_("Tavsif"))
    order = models.PositiveIntegerField(default=0, verbose_name=_("Tartib"))
    is_published = models.BooleanField(default=True, verbose_name=_("E’lon qilingan"))

    class Meta:
        ordering = ['order']
        unique_together = ('course', 'order')
        verbose_name = _("Kurs moduli")
        verbose_name_plural = _("Kurs modullari")

    def __str__(self):
        return f"{self.course.title} · {self.title}"


# ═══════════════════════════════════════════════════════════════
# 18. KURS FAQ (Savol-javob)
# ═══════════════════════════════════════════════════════════════

class CourseFAQ(TimeStampedModel):
    """Kurs bo‘yicha tez-tez so‘raladigan savollar."""

    course = models.ForeignKey(
        Course, on_delete=models.CASCADE,
        related_name='faqs',
        verbose_name=_("Kurs")
    )
    question = models.CharField(max_length=500, verbose_name=_("Savol"))
    answer = models.TextField(verbose_name=_("Javob"))
    order = models.PositiveIntegerField(default=0, verbose_name=_("Tartib"))
    is_active = models.BooleanField(default=True, verbose_name=_("Aktiv"))
    views_count = models.PositiveIntegerField(default=0, verbose_name=_("Ko‘rishlar"))

    class Meta:
        ordering = ['order']
        verbose_name = _("Kurs savoli")
        verbose_name_plural = _("Kurs savollari")

    def __str__(self):
        return self.question


# ═══════════════════════════════════════════════════════════════
# 19. KURS E’LONI (Announcement)
# ═══════════════════════════════════════════════════════════════

class CourseAnnouncement(TimeStampedModel):
    """Kurs e’loni."""

    course = models.ForeignKey(
        Course, on_delete=models.CASCADE,
        related_name='announcements',
        verbose_name=_("Kurs")
    )
    group = models.ForeignKey(
        'user.StudentGroup', on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='announcements',
        verbose_name=_("Guruh")
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='course_announcements',
        verbose_name=_("Muallif")
    )
    title = models.CharField(max_length=255, verbose_name=_("Sarlavha"))
    content = models.TextField(verbose_name=_("Kontent"))
    is_pinned = models.BooleanField(default=False, verbose_name=_("Qadalgan"))
    is_published = models.BooleanField(default=True, verbose_name=_("E’lon qilingan"))
    publish_at = models.DateTimeField(
        default=timezone.now, verbose_name=_("E’lon vaqti")
    )
    expires_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Tugash vaqti")
    )

    class Meta:
        ordering = ['-is_pinned', '-publish_at']
        verbose_name = _("Kurs e’loni")
        verbose_name_plural = _("Kurs e’lonlari")

    def __str__(self):
        return self.title


# ═══════════════════════════════════════════════════════════════
# 20. KURS FAYLI (Resource)
# ═══════════════════════════════════════════════════════════════

class CourseResource(TimeStampedModel):
    """Kurs qo‘shimcha materiallari."""

    RESOURCE_TYPES = (
        ('pdf', 'PDF'),
        ('doc', 'Hujjat'),
        ('slide', 'Taqdimot'),
        ('code', 'Kod'),
        ('link', 'Havola'),
        ('book', 'Kitob'),
        ('video', 'Video'),
        ('audio', 'Audio'),
        ('other', 'Boshqa'),
    )

    course = models.ForeignKey(
        Course, on_delete=models.CASCADE,
        related_name='resources',
        verbose_name=_("Kurs")
    )
    lesson = models.ForeignKey(
        Lesson, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='resources',
        verbose_name=_("Dars")
    )
    title = models.CharField(max_length=255, verbose_name=_("Sarlavha"))
    description = models.TextField(blank=True, verbose_name=_("Tavsif"))
    resource_type = models.CharField(
        max_length=20,
        choices=RESOURCE_TYPES,
        default='pdf',
        verbose_name=_("Turi")
    )
    file = models.FileField(
        upload_to='course_resources/',
        blank=True, null=True,
        validators=[validate_file_size],
        verbose_name=_("Fayl")
    )
    external_url = models.URLField(
        blank=True, null=True, verbose_name=_("Tashqi havola")
    )
    is_free = models.BooleanField(default=False, verbose_name=_("Bepul"))
    download_count = models.PositiveIntegerField(
        default=0, verbose_name=_("Yuklab olishlar")
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = _("Kurs resursi")
        verbose_name_plural = _("Kurs resurslari")

    def __str__(self):
        return self.title


# ═══════════════════════════════════════════════════════════════
# 21. DARS JURNALI (Lesson Log)
# ═══════════════════════════════════════════════════════════════

class LessonLog(TimeStampedModel):
    """Dars jurnali — o‘qituvchi tomonidan qayd etilgan."""

    lesson = models.ForeignKey(
        Lesson, on_delete=models.CASCADE,
        related_name='logs',
        verbose_name=_("Dars")
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='lesson_logs',
        verbose_name=_("O‘qituvchi")
    )
    lesson_date = models.DateField(default=timezone.now, verbose_name=_("Dars sanasi"))
    topics_covered = models.TextField(verbose_name=_("O‘tilgan mavzular"))
    notes = models.TextField(blank=True, verbose_name=_("Izohlar"))
    homework_given = models.BooleanField(default=False, verbose_name=_("Uyga vazifa berildi"))
    next_lesson_plan = models.TextField(
        blank=True, verbose_name=_("Keyingi dars rejasi")
    )
    is_approved = models.BooleanField(
        default=False, verbose_name=_("Tasdiqlangan")
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='approved_lesson_logs',
        verbose_name=_("Kim tasdiqladi")
    )
    approved_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Tasdiqlangan vaqt")
    )

    class Meta:
        ordering = ['-lesson_date']
        verbose_name = _("Dars jurnali")
        verbose_name_plural = _("Dars jurnallari")

    def __str__(self):
        return f"{self.lesson.title} · {self.lesson_date}"


# ═══════════════════════════════════════════════════════════════
# 22. AUDIT LOG
# ═══════════════════════════════════════════════════════════════

class AuditLog(TimeStampedModel):
    """Audit log — har bir o‘zgarishni kuzatish."""

    ACTION_CHOICES = (
        ('create', 'Yaratildi'),
        ('update', 'O‘zgartirildi'),
        ('delete', 'O‘chirildi'),
        ('view', 'Ko‘rildi'),
        ('grade', 'Baholandi'),
        ('send', 'Yuborildi'),
        ('approve', 'Tasdiqlandi'),
        ('reject', 'Rad etildi'),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True,
        related_name='audit_logs',
        verbose_name=_("Foydalanuvchi")
    )
    action = models.CharField(
        max_length=20, choices=ACTION_CHOICES,
        verbose_name=_("Harakat")
    )

    # Obyekt (Generic)
    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE,
        null=True, blank=True,
        verbose_name=_("Obyekt turi")
    )
    object_id = models.PositiveIntegerField(
        null=True, blank=True, verbose_name=_("Obyekt ID")
    )
    content_object = GenericForeignKey('content_type', 'object_id')

    description = models.TextField(blank=True, verbose_name=_("Tavsif"))
    changes = models.JSONField(
        default=dict, blank=True, verbose_name=_("O‘zgarishlar")
    )
    ip_address = models.GenericIPAddressField(
        null=True, blank=True, verbose_name=_("IP manzil")
    )
    user_agent = models.TextField(blank=True, verbose_name=_("Brauzer"))

    class Meta:
        ordering = ['-created_at']
        verbose_name = _("Audit log")
        verbose_name_plural = _("Audit loglar")
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['action', '-created_at']),
        ]

    def __str__(self):
        return f"{self.user} · {self.get_action_display()} · {self.created_at}"


# ═══════════════════════════════════════════════════════════════
# SIGNALLAR
# ═══════════════════════════════════════════════════════════════

@receiver(pre_save, sender=Course)
def course_pre_save(sender, instance, **kwargs):
    """Kurs saqlashdan oldin slug generatsiya."""
    if not instance.slug:
        instance.generate_slug()
    if instance.price == 0:
        instance.is_free = True



@receiver(post_save, sender=HomeworkSubmission)
def submission_post_save(sender, instance, created, **kwargs):
    """Topshiriq saqlanganda."""
    if created:
        # Homework statistikasini yangilash
        Homework.objects.filter(pk=instance.homework.pk).update(
            submissions_count=F('submissions_count') + 1
        )


@receiver(post_save, sender=QuizAttempt)
def quiz_attempt_post_save(sender, instance, created, **kwargs):
    """Test urinishi saqlanganda."""
    if created:
        Quiz.objects.filter(pk=instance.quiz.pk).update(
            attempts_count=F('attempts_count') + 1
        )


@receiver(post_save, sender=Enrollment)
def enrollment_post_save(sender, instance, created, **kwargs):
    """Kursga yozilganda."""
    if created:
        Course.objects.filter(pk=instance.course.pk).update(
            enrollment_count=F('enrollment_count') + 1
        )


@receiver(post_save, sender=Review)
def review_post_save(sender, instance, **kwargs):
    """Sharh saqlanganda kurs reytingini yangilash."""
    course = instance.course
    stats = course.reviews.aggregate(
        avg=Avg('rating'),
        count=Count('id'),
    )
    Course.objects.filter(pk=course.pk).update(
        rating=stats['avg'] or Decimal('0.00'),
        reviews_count=stats['count'],
    )


# ═══════════════════════════════════════════════════════════════
# EXPORTS
# ═══════════════════════════════════════════════════════════════

__all__ = [
    # Kurslar
    'CourseCategory', 'Tag', 'Course',
    'CourseLanguage', 'CourseLevel', 'CourseStatus',
    'CourseManager', 'CourseQuerySet',

    # Oylar va darslar
    'CourseMonth', 'Lesson',
    'LessonDay', 'LessonType', 'LessonStatus',
    'LessonQuerySet',

    # Uyga vazifalar
    'Homework', 'HomeworkSubmission',
    'HomeworkType', 'SubmissionStatus',
    'HomeworkQuerySet',

    # Testlar
    'Quiz', 'Question', 'AnswerOption',
    'QuizAttempt', 'AttemptAnswer',
    'QuizDifficulty', 'QuestionType', 'AttemptStatus',
    'TestQuerySet',

    # Guruhlar
    'StudentGroup', 'GroupMember',
    'GroupStatus',

    # Yozilish
    'Enrollment', 'Attendance',
    'EnrollmentStatus', 'AttendanceStatus',

    # Qo‘shimcha
    'Review', 'Certificate',
    'CourseModule', 'CourseFAQ', 'CourseAnnouncement',
    'CourseResource', 'LessonLog', 'AuditLog',

    # Abstract
    'TimeStampedModel', 'SoftDeleteModel', 'SEOModel',
]
# ═══════════════════════════════════════════════════════════════
# COURSE LIST PAGE SETTINGS (singleton)
# ═══════════════════════════════════════════════════════════════
class CourseListPageSettings(TimeStampedModel):
    """Kurslar ro'yxati sahifasi uchun TO'LIQ UI matnlar."""

    # ═══ SAHIFA HEADER ═══
    page_title = models.CharField(max_length=100, default="Kurslar")
    page_subtitle = models.CharField(
        max_length=250,
        default="Barcha kurslarni boshqaring — oylar, darslar, uyga vazifalar va testlar",
    )
    page_icon = models.CharField(max_length=50, default="bi-book-fill")
    page_badge_text = models.CharField(max_length=40, default="Kurslar boshqaruvi")
    page_badge_icon = models.CharField(max_length=50, default="bi-collection-fill")

    # ═══ ASOSIY TUGMALAR ═══
    btn_create = models.CharField(max_length=60, default="Yangi kurs")
    btn_create_icon = models.CharField(max_length=50, default="bi-plus-lg")
    btn_create_tooltip = models.CharField(max_length=100, default="Yangi kurs yaratish (Ctrl+N)")
    btn_help = models.CharField(max_length=60, default="Yordam")
    btn_help_icon = models.CharField(max_length=50, default="bi-question-circle")
    btn_refresh = models.CharField(max_length=40, default="Yangilash")
    btn_refresh_icon = models.CharField(max_length=50, default="bi-arrow-clockwise")
    btn_export = models.CharField(max_length=40, default="Eksport")
    btn_export_icon = models.CharField(max_length=50, default="bi-download")

    # ═══ STATISTIKA KARTALARI ═══
    stat_total_label = models.CharField(max_length=40, default="Jami kurslar")
    stat_total_icon = models.CharField(max_length=50, default="bi-collection-fill")
    stat_total_hint = models.CharField(max_length=80, default="Barcha kurslar soni")

    stat_published_label = models.CharField(max_length=40, default="Faol")
    stat_published_icon = models.CharField(max_length=50, default="bi-check-circle-fill")
    stat_published_hint = models.CharField(max_length=80, default="E'lon qilingan kurslar")

    stat_draft_label = models.CharField(max_length=40, default="Qoralama")
    stat_draft_icon = models.CharField(max_length=50, default="bi-file-earmark-fill")
    stat_draft_hint = models.CharField(max_length=80, default="Tayyorlanayotgan kurslar")

    stat_pending_label = models.CharField(max_length=40, default="Tasdiqlash")
    stat_pending_icon = models.CharField(max_length=50, default="bi-hourglass-split")
    stat_pending_hint = models.CharField(max_length=80, default="Tasdiqlash kutilmoqda")

    stat_archived_label = models.CharField(max_length=40, default="Arxiv")
    stat_archived_icon = models.CharField(max_length=50, default="bi-archive-fill")
    stat_archived_hint = models.CharField(max_length=80, default="Arxivlangan kurslar")

    stat_featured_label = models.CharField(max_length=40, default="Tanlangan")
    stat_featured_icon = models.CharField(max_length=50, default="bi-star-fill")
    stat_featured_hint = models.CharField(max_length=80, default="Tanlangan kurslar")

    stat_students_label = models.CharField(max_length=40, default="Talabalar")
    stat_students_icon = models.CharField(max_length=50, default="bi-people-fill")
    stat_students_hint = models.CharField(max_length=80, default="Faol talabalar")

    stat_lessons_label = models.CharField(max_length=40, default="Darslar")
    stat_lessons_icon = models.CharField(max_length=50, default="bi-journal-text")
    stat_lessons_hint = models.CharField(max_length=80, default="Barcha darslar")

    stat_months_label = models.CharField(max_length=40, default="Oylar")
    stat_months_icon = models.CharField(max_length=50, default="bi-calendar-month")
    stat_months_hint = models.CharField(max_length=80, default="Barcha oylar")

    stat_avg_rating_label = models.CharField(max_length=40, default="Reyting")
    stat_avg_rating_icon = models.CharField(max_length=50, default="bi-star-half")
    stat_avg_rating_hint = models.CharField(max_length=80, default="O'rtacha reyting")

    # ═══ QIDIRUV ═══
    filter_search_label = models.CharField(max_length=60, default="Qidirish")
    filter_search_placeholder = models.CharField(
        max_length=120, default="Kurs nomi, tavsifi yoki o'qituvchi..."
    )
    filter_search_icon = models.CharField(max_length=50, default="bi-search")
    filter_search_hint = models.CharField(
        max_length=120, default="Kamida 2 ta belgi kiriting"
    )

    # ═══ FILTRLAR ═══
    filter_btn_label = models.CharField(max_length=40, default="Filtrlar")
    filter_btn_icon = models.CharField(max_length=50, default="bi-funnel-fill")
    filter_btn_active_badge = models.CharField(max_length=20, default="faol")

    filter_category_label = models.CharField(max_length=60, default="Kategoriya")
    filter_category_all = models.CharField(max_length=60, default="Barcha kategoriyalar")

    filter_level_label = models.CharField(max_length=60, default="Daraja")
    filter_level_all = models.CharField(max_length=60, default="Barcha darajalar")

    filter_language_label = models.CharField(max_length=60, default="Til")
    filter_language_all = models.CharField(max_length=60, default="Barcha tillar")

    filter_status_label = models.CharField(max_length=60, default="Holat")
    filter_status_all = models.CharField(max_length=60, default="Barcha holatlar")

    filter_price_label = models.CharField(max_length=60, default="Narx")
    filter_price_all = models.CharField(max_length=60, default="Barcha narxlar")
    filter_price_free = models.CharField(max_length=60, default="Bepul")
    filter_price_paid = models.CharField(max_length=60, default="Pullik")

    filter_date_label = models.CharField(max_length=60, default="Sana")
    filter_date_all = models.CharField(max_length=60, default="Barcha vaqt")
    filter_date_today = models.CharField(max_length=60, default="Bugun")
    filter_date_week = models.CharField(max_length=60, default="Bu hafta")
    filter_date_month = models.CharField(max_length=60, default="Bu oy")

    filter_sort_label = models.CharField(max_length=60, default="Saralash")
    filter_sort_newest = models.CharField(max_length=60, default="Eng yangi")
    filter_sort_oldest = models.CharField(max_length=60, default="Eng eski")
    filter_sort_title_az = models.CharField(max_length=60, default="Nomi (A-Z)")
    filter_sort_title_za = models.CharField(max_length=60, default="Nomi (Z-A)")
    filter_sort_popular = models.CharField(max_length=60, default="Mashhur")
    filter_sort_rating = models.CharField(max_length=60, default="Reyting")

    btn_search = models.CharField(max_length=40, default="Qidirish")
    btn_search_icon = models.CharField(max_length=50, default="bi-search")
    btn_clear = models.CharField(max_length=40, default="Tozalash")
    btn_clear_icon = models.CharField(max_length=50, default="bi-x-lg")
    btn_apply = models.CharField(max_length=40, default="Qo'llash")
    btn_apply_icon = models.CharField(max_length=50, default="bi-check-lg")
    btn_reset = models.CharField(max_length=40, default="Reset")
    btn_reset_icon = models.CharField(max_length=50, default="bi-arrow-counterclockwise")

    active_filters_label = models.CharField(max_length=60, default="Faol filtrlar")
    active_filters_clear = models.CharField(max_length=60, default="Hammasini tozalash")

    # ═══ KO'RINISH ═══
    view_grid = models.CharField(max_length=40, default="Grid")
    view_grid_icon = models.CharField(max_length=50, default="bi-grid-3x3-gap-fill")
    view_list = models.CharField(max_length=40, default="List")
    view_list_icon = models.CharField(max_length=50, default="bi-list-ul")
    view_compact = models.CharField(max_length=40, default="Jadval")
    view_compact_icon = models.CharField(max_length=50, default="bi-list")
    view_switch_label = models.CharField(max_length=40, default="Ko'rinish")

    # ═══ BULK ═══
    bulk_label = models.CharField(max_length=60, default="ta tanlandi")
    bulk_select_all = models.CharField(max_length=60, default="Hammasini tanlash")
    bulk_publish = models.CharField(max_length=60, default="E'lon qilish")
    bulk_publish_icon = models.CharField(max_length=50, default="bi-rocket-takeoff")
    bulk_unpublish = models.CharField(max_length=60, default="E'londan olish")
    bulk_unpublish_icon = models.CharField(max_length=50, default="bi-eye-slash")
    bulk_feature = models.CharField(max_length=60, default="Tanlash")
    bulk_feature_icon = models.CharField(max_length=50, default="bi-star-fill")
    bulk_unfeature = models.CharField(max_length=60, default="Tanlovdan olish")
    bulk_unfeature_icon = models.CharField(max_length=50, default="bi-star")
    bulk_archive = models.CharField(max_length=60, default="Arxivlash")
    bulk_archive_icon = models.CharField(max_length=50, default="bi-archive")
    bulk_delete = models.CharField(max_length=60, default="O'chirish")
    bulk_delete_icon = models.CharField(max_length=50, default="bi-trash")
    bulk_cancel = models.CharField(max_length=60, default="Bekor qilish")
    bulk_cancel_icon = models.CharField(max_length=50, default="bi-x-lg")
    bulk_confirm_text = models.CharField(
        max_length=200, default="{count} ta kursni {action} qilasizmi?"
    )

    # ═══ BADGE ═══
    badge_published = models.CharField(max_length=40, default="Faol")
    badge_draft = models.CharField(max_length=40, default="Qoralama")
    badge_pending = models.CharField(max_length=40, default="Tasdiqlash")
    badge_archived = models.CharField(max_length=40, default="Arxiv")
    badge_featured = models.CharField(max_length=40, default="⭐")
    badge_free = models.CharField(max_length=40, default="BEPUL")
    badge_paid = models.CharField(max_length=40, default="Pullik")
    badge_new = models.CharField(max_length=40, default="Yangi")
    badge_hot = models.CharField(max_length=40, default="🔥 Mashhur")

    badge_new_days = models.PositiveSmallIntegerField(
        default=7, verbose_name="Yangi deb belgilash (kun)"
    )
    badge_hot_threshold = models.PositiveSmallIntegerField(
        default=50, verbose_name="Mashhur chegara (talaba)"
    )

    # ═══ KARTA ═══
    card_teacher_icon = models.CharField(max_length=50, default="bi-person-circle")
    card_teacher_label = models.CharField(max_length=40, default="O'qituvchi")
    card_duration_label = models.CharField(max_length=40, default="Davomiylik")
    card_duration_suffix = models.CharField(max_length=40, default="oy")
    card_level_label = models.CharField(max_length=40, default="Daraja")
    card_lang_label = models.CharField(max_length=40, default="Til")
    card_tag_icon = models.CharField(max_length=50, default="bi-tag-fill")
    card_price_label = models.CharField(max_length=40, default="Narx")
    card_no_teacher = models.CharField(max_length=60, default="Belgilanmagan")
    card_no_description = models.CharField(
        max_length=120, default="Tavsif kiritilmagan"
    )
    card_no_cover = models.CharField(max_length=40, default="Muqova yo'q")
    card_view_btn = models.CharField(max_length=40, default="Ko'rish")
    card_view_icon = models.CharField(max_length=50, default="bi-eye-fill")
    card_edit_btn = models.CharField(max_length=40, default="Tahrirlash")
    card_edit_icon = models.CharField(max_length=50, default="bi-pencil-square")
    card_delete_btn = models.CharField(max_length=40, default="O'chirish")
    card_delete_icon = models.CharField(max_length=50, default="bi-trash-fill")
    card_more_btn = models.CharField(max_length=40, default="Ko'proq")
    card_more_icon = models.CharField(max_length=50, default="bi-three-dots")

    card_dropdown_view = models.CharField(max_length=60, default="Batafsil ko'rish")
    card_dropdown_edit = models.CharField(max_length=60, default="Tahrirlash")
    card_dropdown_duplicate = models.CharField(max_length=60, default="Nusxa olish")
    card_dropdown_duplicate_icon = models.CharField(max_length=50, default="bi-files")
    card_dropdown_publish = models.CharField(max_length=60, default="E'lon qilish")
    card_dropdown_unpublish = models.CharField(max_length=60, default="E'londan olish")
    card_dropdown_feature = models.CharField(max_length=60, default="Tanlash")
    card_dropdown_unfeature = models.CharField(max_length=60, default="Tanlovdan olish")
    card_dropdown_archive = models.CharField(max_length=60, default="Arxivlash")
    card_dropdown_delete = models.CharField(max_length=60, default="O'chirish")

    # ═══ STATS USTUN ═══
    card_stat_months_icon = models.CharField(max_length=50, default="bi-calendar-month")
    card_stat_lessons_icon = models.CharField(max_length=50, default="bi-journal-text")
    card_stat_students_icon = models.CharField(max_length=50, default="bi-people-fill")

    # ═══ JADVAL USTUNLARI (compact) ═══
    table_col_select = models.CharField(max_length=40, default="#")
    table_col_cover = models.CharField(max_length=40, default="Rasm")
    table_col_title = models.CharField(max_length=40, default="Kurs nomi")
    table_col_category = models.CharField(max_length=40, default="Kategoriya")
    table_col_teacher = models.CharField(max_length=40, default="O'qituvchi")
    table_col_level = models.CharField(max_length=40, default="Daraja")
    table_col_months = models.CharField(max_length=40, default="Oylar")
    table_col_lessons = models.CharField(max_length=40, default="Darslar")
    table_col_students = models.CharField(max_length=40, default="Talabalar")
    table_col_rating = models.CharField(max_length=40, default="Reyting")
    table_col_status = models.CharField(max_length=40, default="Holat")
    table_col_actions = models.CharField(max_length=40, default="Amallar")

    # ═══ BO'SH HOLAT ═══
    empty_title = models.CharField(max_length=120, default="Kurslar yo'q")
    empty_subtitle = models.CharField(
        max_length=250, default="Birinchi kursni yarating va oylar bilan boshlang"
    )
    empty_icon = models.CharField(max_length=50, default="bi-book")
    empty_cta = models.CharField(max_length=60, default="Yangi kurs yaratish")
    empty_cta_icon = models.CharField(max_length=50, default="bi-plus-lg")

    empty_search_title = models.CharField(max_length=120, default="Hech narsa topilmadi")
    empty_search_subtitle = models.CharField(
        max_length=250, default="Qidiruv shartlarini o'zgartirib ko'ring"
    )
    empty_search_icon = models.CharField(max_length=50, default="bi-search")
    empty_search_cta = models.CharField(max_length=60, default="Filtrlarni tozalash")

    empty_filtered_title = models.CharField(max_length=120, default="Kurs topilmadi")
    empty_filtered_subtitle = models.CharField(
        max_length=250, default="Filtr shartlariga mos kurs yo'q"
    )

    # ═══ PAGINATION ═══
    pagination_prev_icon = models.CharField(max_length=50, default="bi-chevron-left")
    pagination_next_icon = models.CharField(max_length=50, default="bi-chevron-right")
    pagination_first_icon = models.CharField(max_length=50, default="bi-chevron-double-left")
    pagination_last_icon = models.CharField(max_length=50, default="bi-chevron-double-right")
    pagination_info = models.CharField(
        max_length=80, default="{start}-{end} / {total} ko'rsatildi"
    )
    pagination_per_page = models.CharField(max_length=60, default="Har sahifada")
    pagination_per_page_options = models.CharField(
        max_length=60, default="12,24,48,96",
        help_text="Vergul bilan: 12,24,48,96"
    )

    # ═══ XABARLAR ═══
    msg_deleted = models.CharField(max_length=200, default="Kurs muvaffaqiyatli o'chirildi")
    msg_published = models.CharField(max_length=200, default="Kurs e'lon qilindi")
    msg_unpublish = models.CharField(max_length=200, default="Kurs e'londan olindi")
    msg_featured = models.CharField(max_length=200, default="Kurs tanlandi")
    msg_unfeatured = models.CharField(max_length=200, default="Kurs tanlovdan olindi")
    msg_archived = models.CharField(max_length=200, default="Kurs arxivlandi")
    msg_duplicated = models.CharField(max_length=200, default="Kurs nusxalandi")
    msg_error = models.CharField(max_length=200, default="Xatolik yuz berdi")
    msg_network_error = models.CharField(
        max_length=200, default="Tarmoq xatosi. Qayta urinib ko'ring."
    )
    msg_loading = models.CharField(max_length=60, default="Yuklanmoqda...")
    msg_confirm_delete = models.CharField(
        max_length=250, default="Bu kursni o'chirmoqchimisiz?"
    )
    msg_confirm_delete_extra = models.CharField(
        max_length=250, default="Bu amalni qaytarib bo'lmaydi!"
    )
    msg_confirm_bulk_delete = models.CharField(
        max_length=250, default="Tanlangan kurslarni o'chirmoqchimisiz?"
    )
    msg_no_selection = models.CharField(
        max_length=120, default="Hech narsa tanlanmagan"
    )
    msg_duplicate_suffix = models.CharField(max_length=60, default="(nusxa)")

    # ═══ TOOLTIP ═══
    tooltip_view = models.CharField(max_length=60, default="Ko'rish")
    tooltip_edit = models.CharField(max_length=60, default="Tahrirlash")
    tooltip_delete = models.CharField(max_length=60, default="O'chirish")
    tooltip_publish = models.CharField(max_length=60, default="E'lon qilish")
    tooltip_unpublish = models.CharField(max_length=60, default="E'londan olish")
    tooltip_feature = models.CharField(max_length=60, default="Tanlash")
    tooltip_unfeature = models.CharField(max_length=60, default="Tanlovdan olish")
    tooltip_duplicate = models.CharField(max_length=60, default="Nusxa olish")
    tooltip_more = models.CharField(max_length=60, default="Qo'shimcha amallar")

    # ═══ KEYBOARD ═══
    keyboard_hint_title = models.CharField(
        max_length=80, default="Klaviatura yorliqlari"
    )
    keyboard_hint_new = models.CharField(
        max_length=80, default="Yangi kurs (Ctrl+N)"
    )
    keyboard_hint_select = models.CharField(
        max_length=80, default="Hammasini tanlash (Ctrl+A)"
    )
    keyboard_hint_clear = models.CharField(
        max_length=80, default="Bekor qilish (Esc)"
    )
    keyboard_hint_search = models.CharField(
        max_length=80, default="Qidirish (Ctrl+K)"
    )

    class Meta:
        verbose_name = "Kurslar ro'yxati sozlamalari"
        verbose_name_plural = "Kurslar ro'yxati sozlamalari"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Kurslar ro'yxati sozlamalari"

# ═══════════════════════════════════════════════════════════════
# COURSE FORM PAGE SETTINGS (singleton)
# ═══════════════════════════════════════════════════════════════

class CourseFormPageSettings(TimeStampedModel):
    """Kurs yaratish/tahrirlash sahifasi uchun TO'LIQ UI matnlar."""

    # ═══ HEADER ═══
    page_badge_create = models.CharField(max_length=60, default="Yangi kurs")
    page_badge_edit = models.CharField(max_length=60, default="Tahrirlash")
    page_badge_icon = models.CharField(max_length=50, default="bi-book-half")

    page_title_create = models.CharField(max_length=120, default="Yangi kurs yaratish")
    page_title_edit = models.CharField(max_length=120, default="Kursni tahrirlash")
    page_icon = models.CharField(max_length=50, default="bi-plus-circle-fill")

    page_subtitle_create = models.CharField(
        max_length=250, default="Kurs ma’lumotlarini to‘ldiring va saqlang"
    )
    page_subtitle_edit = models.CharField(
        max_length=250, default="Kurs ma’lumotlarini yangilang"
    )

    # ═══ ASOSIY TUGMALAR ═══
    btn_save = models.CharField(max_length=60, default="Saqlash")
    btn_save_icon = models.CharField(max_length=50, default="bi-check-lg")
    btn_save_and_new = models.CharField(max_length=60, default="Saqlash va yangi")
    btn_save_and_new_icon = models.CharField(max_length=50, default="bi-plus-lg")
    btn_cancel = models.CharField(max_length=60, default="Bekor qilish")
    btn_cancel_icon = models.CharField(max_length=50, default="bi-x-lg")
    btn_reset = models.CharField(max_length=60, default="Tiklash")
    btn_reset_icon = models.CharField(max_length=50, default="bi-arrow-counterclockwise")
    btn_preview = models.CharField(max_length=60, default="Ko‘rish")
    btn_preview_icon = models.CharField(max_length=50, default="bi-eye")
    btn_back = models.CharField(max_length=60, default="Orqaga")
    btn_back_icon = models.CharField(max_length=50, default="bi-arrow-left")

    # ═══ BO'LIMLAR ═══
    sec_basic_title = models.CharField(max_length=80, default="Asosiy ma’lumotlar")
    sec_basic_subtitle = models.CharField(
        max_length=200, default="Kurs nomi va tavsifi"
    )
    sec_basic_icon = models.CharField(max_length=50, default="bi-info-circle-fill")

    sec_media_title = models.CharField(max_length=80, default="Muqova va media")
    sec_media_subtitle = models.CharField(
        max_length=200, default="Kurs muqovasi va taqdimot videosi"
    )
    sec_media_icon = models.CharField(max_length=50, default="bi-image-fill")

    sec_teacher_title = models.CharField(max_length=80, default="O‘qituvchi va kategoriya")
    sec_teacher_subtitle = models.CharField(
        max_length=200, default="Kurs egasi va turkum"
    )
    sec_teacher_icon = models.CharField(max_length=50, default="bi-person-badge-fill")

    sec_dates_title = models.CharField(max_length=80, default="Sanalar va davomiylik")
    sec_dates_subtitle = models.CharField(
        max_length=200, default="Kurs qachon boshlanadi va tugaydi"
    )
    sec_dates_icon = models.CharField(max_length=50, default="bi-calendar-range-fill")

    sec_settings_title = models.CharField(max_length=80, default="Kurs sozlamalari")
    sec_settings_subtitle = models.CharField(
        max_length=200, default="Til, daraja, holat va boshqalar"
    )
    sec_settings_icon = models.CharField(max_length=50, default="bi-sliders")

    sec_price_title = models.CharField(max_length=80, default="Narx va to‘lov")
    sec_price_subtitle = models.CharField(
        max_length=200, default="Kurs narxi va chegirma"
    )
    sec_price_icon = models.CharField(max_length=50, default="bi-cash-coin")

    sec_advanced_title = models.CharField(max_length=80, default="Qo‘shimcha sozlamalar")
    sec_advanced_subtitle = models.CharField(
        max_length=200, default="Talabalar limiti, sertifikat va boshqalar"
    )
    sec_advanced_icon = models.CharField(max_length=50, default="bi-gear-fill")

    sec_seo_title = models.CharField(max_length=80, default="SEO sozlamalari")
    sec_seo_subtitle = models.CharField(
        max_length=200, default="Qidiruv tizimlari uchun meta ma’lumotlar"
    )
    sec_seo_icon = models.CharField(max_length=50, default="bi-search-heart")

    # ═══ MAYDON BELGILARI ═══
    field_title = models.CharField(max_length=60, default="Kurs nomi")
    field_title_hint = models.CharField(
        max_length=200, default="2-255 belgi. Qisqa va tushunarli bo‘lsin"
    )
    field_title_placeholder = models.CharField(
        max_length=120, default="Masalan: Ona tili grammatikasi — 9 oy"
    )

    field_slug = models.CharField(max_length=60, default="Slug (URL)")
    field_slug_hint = models.CharField(
        max_length=200, default="Bo‘sh qoldirsangiz avtomatik yaratiladi"
    )
    field_slug_placeholder = models.CharField(
        max_length=120, default="ona-tili-grammatikasi"
    )
    btn_generate_slug = models.CharField(max_length=60, default="Yaratish")
    btn_generate_slug_icon = models.CharField(max_length=50, default="bi-arrow-repeat")

    field_short_description = models.CharField(max_length=60, default="Qisqa tavsif")
    field_short_description_hint = models.CharField(
        max_length=200, default="Karta va ro‘yxatda ko‘rinadi (max 300 belgi)"
    )
    field_short_description_placeholder = models.CharField(
        max_length=200, default="Bu kursda nima o‘rganasiz?"
    )

    field_description = models.CharField(max_length=60, default="Batafsil tavsif")
    field_description_hint = models.CharField(
        max_length=200, default="Markdown yoki HTML qo‘llab-quvvatlanadi"
    )
    field_description_placeholder = models.CharField(
        max_length=200, default="Kurs haqida batafsil ma’lumot..."
    )

    field_cover = models.CharField(max_length=60, default="Muqova rasmi")
    field_cover_hint = models.CharField(
        max_length=200, default="JPG, PNG, WEBP · Max 5 MB · Tavsiya: 1200x600"
    )
    field_cover_placeholder = models.CharField(max_length=60, default="Rasm yuklash")
    btn_cover_upload = models.CharField(max_length=60, default="Rasm yuklash")
    btn_cover_upload_icon = models.CharField(max_length=50, default="bi-upload")
    btn_cover_remove = models.CharField(max_length=60, default="O‘chirish")
    btn_cover_remove_icon = models.CharField(max_length=50, default="bi-trash")

    field_promo_video = models.CharField(max_length=60, default="Taqdimot video (URL)")
    field_promo_video_placeholder = models.CharField(
        max_length=120, default="https://youtube.com/watch?v=..."
    )

    field_teacher = models.CharField(max_length=60, default="O‘qituvchi")
    field_teacher_hint = models.CharField(
        max_length=200, default="Kursni olib boradigan o‘qituvchi"
    )

    field_category = models.CharField(max_length=60, default="Kategoriya")
    field_category_hint = models.CharField(
        max_length=200, default="Kurs qaysi turkumga tegishli"
    )

    field_start_date = models.CharField(max_length=60, default="Boshlanish sanasi")
    field_end_date = models.CharField(max_length=60, default="Tugash sanasi")
    field_duration = models.CharField(max_length=60, default="Davomiyligi (oy)")
    field_duration_hint = models.CharField(
        max_length=200, default="1-36 oy oralig‘ida"
    )

    field_language = models.CharField(max_length=60, default="Til")
    field_level = models.CharField(max_length=60, default="Daraja")
    field_status = models.CharField(max_length=60, default="Holat")

    field_price = models.CharField(max_length=60, default="Narx (so‘m)")
    field_price_hint = models.CharField(
        max_length=200, default="0 kiritsangiz — kurs bepul bo‘ladi"
    )
    field_price_placeholder = models.CharField(max_length=60, default="0")

    field_discounted_price = models.CharField(
        max_length=60, default="Chegirmali narx (so‘m)"
    )
    field_discounted_price_hint = models.CharField(
        max_length=200, default="Bo‘sh qoldirsangiz chegirma yo‘q"
    )

    field_max_students = models.CharField(max_length=60, default="Maksimal talabalar")
    field_max_students_hint = models.CharField(
        max_length=200, default="0 = cheksiz"
    )

    field_passing_score = models.CharField(max_length=60, default="O‘tish bali (%)")
    field_attendance_required = models.CharField(
        max_length=60, default="Talab qilinadigan davomat (%)"
    )

    field_meta_title = models.CharField(max_length=60, default="SEO sarlavha")
    field_meta_title_placeholder = models.CharField(
        max_length=120, default="60 belgi atrofida"
    )
    field_meta_description = models.CharField(max_length=60, default="SEO tavsif")
    field_meta_description_placeholder = models.CharField(
        max_length=160, default="160 belgi atrofida"
    )
    field_meta_keywords = models.CharField(max_length=60, default="SEO kalit so‘zlar")
    field_meta_keywords_placeholder = models.CharField(
        max_length=160, default="kalit, so‘z, vergul, bilan"
    )

    # ═══ CHECKBOX LABELS ═══
    check_is_active = models.CharField(max_length=60, default="Faol")
    check_is_active_hint = models.CharField(
        max_length=200, default="Faol bo‘lmagan kurs saytda ko‘rinmaydi"
    )
    check_is_featured = models.CharField(max_length=60, default="Tanlangan")
    check_is_featured_hint = models.CharField(
        max_length=200, default="Tanlangan kurslar bosh sahifada ko‘rinadi"
    )
    check_is_certificate = models.CharField(max_length=60, default="Sertifikat beriladi")
    check_is_certificate_hint = models.CharField(
        max_length=200, default="Kursni tugatganlarga sertifikat beriladi"
    )

    # ═══ PREVIEW ═══
    preview_title = models.CharField(max_length=60, default="Ko‘rinish")
    preview_subtitle = models.CharField(max_length=120, default="Karta qanday ko‘rinadi")
    preview_no_cover = models.CharField(max_length=60, default="Muqova yo‘q")
    preview_no_title = models.CharField(max_length=80, default="Kurs nomi kiritilmagan")
    preview_no_teacher = models.CharField(max_length=60, default="Belgilanmagan")
    preview_no_description = models.CharField(
        max_length=120, default="Tavsif kiritilmagan"
    )
    preview_free = models.CharField(max_length=60, default="BEPUL")
    preview_duration_suffix = models.CharField(max_length=40, default="oy")

    # ═══ XABARLAR ═══
    msg_saved_create = models.CharField(
        max_length=200, default="Kurs muvaffaqiyatli yaratildi!"
    )
    msg_saved_edit = models.CharField(
        max_length=200, default="Kurs ma’lumotlari yangilandi!"
    )
    msg_error = models.CharField(max_length=200, default="Xatolik yuz berdi")
    msg_network_error = models.CharField(
        max_length=200, default="Tarmoq xatosi. Qayta urinib ko‘ring."
    )
    msg_unsaved = models.CharField(
        max_length=200, default="Saqlanmagan o‘zgarishlar bor!"
    )
    msg_unsaved_confirm = models.CharField(
        max_length=250, default="Sahifadan chiqmoqchimisiz? O‘zgarishlar yo‘qoladi."
    )
    msg_slug_generated = models.CharField(max_length=120, default="Slug yaratildi")
    msg_char_limit = models.CharField(max_length=60, default="belgi")

    # ═══ VALIDATSIYA ═══
    err_title_required = models.CharField(
        max_length=120, default="Kurs nomi majburiy"
    )
    err_title_min = models.CharField(
        max_length=120, default="Kurs nomi kamida 3 belgi bo‘lishi kerak"
    )
    err_date_order = models.CharField(
        max_length=160, default="Tugash sanasi boshlanishdan keyin bo‘lishi kerak"
    )
    err_price_negative = models.CharField(
        max_length=120, default="Narx manfiy bo‘lishi mumkin emas"
    )
    err_discount_higher = models.CharField(
        max_length=160, default="Chegirmali narx asosiy narxdan katta bo‘lmasin"
    )

    # ═══ KEYBOARD HINT ═══
    keyboard_hint_title = models.CharField(
        max_length=80, default="Klaviatura yorliqlari"
    )
    keyboard_save = models.CharField(max_length=80, default="Saqlash (Ctrl+S)")
    keyboard_cancel = models.CharField(max_length=80, default="Bekor (Esc)")

    class Meta:
        verbose_name = "Kurs formasi sozlamalari"
        verbose_name_plural = "Kurs formasi sozlamalari"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Kurs formasi sozlamalari"


# ═══════════════════════════════════════════════════════════════
# GURUH DARSI — avtomatik taqsimlangan darslar
# ═══════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════
# GURUH DARSI — avtomatik taqsimlangan darslar
# ═══════════════════════════════════════════════════════════════

class GroupLesson(TimeStampedModel):
    """
    Guruhga biriktirilgan dars.
    Darslar avtomatik taqsimlanadi:
    - Toq kun guruhga: Du, Ch, Ju
    - Juft kun guruhga: Se, Pa, Sha
    """
    group = models.ForeignKey(
        'user.StudentGroup',
        on_delete=models.CASCADE,
        related_name='group_lessons',
        verbose_name=_("Guruh")
    )
    lesson = models.ForeignKey(
        Lesson, on_delete=models.CASCADE,
        related_name='group_assignments',
        verbose_name=_("Dars")
    )

    # ─── Avtomatik hisoblangan sana va tartib ───
    lesson_date = models.DateField(
        verbose_name=_("Dars sanasi"),
        null=True, blank=True
    )
    order_in_group = models.PositiveIntegerField(
        default=1, verbose_name=_("Guruhdagi tartib raqami")
    )

    # ─── Holat ───
    is_completed = models.BooleanField(
        default=False, verbose_name=_("O'tilgan")
    )
    is_sent = models.BooleanField(
        default=False, verbose_name=_("Yuborilgan")
    )
    sent_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Yuborilgan vaqt")
    )
    scheduled_task_id = models.CharField(
        max_length=100, blank=True, null=True,
        db_index=True,
        verbose_name=_("Rejalashtirilgan vazifa ID"),
    )

    # ⭐ YANGI: homework yuborilgan vaqt
    homework_sent_at = models.DateTimeField(
        null=True, blank=True,
        verbose_name=_("Uyga vazifa yuborilgan vaqt"),
    )
    homework_status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Qo‘lda yuborish kutilmoqda'),
            ('scheduled', 'Rejalashtirilgan'),
            ('sending', 'Yuborilmoqda'),
            ('sent', 'Yuborildi'),
            ('failed', 'Xatolik'),
            ('partial', 'Qismiy'),
            ('cancelled', 'Bekor qilindi'),
        ],
        default='pending',
        db_index=True,
    )
    homework_recipients_count = models.PositiveIntegerField(default=0)
    homework_failed_count = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('group', 'lesson')
        ordering = ['group', 'order_in_group']
        verbose_name = _("Guruh darsi")
        verbose_name_plural = _("Guruh darslari")
        indexes = [
            models.Index(fields=['group', 'lesson_date']),
        ]

    def __str__(self):
        return f"{self.group.name} · {self.lesson.lesson_number}-dars ({self.lesson_date})"

    def mark_sent(self):
        """Yuborilgan deb belgilash."""
        self.is_sent = True
        self.sent_at = timezone.now()
        self.save(update_fields=['is_sent', 'sent_at'])



# ═══════════════════════════════════════════════════════════════
# HOMEWORK DELIVERY LOG — uyga vazifa yuborish tarixi
# ═══════════════════════════════════════════════════════════════

class HomeworkDeliveryLog(TimeStampedModel):
    """
    Uyga vazifa yuborish tarixi.
    Har bir talaba uchun alohida yozuv — Telegram xabar holati.
    """
    STATUS_CHOICES = (
        ('pending', 'Kutilmoqda'),
        ('sent', 'Yuborildi'),
        ('failed', 'Xatolik'),
        ('skipped', 'O\'tkazib yuborildi'),
        ('read', 'O\'qildi'),
    )

    group_lesson = models.ForeignKey(
        GroupLesson, on_delete=models.CASCADE,
        related_name='delivery_logs',
        verbose_name=_("Guruh darsi"),
    )
    student = models.ForeignKey(
        'user.StudentProfile', on_delete=models.CASCADE,
        related_name='homework_delivery_logs',
        verbose_name=_("Talaba"),
    )
    homework = models.ForeignKey(
        Homework, on_delete=models.CASCADE,
        related_name='delivery_logs',
        verbose_name=_("Uyga vazifa"),
    )

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES,
        default='pending', db_index=True,
        verbose_name=_("Holat"),
    )
    error = models.TextField(
        blank=True, verbose_name=_("Xato matni"),
    )
    chat_id = models.BigIntegerField(
        null=True, blank=True,
        verbose_name=_("Telegram chat ID"),
    )
    sent_at = models.DateTimeField(
        null=True, blank=True,
        verbose_name=_("Yuborilgan vaqt"),
    )
    read_at = models.DateTimeField(
        null=True, blank=True,
        verbose_name=_("O'qilgan vaqt"),
    )

    class Meta:
        verbose_name = _("Uyga vazifa yuborish tarixi")
        verbose_name_plural = _("Uyga vazifa yuborish tarixi")
        ordering = ['-created_at']
        unique_together = ('group_lesson', 'student')
        indexes = [
            models.Index(fields=['group_lesson', 'status']),
            models.Index(fields=['student', '-created_at']),
        ]

    def __str__(self):
        return (
            f"{self.student.user.get_full_name()} — "
            f"{self.homework.title} ({self.get_status_display()})"
        )

    @property
    def is_sent(self):
        return self.status == 'sent'

    @property
    def is_failed(self):
        return self.status == 'failed'

    @property
    def is_skipped(self):
        return self.status == 'skipped'

    def mark_sent(self):
        self.status = 'sent'
        self.sent_at = timezone.now()
        self.save(update_fields=['status', 'sent_at'])

    def mark_failed(self, error=''):
        self.status = 'failed'
        self.error = error
        self.save(update_fields=['status', 'error'])

    def mark_read(self):
        self.status = 'read'
        self.read_at = timezone.now()
        self.save(update_fields=['status', 'read_at'])


# ═══════════════════════════════════════════════════════════════
# EXPORTS ga qo'shish (agar `__all__` ro'yxati bo'lsa)
# ═══════════════════════════════════════════════════════════════