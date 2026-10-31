"""
LearnCraft – Learning Management System Models
================================================
Professional, feature-rich, production-ready modellar to‘plami.

Muallif: LearnCraft jamoasi
Versiya: 2.0
Sana: 2025
"""

from __future__ import annotations

import os
import uuid
from decimal import Decimal
from datetime import timedelta
from typing import Optional, Any

from django.conf import settings
from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.exceptions import ValidationError
from django.core.validators import (
    RegexValidator, MinValueValidator, MaxValueValidator,
    FileExtensionValidator
)
from django.db import models, transaction
from django.db.models import (
    Count, Sum, Avg, Q, F, Case, When, Value,
    IntegerField, DecimalField, FloatField
)
from django.db.models.functions import Coalesce, TruncDate, TruncMonth
from django.db.models.signals import post_save, pre_save, post_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _


# ============================================================
# YORDAMCHI VALIDATORLAR VA FUNKSIYALAR
# ============================================================

phone_regex = RegexValidator(
    regex=r"^\+?998\d{9}$",
    message="Telefon raqami quyidagi formatda bo'lishi kerak: '+998901234567'."
)


def validate_file_size(value, max_mb: int = 5):
    """Fayl hajmini tekshirish (MB)."""
    limit = max_mb * 1024 * 1024
    if value.size > limit:
        raise ValidationError(f"Fayl hajmi {max_mb} MB dan oshmasligi kerak.")


def avatar_upload_path(instance, filename: str) -> str:
    """Avatar uchun unikal fayl yo‘li."""
    ext = filename.split('.')[-1]
    new_name = f"{uuid.uuid4().hex}.{ext}"
    return f"avatars/{instance.role}/{new_name}"


def task_file_upload_path(instance, filename: str) -> str:
    """Topshiriq fayli uchun unikal yo‘l."""
    ext = filename.split('.')[-1]
    new_name = f"{uuid.uuid4().hex}.{ext}"
    return f"tasks/{timezone.now().strftime('%Y/%m')}/{new_name}"


def submission_file_upload_path(instance, filename: str) -> str:
    """Topshirilgan fayl uchun unikal yo‘l."""
    ext = filename.split('.')[-1]
    new_name = f"{uuid.uuid4().hex}.{ext}"
    return f"submissions/{timezone.now().strftime('%Y/%m')}/{new_name}"


# ============================================================
# 1. CUSTOM QUERYSET VA MANAGERLAR
# ============================================================

class CustomUserQuerySet(models.QuerySet):
    """CustomUser uchun kengaytirilgan QuerySet."""

    def active(self):
        return self.filter(is_active=True)

    def inactive(self):
        return self.filter(is_active=False)

    def by_role(self, role: str):
        return self.filter(role=role)

    def admins(self):
        return self.filter(role='admin')

    def managers(self):
        return self.filter(role='manager')

    def teachers(self):
        return self.filter(role='teacher')

    def students(self):
        return self.filter(role='student')

    def parents(self):
        return self.filter(role='parent')

    def search(self, query: str):
        """Ism, familiya yoki telefon bo‘yicha qidirish."""
        return self.filter(
            Q(phone_number__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(middle_name__icontains=query)
        )

    def recent(self, days: int = 7):
        """Oxirgi N kun ichida qo‘shilganlar."""
        threshold = timezone.now() - timedelta(days=days)
        return self.filter(date_joined__gte=threshold)

    def with_stats(self):
        """Statistika bilan birga."""
        return self.annotate(
            total_notifications=Count('notifications', distinct=True),
            total_results=Count('student_profile__test_results', distinct=True),
        )


class CustomUserManager(BaseUserManager):
    """CustomUser uchun professional manager."""

    def get_queryset(self):
        return CustomUserQuerySet(self.model, using=self._db)

    def create_user(self, phone_number: str, password: Optional[str] = None, **extra_fields):
        if not phone_number:
            raise ValueError("Telefon raqamni kiritish shart!")

        extra_fields.setdefault('is_active', True)
        user = self.model(phone_number=phone_number, **extra_fields)

        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()

        user.save(using=self._db)
        return user

    def create_superuser(self, phone_number: str, password: Optional[str] = None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", 'admin')
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser is_staff=True bo‘lishi kerak.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser is_superuser=True bo‘lishi kerak.")

        return self.create_user(phone_number, password, **extra_fields)

    def active(self):
        return self.get_queryset().active()

    def by_role(self, role):
        return self.get_queryset().by_role(role)

    def students(self):
        return self.get_queryset().students()

    def teachers(self):
        return self.get_queryset().teachers()


class SoftDeleteQuerySet(models.QuerySet):
    """Soft Delete bilan ishlash uchun mixin."""

    def delete(self, hard: bool = False):
        if hard:
            return super().delete()
        return self.update(is_deleted=True, deleted_at=timezone.now())

    def restore(self):
        return self.update(is_deleted=False, deleted_at=None)

    def alive(self):
        return self.filter(is_deleted=False)

    def dead(self):
        return self.filter(is_deleted=True)


class SoftDeleteManager(models.Manager):
    """Soft delete manageri."""

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).filter(is_deleted=False)

    def all_with_deleted(self):
        return SoftDeleteQuerySet(self.model, using=self._db)


# ============================================================
# 2. ABSTRACT BASE MODELS
# ============================================================

class TimeStampedModel(models.Model):
    """Yaratilgan va tahrirlangan vaqtni saqlovchi abstrakt model."""
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Yaratilgan")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Tahrirlangan")

    class Meta:
        abstract = True
        ordering = ['-created_at']


class SoftDeleteModel(models.Model):
    """Soft delete uchun abstrakt model."""
    is_deleted = models.BooleanField(default=False, verbose_name="O‘chirilgan")
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name="O‘chirilgan vaqt")

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def delete(self, hard: bool = False, **kwargs):
        if hard:
            return super().delete(**kwargs)
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=['is_deleted', 'deleted_at'])

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=['is_deleted', 'deleted_at'])


# ============================================================
# 3. REGISTRATION KEY
# ============================================================

class RegistrationKey(TimeStampedModel):
    """Ro‘yxatdan o‘tish uchun maxsus kalit."""

    key = models.CharField(max_length=150, unique=True, verbose_name="Maxsus kalit")
    is_active = models.BooleanField(default=True, verbose_name="Aktiv")
    usage_limit = models.PositiveIntegerField(default=1, verbose_name="Ishlatish limiti")
    used_count = models.PositiveIntegerField(default=0, verbose_name="Ishlatilgan")
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name="Muddati")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='created_keys',
        verbose_name="Kim yaratdi"
    )

    class Meta:
        verbose_name = "Ro‘yxatdan o‘tish kaliti"
        verbose_name_plural = "Ro‘yxatdan o‘tish kalitlari"
        ordering = ['-created_at']
        indexes = [models.Index(fields=['key', 'is_active'])]

    def __str__(self):
        return self.key

    @property
    def is_expired(self) -> bool:
        """Muddati o‘tganmi?"""
        if not self.expires_at:
            return False
        return timezone.now() > self.expires_at

    @property
    def is_exhausted(self) -> bool:
        """Limit tugaganmi?"""
        return self.used_count >= self.usage_limit

    @property
    def is_valid(self) -> bool:
        """Kalit ishlatish uchun yaroqlimi?"""
        return self.is_active and not self.is_expired and not self.is_exhausted

    def use(self) -> bool:
        """Kalitni ishlatish."""
        if not self.is_valid:
            return False
        self.used_count = F('used_count') + 1
        self.save(update_fields=['used_count'])
        return True


# ============================================================
# 4. CUSTOM USER
# ============================================================

ROLE_CHOICES = (
    ('admin', 'Admin'),
    ('manager', 'Manager'),
    ('teacher', 'Teacher'),
    ('student', 'Student'),
    ('parent', 'Parent'),
)


class CustomUser(AbstractBaseUser, PermissionsMixin):
    """
    Tizimning asosiy foydalanuvchi modeli.
    Telefon raqam orqali autentifikatsiya qilinadi.
    """

    phone_number = models.CharField(
        validators=[phone_regex], max_length=17, unique=True,
        verbose_name="Telefon raqam", db_index=True
    )
    first_name = models.CharField(max_length=150, blank=True, verbose_name="Ism")
    last_name = models.CharField(max_length=150, blank=True, verbose_name="Familiya")
    middle_name = models.CharField(max_length=50, blank=True, null=True, verbose_name="Sharif")
    avatar = models.ImageField(
        upload_to=avatar_upload_path, blank=True, null=True,
        validators=[validate_file_size],
        verbose_name="Profil rasmi"
    )
    role = models.CharField(
        max_length=10, choices=ROLE_CHOICES, default='student',
        verbose_name="Rol", db_index=True
    )
    is_active = models.BooleanField(default=True, verbose_name="Aktiv")
    is_staff = models.BooleanField(default=False, verbose_name="Xodim")
    date_joined = models.DateTimeField(auto_now_add=True, verbose_name="Ro‘yxatdan o‘tgan")

    # Qo‘shimcha maydonlar
    email = models.EmailField(blank=True, null=True, verbose_name="Email")
    last_login_ip = models.GenericIPAddressField(null=True, blank=True, verbose_name="Oxirgi IP")
    language = models.CharField(
        max_length=5, default='uz',
        choices=(('uz', 'O‘zbekcha'), ('ru', 'Русский'), ('en', 'English')),
        verbose_name="Til"
    )
    timezone = models.CharField(max_length=50, default='Asia/Tashkent', verbose_name="Vaqt zonasi")

    USERNAME_FIELD = 'phone_number'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    objects = CustomUserManager()

    class Meta:
        verbose_name = "Foydalanuvchi"
        verbose_name_plural = "Foydalanuvchilar"
        ordering = ['-date_joined']
        indexes = [
            models.Index(fields=['phone_number']),
            models.Index(fields=['role', 'is_active']),
        ]

    def __str__(self) -> str:
        return f"{self.get_full_name()} ({self.phone_number})"

    # ---------- Xususiyatlar (Properties) ----------

    @property
    def full_name(self) -> str:
        return self.get_full_name()

    @property
    def short_name(self) -> str:
        """Qisqa ism."""
        if self.first_name:
            return f"{self.first_name} {self.last_name[:1]}."
        return self.phone_number

    @property
    def initials(self) -> str:
        """Bosh harflar."""
        f = self.first_name[:1] if self.first_name else ''
        l = self.last_name[:1] if self.last_name else ''
        return f"{f}{l}".upper() or '?'

    @property
    def is_admin(self) -> bool:
        return self.role == 'admin'

    @property
    def is_manager(self) -> bool:
        return self.role == 'manager'

    @property
    def is_teacher(self) -> bool:
        return self.role == 'teacher'

    @property
    def is_student(self) -> bool:
        return self.role == 'student'

    @property
    def is_parent(self) -> bool:
        return self.role == 'parent'

    @property
    def is_online(self) -> bool:
        """Oxirgi 5 daqiqada aktiv bo‘lganmi?"""
        if not self.last_login:
            return False
        return (timezone.now() - self.last_login) < timedelta(minutes=5)

    @property
    def avatar_url(self) -> str:
        """Avatar URL yoki default."""
        if self.avatar:
            return self.avatar.url
        return f"https://ui-avatars.com/api/?name={self.initials}&background=4F46E5&color=fff"

    # ---------- Metodlar ----------

    def get_full_name(self) -> str:
        parts = [self.last_name, self.first_name, self.middle_name]
        return ' '.join(p for p in parts if p).strip() or self.phone_number

    def get_short_name(self) -> str:
        return self.first_name or self.phone_number

    def get_absolute_url(self) -> str:
        return reverse('admin_student_detail', kwargs={'pk': self.pk})

    def get_role_display_uz(self) -> str:
        """Rol nomini o‘zbek tilida."""
        roles = {
            'admin': 'Administrator',
            'manager': 'Menejer',
            'teacher': 'O‘qituvchi',
            'student': 'O‘quvchi',
            'parent': 'Ota-ona',
        }
        return roles.get(self.role, self.role)

    def can_manage(self, other_user: 'CustomUser') -> bool:
        """Bu foydalanuvchi boshqasini boshqara oladimi?"""
        hierarchy = {'admin': 5, 'manager': 4, 'teacher': 3, 'parent': 2, 'student': 1}
        return hierarchy.get(self.role, 0) > hierarchy.get(other_user.role, 0)

    def get_statistics(self) -> dict:
        """Foydalanuvchi statistikasi."""
        stats = {
            'total_notifications': self.notifications.count(),
            'unread_notifications': self.notifications.filter(is_read=False).count(),
        }
        if self.is_student and hasattr(self, 'student_profile'):
            stats.update(self.student_profile.get_statistics())
        return stats

    def update_last_login_ip(self, ip: str):
        """Oxirgi IP ni yangilash."""
        self.last_login_ip = ip
        self.save(update_fields=['last_login_ip'])


# ============================================================
# 5. STUDENT PROFILE
# ============================================================

class StudentProfileQuerySet(models.QuerySet):
    def active(self):
        return self.filter(status='active')

    def top_by_coins(self, limit: int = 10):
        return self.order_by('-coins')[:limit]

    def top_by_balance(self, limit: int = 10):
        return self.order_by('-balance')[:limit]

    def with_stats(self):
        return self.annotate(
            total_tests=Count('test_results', distinct=True),
            avg_score=Avg('test_results__total_score'),
            total_coins_earned=Sum('test_results__coins_awarded'),
        )


class StudentProfile(TimeStampedModel):
    """Talaba profili."""

    STATUS_CHOICES = (
        ('active', 'Aktiv'),
        ('frozen', 'Muzlatilgan'),
        ('graduated', 'Bitirgan'),
        ('dropped', 'Ketib qolgan'),
    )

    user = models.OneToOneField(
        CustomUser, on_delete=models.CASCADE,
        related_name='student_profile', verbose_name="Foydalanuvchi"
    )
    birth_date = models.DateField(blank=True, null=True, verbose_name="Tug‘ilgan sana")
    balance = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name="Balans (so‘m)"
    )
    coins = models.PositiveIntegerField(
        default=0, validators=[MaxValueValidator(10_000_000)],
        verbose_name="Coinlar"
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='active',
        verbose_name="Holat", db_index=True
    )
    parent_phone = models.CharField(
        max_length=17, blank=True, null=True, verbose_name="Ota-ona telefon"
    )
    notes = models.TextField(blank=True, null=True, verbose_name="Izohlar")

    # Qo‘shimcha maydonlar
    level = models.PositiveSmallIntegerField(default=1, verbose_name="Daraja")
    experience_points = models.PositiveIntegerField(default=0, verbose_name="Tajriba ochkolari")
    streak_days = models.PositiveIntegerField(default=0, verbose_name="Streak kunlari")
    last_activity = models.DateTimeField(null=True, blank=True, verbose_name="Oxirgi faollik")

    objects = StudentProfileQuerySet.as_manager()

    class Meta:
        verbose_name = "Talaba profili"
        verbose_name_plural = "Talaba profillari"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['-coins']),
        ]

    def __str__(self) -> str:
        return f"Talaba: {self.user.get_full_name()}"

    @property
    def total_tests(self) -> int:
        return self.test_results.count()

    @property
    def total_score(self) -> int:
        return self.test_results.aggregate(
            total=Coalesce(Sum('total_score'), 0)
        )['total']

    @property
    def average_score(self) -> float:
        result = self.test_results.aggregate(avg=Avg('total_score'))['avg']
        return round(result, 2) if result else 0.0

    @property
    def total_coins_earned(self) -> int:
        return self.test_results.aggregate(
            total=Coalesce(Sum('coins_awarded'), 0)
        )['total']

    @property
    def completion_rate(self) -> float:
        """Testlarni yakunlash foizi."""
        total_quizzes = Quiz.objects.filter(is_active=True).count()
        if not total_quizzes:
            return 0.0
        return round((self.total_tests / total_quizzes) * 100, 1)

    @property
    def is_active_student(self) -> bool:
        return self.status == 'active'

    @property
    def groups_list(self) -> str:
        """Guruhlar ro‘yxati (vergul bilan)."""
        return ', '.join(self.groups.values_list('name', flat=True)) or '—'

    def get_absolute_url(self) -> str:
        return reverse('admin_student_detail', kwargs={'pk': self.pk})

    def add_coins(self, amount: int, reason: str = '') -> 'CoinTransaction':
        """Coin qo‘shish va tranzaksiya yaratish."""
        with transaction.atomic():
            self.coins = F('coins') + amount
            self.save(update_fields=['coins'])
            self.refresh_from_db()

            return CoinTransaction.objects.create(
                student=self,
                amount=amount,
                transaction_type='earn',
                reason=reason or 'Coin qo‘shildi',
                balance_after=self.coins,
            )

    def spend_coins(self, amount: int, reason: str = '') -> Optional['CoinTransaction']:
        """Coin sarflash."""
        if self.coins < amount:
            return None

        with transaction.atomic():
            self.coins = F('coins') - amount
            self.save(update_fields=['coins'])
            self.refresh_from_db()

            return CoinTransaction.objects.create(
                student=self,
                amount=-amount,
                transaction_type='spend',
                reason=reason or 'Coin sarflandi',
                balance_after=self.coins,
            )

    def deposit(self, amount: Decimal, reason: str = '') -> 'Payment':
        """Balansga pul qo‘shish."""
        with transaction.atomic():
            self.balance = F('balance') + amount
            self.save(update_fields=['balance'])

            return Payment.objects.create(
                student=self,
                amount=amount,
                payment_type='deposit',
                reason=reason,
            )

    def get_statistics(self) -> dict:
        """To‘liq statistika."""
        return {
            'total_tests': self.total_tests,
            'total_score': self.total_score,
            'average_score': self.average_score,
            'total_coins': self.coins,
            'total_coins_earned': self.total_coins_earned,
            'balance': float(self.balance),
            'level': self.level,
            'streak_days': self.streak_days,
            'completion_rate': self.completion_rate,
            'groups_count': self.groups.count(),
        }

    def update_activity(self):
        """Oxirgi faollikni yangilash."""
        self.last_activity = timezone.now()
        self.save(update_fields=['last_activity'])


# ============================================================
# 6. TEACHER PROFILE
# ============================================================

class TeacherProfileQuerySet(models.QuerySet):
    def with_courses(self):
        return self.annotate(courses_count=Count('courses', distinct=True))

    def top_rated(self):
        return self.order_by('-average_rating')


class TeacherProfile(TimeStampedModel):
    """O‘qituvchi profili."""

    user = models.OneToOneField(
        CustomUser, on_delete=models.CASCADE,
        related_name='teacher_profile', verbose_name="Foydalanuvchi"
    )
    bio = models.TextField(blank=True, null=True, verbose_name="Biografiya")
    specialization = models.CharField(
        max_length=100, verbose_name="Mutaxassislik",
        help_text="Masalan: Backend, Ingliz tili"
    )
    experiance = models.PositiveSmallIntegerField(
        default=0, validators=[MaxValueValidator(60)],
        verbose_name="Tajriba (yil)"
    )
    fixed_salary = models.DecimalField(
        max_digits=12, decimal_places=2, blank=True, null=True,
        verbose_name="Belgilangan oylik"
    )
    salary_percentage = models.PositiveSmallIntegerField(
        default=0, validators=[MaxValueValidator(100)],
        verbose_name="Foiz stavka"
    )

    # Qo‘shimcha
    education = models.CharField(max_length=255, blank=True, null=True, verbose_name="Ma’lumoti")
    certificates = models.TextField(blank=True, null=True, verbose_name="Sertifikatlar")
    rating = models.DecimalField(
        max_digits=3, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(0), MaxValueValidator(5)],
        verbose_name="Reyting"
    )
    average_rating = models.DecimalField(
        max_digits=3, decimal_places=2, default=Decimal('0.00'),
        verbose_name="O‘rtacha reyting"
    )

    objects = TeacherProfileQuerySet.as_manager()

    class Meta:
        verbose_name = "O‘qituvchi profili"
        verbose_name_plural = "O‘qituvchilar profillari"
        ordering = ['-rating', 'user__first_name']

    def __str__(self) -> str:
        return f"O‘qituvchi: {self.user.get_full_name()}"

    @property
    def years_of_experience(self) -> str:
        return f"{self.experiance} yil"

    @property
    def monthly_salary(self) -> Decimal:
        """Oylik maosh (fixed yoki foizdan)."""
        return self.fixed_salary or Decimal('0')

    def get_absolute_url(self) -> str:
        return reverse('admin_teacher_detail', kwargs={'pk': self.pk})


# ============================================================
# 7. MANAGER PROFILE
# ============================================================

class ManagerProfile(TimeStampedModel):
    """Menejer profili."""

    user = models.OneToOneField(
        CustomUser, on_delete=models.CASCADE,
        related_name='manager_profile', verbose_name="Foydalanuvchi"
    )
    branch = models.CharField(
        max_length=100, blank=True, null=True,
        verbose_name="Filial nomi"
    )
    permissions_level = models.PositiveSmallIntegerField(
        default=0, validators=[MaxValueValidator(10)],
        verbose_name="Ruxsat darajasi"
    )

    class Meta:
        verbose_name = "Menejer profili"
        verbose_name_plural = "Menejerlar profillari"

    def __str__(self) -> str:
        return f"Menejer: {self.user.get_full_name()} ({self.branch or '—'})"

    def get_absolute_url(self) -> str:
        return reverse('admin_manager_detail', kwargs={'pk': self.pk})


# ============================================================
# 8. QUIZ CATEGORY
# ============================================================

class QuizCategory(TimeStampedModel):
    """Test yo‘nalishi (kategoriyasi)."""

    name = models.CharField(max_length=100, unique=True, verbose_name="Yo‘nalish nomi")
    slug = models.SlugField(unique=True, blank=True, null=True, verbose_name="Slug")
    description = models.TextField(blank=True, null=True, verbose_name="Tavsif")
    icon = models.CharField(max_length=100, default='fas fa-book', verbose_name="Ikonka")
    color = models.CharField(max_length=20, default='#4F46E5', verbose_name="Rang")
    order = models.PositiveIntegerField(default=0, verbose_name="Tartib")
    is_active = models.BooleanField(default=True, verbose_name="Aktiv")

    class Meta:
        verbose_name = "Test yo‘nalishi"
        verbose_name_plural = "Test yo‘nalishlari"
        ordering = ['order', 'name']

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @property
    def total_quizzes(self) -> int:
        return self.quizzes.filter(is_active=True).count()

    def get_absolute_url(self) -> str:
        return reverse('admin_quiz_category_detail', kwargs={'pk': self.pk})


# ============================================================
# 9. QUIZ
# ============================================================

class QuizQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def by_difficulty(self, difficulty: str):
        return self.filter(difficulty=difficulty)

    def easy(self):
        return self.filter(difficulty='easy')

    def medium(self):
        return self.filter(difficulty='medium')

    def hard(self):
        return self.filter(difficulty='hard')

    def recent(self, days: int = 7):
        threshold = timezone.now() - timedelta(days=days)
        return self.filter(created_at__gte=threshold)

    def with_stats(self):
        return self.annotate(
            attempts_count=Count('results', distinct=True),
            avg_score=Avg('results__total_score'),
        )


class Quiz(TimeStampedModel):
    """Test modeli."""

    DIFFICULTY_CHOICES = (
        ('easy', 'Oson'),
        ('medium', 'O‘rta'),
        ('hard', 'Qiyin'),
    )

    category = models.ForeignKey(
        QuizCategory, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='quizzes',
        verbose_name="Yo‘nalish"
    )
    difficulty = models.CharField(
        max_length=20, choices=DIFFICULTY_CHOICES, default='medium',
        verbose_name="Qiyinlik darajasi"
    )
    title = models.CharField(max_length=255, verbose_name="Test nomi")
    description = models.TextField(blank=True, null=True, verbose_name="Tavsif")
    is_active = models.BooleanField(default=True, verbose_name="Aktiv")
    coins_reward = models.PositiveIntegerField(default=0, verbose_name="Coin mukofoti")
    locked = models.BooleanField(default=True, verbose_name="Qulflangan")

    # Qo‘shimcha
    duration_minutes = models.PositiveIntegerField(
        default=30, validators=[MinValueValidator(1), MaxValueValidator(300)],
        verbose_name="Davomiyligi (daqiqa)"
    )
    passing_score = models.PositiveSmallIntegerField(
        default=60, validators=[MinValueValidator(0), MaxValueValidator(100)],
        verbose_name="O‘tish bali (%)"
    )
    max_attempts = models.PositiveSmallIntegerField(
        default=3, verbose_name="Maksimal urinishlar"
    )
    shuffle_questions = models.BooleanField(default=False, verbose_name="Savollarni aralashtirish")
    show_answers = models.BooleanField(default=True, verbose_name="Javoblarni ko‘rsatish")

    objects = QuizQuerySet.as_manager()

    class Meta:
        verbose_name = "Test"
        verbose_name_plural = "Testlar"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['is_active', 'difficulty']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def max_score(self) -> int:
        return self.questions.aggregate(
            total=Coalesce(Sum('points'), 0)
        )['total']

    @property
    def total_questions(self) -> int:
        return self.questions.count()

    @property
    def attempts_count(self) -> int:
        return self.results.count()

    @property
    def average_score(self) -> float:
        result = self.results.aggregate(avg=Avg('total_score'))['avg']
        return round(result, 2) if result else 0.0

    @property
    def success_rate(self) -> float:
        """Muvaffaqiyat foizi."""
        total = self.attempts_count
        if not total:
            return 0.0
        passed = self.results.filter(
            total_score__gte=F('quiz__max_score') * self.passing_score / 100
        ).count()
        return round((passed / total) * 100, 1)

    @property
    def difficulty_color(self) -> str:
        colors = {'easy': '#059669', 'medium': '#F59E0B', 'hard': '#dc2626'}
        return colors.get(self.difficulty, '#6B7280')

    def get_absolute_url(self) -> str:
        return reverse('admin_quiz_detail', kwargs={'pk': self.pk})

    def can_attempt(self, student_profile: 'StudentProfile') -> bool:
        """Talaba yana urinishi mumkinmi?"""
        attempts = self.results.filter(student=student_profile).count()
        return attempts < self.max_attempts

    def get_questions(self, shuffle: bool = None):
        """Savollarni olish."""
        qs = self.questions.all()
        if shuffle or self.shuffle_questions:
            qs = qs.order_by('?')
        return qs


# ============================================================
# 10. QUESTION
# ============================================================

class Question(TimeStampedModel):
    """Test savoli."""

    quiz = models.ForeignKey(
        Quiz, on_delete=models.CASCADE,
        related_name="questions", verbose_name="Test"
    )
    text = models.TextField(verbose_name="Savol matni")
    image = models.ImageField(
        upload_to="quiz_questions/", blank=True, null=True,
        validators=[validate_file_size],
        verbose_name="Savol rasmi"
    )
    points = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1), MaxValueValidator(100)],
        verbose_name="Ball"
    )
    order = models.PositiveIntegerField(default=0, verbose_name="Tartib raqami")
    explanation = models.TextField(
        blank=True, null=True, verbose_name="Tushuntirish"
    )

    class Meta:
        verbose_name = "Savol"
        verbose_name_plural = "Savollar"
        ordering = ["order", "id"]
        indexes = [models.Index(fields=['quiz', 'order'])]

    def __str__(self) -> str:
        return self.text[:60]

    @property
    def correct_option(self) -> Optional['AnswerOption']:
        """To‘g‘ri javob."""
        return self.options.filter(is_correct=True).first()

    @property
    def options_count(self) -> int:
        return self.options.count()

    def get_absolute_url(self) -> str:
        return reverse('admin_question_detail', kwargs={'pk': self.pk})


# ============================================================
# 11. ANSWER OPTION
# ============================================================

class AnswerOption(TimeStampedModel):
    """Javob varianti."""

    question = models.ForeignKey(
        Question, on_delete=models.CASCADE,
        related_name="options", verbose_name="Savol"
    )
    text = models.CharField(max_length=255, verbose_name="Javob varianti")
    is_correct = models.BooleanField(default=False, verbose_name="To‘g‘ri javob")
    order = models.PositiveIntegerField(default=0, verbose_name="Tartib")

    class Meta:
        verbose_name = "Javob varianti"
        verbose_name_plural = "Javob variantlari"
        ordering = ['order', 'id']

    def __str__(self) -> str:
        mark = "✓" if self.is_correct else "✗"
        return f"{mark} {self.text}"

    def clean(self):
        """Bir savolda bir nechta to‘g‘ri javob bo‘lmasligi."""
        if self.is_correct:
            existing = AnswerOption.objects.filter(
                question=self.question, is_correct=True
            ).exclude(pk=self.pk)
            if existing.exists():
                raise ValidationError("Bu savolda allaqachon to‘g‘ri javob bor.")


# ============================================================
# 12. TEST RESULT
# ============================================================

class TestResultQuerySet(models.QuerySet):
    def passed(self, threshold: int = 60):
        return self.filter(
            total_score__gte=F('quiz__max_score') * threshold / 100
        )

    def failed(self, threshold: int = 60):
        return self.filter(
            total_score__lt=F('quiz__max_score') * threshold / 100
        )

    def recent(self, days: int = 7):
        threshold = timezone.now() - timedelta(days=days)
        return self.filter(taken_at__gte=threshold)

    def by_student(self, student):
        return self.filter(student=student)


class TestResult(TimeStampedModel):
    """Test natijasi."""

    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE,
        related_name="test_results", verbose_name="Talaba"
    )
    quiz = models.ForeignKey(
        Quiz, on_delete=models.CASCADE,
        related_name="results", verbose_name="Test"
    )
    correct_answers = models.PositiveIntegerField(default=0, verbose_name="To‘g‘ri javoblar")
    total_score = models.PositiveIntegerField(default=0, verbose_name="To‘plangan ball")
    coins_awarded = models.PositiveIntegerField(default=0, verbose_name="Berilgan coinlar")
    taken_at = models.DateTimeField(auto_now_add=True, verbose_name="Topshirilgan vaqt")

    # Qo‘shimcha
    time_spent_seconds = models.PositiveIntegerField(default=0, verbose_name="Sarflangan vaqt (sek)")
    attempt_number = models.PositiveSmallIntegerField(default=1, verbose_name="Urinish raqami")

    objects = TestResultQuerySet.as_manager()

    class Meta:
        verbose_name = "Test natijasi"
        verbose_name_plural = "Test natijalari"
        ordering = ["-taken_at"]
        indexes = [
            models.Index(fields=['student', '-taken_at']),
            models.Index(fields=['quiz', '-taken_at']),
        ]

    def __str__(self) -> str:
        return f"{self.student.user.get_full_name()} – {self.quiz.title}: {self.total_score} ball"

    @property
    def percentage(self) -> float:
        max_score = self.quiz.max_score
        if not max_score:
            return 0.0
        return round((self.total_score / max_score) * 100, 1)

    @property
    def is_passed(self) -> bool:
        """O‘tgan yoki o‘tmagan?"""
        return self.percentage >= self.quiz.passing_score

    @property
    def grade(self) -> str:
        """Baho (A, B, C, D, F)."""
        pct = self.percentage
        if pct >= 90: return 'A'
        if pct >= 80: return 'B'
        if pct >= 70: return 'C'
        if pct >= 60: return 'D'
        return 'F'

    @property
    def time_spent_display(self) -> str:
        """Sarflangan vaqtni chiroyli formatda."""
        s = self.time_spent_seconds
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h} soat {m} daq"
        return f"{m} daq {s} sek"

    @property
    def wrong_answers(self) -> int:
        return self.quiz.total_questions - self.correct_answers

    def get_absolute_url(self) -> str:
        return reverse('admin_test_result_detail', kwargs={'pk': self.pk})


# ============================================================
# 13. TEST RESULT ANSWER
# ============================================================

class TestResultAnswer(TimeStampedModel):
    """Talabaning bir savolga bergan javobi."""

    result = models.ForeignKey(
        TestResult, on_delete=models.CASCADE,
        related_name="answers", verbose_name="Natija"
    )
    question = models.ForeignKey(
        Question, on_delete=models.CASCADE, verbose_name="Savol"
    )
    selected_option = models.ForeignKey(
        AnswerOption, on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name="Tanlangan javob"
    )
    is_correct = models.BooleanField(default=False, verbose_name="To‘g‘rimi?")

    class Meta:
        verbose_name = "Javob yozuvi"
        verbose_name_plural = "Javob yozuvlari"
        unique_together = ('result', 'question')

    def __str__(self) -> str:
        return f"{self.question.text[:30]} – {'✓' if self.is_correct else '✗'}"


# ============================================================
# 14. STUDENT QUIZ ACCESS
# ============================================================

class StudentQuizAccess(TimeStampedModel):
    """Talabaga test uchun ruxsat."""

    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE,
        related_name='quiz_permissions', verbose_name="Talaba"
    )
    quiz = models.ForeignKey(
        Quiz, on_delete=models.CASCADE,
        related_name='student_permissions', verbose_name="Test"
    )
    is_allowed = models.BooleanField(default=False, verbose_name="Ruxsat berilgan")
    assigned_at = models.DateTimeField(auto_now_add=True, verbose_name="Tayinlangan")
    assigned_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name="Kim tayinladi"
    )
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name="Amal qilish muddati")

    class Meta:
        unique_together = ('student', 'quiz')
        verbose_name = "Talaba test ruxsati"
        verbose_name_plural = "Talaba test ruxsatlari"
        indexes = [models.Index(fields=['student', 'is_allowed'])]

    def __str__(self) -> str:
        status = '✅' if self.is_allowed else '⛔'
        return f"{self.student.user.phone_number} → {self.quiz.title} {status}"

    @property
    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        return timezone.now() > self.expires_at

    @property
    def is_valid(self) -> bool:
        return self.is_allowed and not self.is_expired


# ============================================================
# 15. STUDENT GROUP
# ============================================================

class StudentGroupQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def with_stats(self):
        return self.annotate(
            students_count=Count('students', distinct=True),
            lessons_count=Count('lessons', distinct=True),
        )


class StudentGroup(TimeStampedModel):
    """Talabalar guruhi."""
    schedule = models.JSONField(
        default=dict, blank=True,
        verbose_name="Jadval",
        help_text='{"monday": "14:00", "wednesday": "14:00", "friday": "14:00"}'
    )

    # ⭐ YANGI — jadval turi
    schedule_type = models.CharField(
        max_length=10,
        choices=[
            ('odd', 'Toq kunlar (Du·Ch·Ju)'),
            ('even', 'Juft kunlar (Se·Pa·Sha)'),
            ('custom', 'Qo\'lda'),
        ],
        default='odd',
        verbose_name="Jadval turi"
    )

    # ⭐ YANGI — darslar boshlanish sanasi
    lessons_start_date = models.DateField(
        null=True, blank=True,
        verbose_name="Darslar boshlanish sanasi"
    )
    name = models.CharField(max_length=100, unique=True, verbose_name="Guruh nomi")
    students = models.ManyToManyField(
        StudentProfile,   related_name='groups', blank=True,
        verbose_name="Talabalar"
    )
    teacher = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
         related_name='groups_taught', verbose_name="O‘qituvchi",
        limit_choices_to={'role': 'teacher'}
    )
    is_active = models.BooleanField(default=True, verbose_name="Aktiv")
    description = models.TextField(blank=True, null=True, verbose_name="Tavsif")
    color = models.CharField(max_length=20, default='#4F46E5', verbose_name="Rang")

    objects = StudentGroupQuerySet.as_manager()

    class Meta:
        verbose_name = "Talabalar guruhi"
        verbose_name_plural = "Talabalar guruhlari"
        ordering = ['-created_at']

    def __str__(self) -> str:
        return self.name

    @property
    def students_count(self) -> int:
        return self.students.count()

    @property
    def average_performance(self) -> float:
        """Guruhning o‘rtacha natijasi."""
        result = self.students.aggregate(
            avg=Avg('test_results__total_score')
        )['avg']
        return round(result, 2) if result else 0.0

    @property
    def total_coins(self) -> int:
        return self.students.aggregate(
            total=Coalesce(Sum('coins'), 0)
        )['total']

    def get_absolute_url(self) -> str:
        return reverse('admin_group_detail', kwargs={'pk': self.pk})

    def add_student(self, student: StudentProfile):
        """Talabani guruhga qo‘shish."""
        self.students.add(student)
        return True

    def remove_student(self, student: StudentProfile):
        """Talabani guruhdan chiqarish."""
        self.students.remove(student)
        return True


# ============================================================
# 16. GROUP QUIZ ACCESS
# ============================================================

class GroupQuizAccess(TimeStampedModel):
    """Guruhga test uchun ruxsat."""

    group = models.ForeignKey(
        StudentGroup, on_delete=models.CASCADE,
        related_name='quiz_permissions', verbose_name="Guruh"
    )
    quiz = models.ForeignKey(
        Quiz, on_delete=models.CASCADE,
        related_name='group_permissions', verbose_name="Test"
    )
    is_allowed = models.BooleanField(default=True, verbose_name="Ruxsat berilgan")
    assigned_at = models.DateTimeField(auto_now_add=True, verbose_name="Tayinlangan")
    assigned_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name="Kim tayinladi"
    )
    deadline = models.DateTimeField(null=True, blank=True, verbose_name="Muddat")

    class Meta:
        unique_together = ('group', 'quiz')
        verbose_name = "Guruh test ruxsati"
        verbose_name_plural = "Guruh test ruxsatlari"

    def __str__(self) -> str:
        status = '✅' if self.is_allowed else '⛔'
        return f"{self.group.name} → {self.quiz.title} {status}"

    @property
    def is_expired(self) -> bool:
        if not self.deadline:
            return False
        return timezone.now() > self.deadline


# ============================================================
# 17. MENU SECTION
# ============================================================

class MenuSection(TimeStampedModel):
    """Menyu bo‘limi."""

    title = models.CharField(max_length=200, verbose_name="Sarlavha")
    order = models.PositiveIntegerField(default=0, verbose_name="Tartib")
    is_active = models.BooleanField(default=True, verbose_name="Aktiv")
    icon = models.CharField(max_length=100, blank=True, null=True, verbose_name="Ikonka")

    class Meta:
        ordering = ['order']
        verbose_name = "Menyu bo‘limi"
        verbose_name_plural = "Menyu bo‘limlari"

    def __str__(self) -> str:
        return self.title

    @property
    def items_count(self) -> int:
        return self.items.filter(is_active=True).count()


# ============================================================
# 18. MENU ITEM
# ============================================================

class MenuItem(TimeStampedModel):
    """Menyu elementi."""

    section = models.ForeignKey(
        MenuSection, on_delete=models.CASCADE,
        related_name='items', null=True, blank=True,
        verbose_name="Bo‘lim"
    )
    title = models.CharField(max_length=200, verbose_name="Sarlavha")
    url = models.CharField(max_length=255, blank=True, null=True, verbose_name="URL")
    url_name = models.CharField(max_length=100, blank=True, null=True, verbose_name="URL nomi")
    icon_class = models.CharField(
        max_length=100, default="fas fa-circle", verbose_name="Ikonka"
    )
    order = models.PositiveIntegerField(default=0, verbose_name="Tartib")
    is_active = models.BooleanField(default=True, verbose_name="Aktiv")
    badge_text = models.CharField(
        max_length=20, blank=True, null=True, verbose_name="Badge matni"
    )
    badge_color = models.CharField(
        max_length=150, default="bg-rose-500", verbose_name="Badge rangi"
    )
    required_role = models.CharField(
        max_length=10, blank=True, null=True,
        choices=ROLE_CHOICES, verbose_name="Kerakli rol"
    )

    class Meta:
        ordering = ['section__order', 'order']
        verbose_name = "Menyu elementi"
        verbose_name_plural = "Menyu elementlari"

    def __str__(self) -> str:
        section_title = self.section.title if self.section else '—'
        return f"{section_title} → {self.title}"

    def get_url(self) -> str:
        """URL ni olish."""
        if self.url_name:
            try:
                return reverse(self.url_name)
            except Exception:
                return '#'
        return self.url if self.url else '#'

    def is_visible_for(self, user: CustomUser) -> bool:
        """Foydalanuvchi uchun ko‘rinadimi?"""
        if not self.is_active:
            return False
        if self.required_role and user.role != self.required_role:
            return False
        return True


# ============================================================
# 19. COURSE
# ============================================================

class CourseQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def ongoing(self):
        today = timezone.now().date()
        return self.filter(start_date__lte=today, end_date__gte=today)

    def finished(self):
        return self.filter(end_date__lt=timezone.now().date())

    def upcoming(self):
        return self.filter(start_date__gt=timezone.now().date())


class Course(TimeStampedModel):
    """Kurs modeli."""

    title = models.CharField(max_length=255, unique=True, verbose_name="Kurs nomi")
    description = models.TextField(blank=True, verbose_name="Tavsif")
    start_date = models.DateField(verbose_name="Boshlanish sanasi")
    end_date = models.DateField(verbose_name="Tugash sanasi")
    duration_months = models.PositiveSmallIntegerField(
        default=9, validators=[MinValueValidator(1), MaxValueValidator(60)],
        verbose_name="Davomiyligi (oy)"
    )
    is_active = models.BooleanField(default=True, verbose_name="Aktiv")

    # Qo‘shimcha
    price = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0'),
        verbose_name="Narxi (so‘m)"
    )
    image = models.ImageField(
        upload_to='courses/', blank=True, null=True,
        validators=[validate_file_size],
        verbose_name="Kurs rasmi"
    )
    teacher = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='courses', limit_choices_to={'role': 'teacher'},
        verbose_name="O‘qituvchi"
    )

    objects = CourseQuerySet.as_manager()

    class Meta:
        verbose_name = "Kurs"
        verbose_name_plural = "Kurslar"
        ordering = ['-start_date']
        indexes = [
            models.Index(fields=['is_active', 'start_date']),
        ]

    def __str__(self) -> str:
        return self.title

    def clean(self):
        """Sanani tekshirish."""
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValidationError("Boshlanish sanasi tugash sanasidan keyin bo‘lishi mumkin emas.")

    @property
    def lessons_count(self) -> int:
        return self.lessons.count()

    @property
    def progress_percent(self) -> float:
        """Kurs tugash foizi."""
        today = timezone.now().date()
        if self.start_date > today:
            return 0.0
        if self.end_date < today:
            return 100.0
        total_days = (self.end_date - self.start_date).days
        passed_days = (today - self.start_date).days
        if total_days <= 0:
            return 0.0
        return round((passed_days / total_days) * 100, 1)

    @property
    def is_ongoing(self) -> bool:
        today = timezone.now().date()
        return self.start_date <= today <= self.end_date

    @property
    def students_count(self) -> int:
        return StudentProfile.objects.filter(
            groups__lessons__course=self
        ).distinct().count()

    def get_absolute_url(self) -> str:
        return reverse('admin_course_detail', kwargs={'pk': self.pk})


# ============================================================
# 20. LESSON
# ============================================================

class LessonQuerySet(models.QuerySet):
    def upcoming(self):
        return self.filter(date__gte=timezone.now().date())

    def past(self):
        return self.filter(date__lt=timezone.now().date())

    def today(self):
        return self.filter(date=timezone.now().date())


class Lesson(TimeStampedModel):
    """Dars modeli."""

    course = models.ForeignKey(
        Course, on_delete=models.CASCADE,
        related_name='lessons', verbose_name="Kurs"
    )
    title = models.CharField(max_length=255, verbose_name="Dars nomi")
    content = models.TextField(blank=True, verbose_name="Kontent")
    order = models.PositiveIntegerField(verbose_name="Tartib raqami")
    date = models.DateField(verbose_name="Sana")
    group = models.ForeignKey(
        StudentGroup, on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name="Guruh"
    )

    # Qo‘shimcha
    video_url = models.URLField(blank=True, null=True, verbose_name="Video URL")
    duration_minutes = models.PositiveSmallIntegerField(
        default=60, verbose_name="Davomiyligi (daqiqa)"
    )
    is_published = models.BooleanField(default=True, verbose_name="E’lon qilingan")

    objects = LessonQuerySet.as_manager()

    class Meta:
        unique_together = ('course', 'order')
        ordering = ['date', 'order']
        verbose_name = "Dars"
        verbose_name_plural = "Darslar"
        indexes = [models.Index(fields=['course', 'date'])]

    def __str__(self) -> str:
        return f"{self.course.title} – {self.title}"

    @property
    def is_today(self) -> bool:
        return self.date == timezone.now().date()

    @property
    def is_past(self) -> bool:
        return self.date < timezone.now().date()

    @property
    def questions_count(self) -> int:
        return self.questions.count()

    @property
    def assignments_count(self) -> int:
        return self.assignment_set.count()

    def get_absolute_url(self) -> str:
        return reverse('admin_lesson_detail', kwargs={'pk': self.pk})


# ============================================================
# 21. TASK
# ============================================================

class TaskQuerySet(models.QuerySet):
    def by_type(self, task_type: str):
        return self.filter(task_type=task_type)

    def quizzes(self):
        return self.filter(task_type='quiz')

    def ctf(self):
        return self.filter(task_type='ctf')


class Task(TimeStampedModel):
    """Topshiriq modeli (barcha turlari)."""

    TASK_TYPE_CHOICES = (
        ('quiz', 'Test'),
        ('open_question', 'Ochiq savol'),
        ('file_upload', 'Fayl yuklash'),
        ('ctf', 'CTF bayrog‘i'),
        ('problem', 'Masala'),
    )

    task_type = models.CharField(
        max_length=20, choices=TASK_TYPE_CHOICES,
        verbose_name="Topshiriq turi", db_index=True
    )
    title = models.CharField(max_length=255, verbose_name="Sarlavha")
    description = models.TextField(blank=True, verbose_name="Tavsif")
    quiz = models.ForeignKey(
        Quiz, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='tasks', verbose_name="Bog‘langan test"
    )
    flag = models.CharField(
        max_length=255, blank=True, null=True,
        verbose_name="CTF bayrog‘i",
        help_text="CTF uchun to‘g‘ri bayroq"
    )
    file = models.FileField(
        upload_to=task_file_upload_path, blank=True, null=True,
        validators=[validate_file_size],
        verbose_name="Fayl"
    )
    max_score = models.PositiveIntegerField(
        default=100, validators=[MinValueValidator(1)],
        verbose_name="Maksimal ball"
    )
    coins_reward = models.PositiveIntegerField(default=0, verbose_name="Coin mukofoti")

    # Qo‘shimcha
    difficulty = models.CharField(
        max_length=20,
        choices=(('easy', 'Oson'), ('medium', 'O‘rta'), ('hard', 'Qiyin')),
        default='medium', verbose_name="Qiyinlik"
    )
    time_limit_minutes = models.PositiveSmallIntegerField(
        default=0, verbose_name="Vaqt chegarasi (daqiqa, 0 = cheksiz)"
    )
    is_published = models.BooleanField(default=True, verbose_name="E’lon qilingan")

    objects = TaskQuerySet.as_manager()

    class Meta:
        verbose_name = "Topshiriq"
        verbose_name_plural = "Topshiriqlar"
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f"{self.get_task_type_display()}: {self.title}"

    @property
    def assignments_count(self) -> int:
        return self.assignments.count()

    @property
    def submissions_count(self) -> int:
        return Submission.objects.filter(assignment__task=self).count()

    @property
    def average_score(self) -> float:
        result = Submission.objects.filter(
            assignment__task=self, score__isnull=False
        ).aggregate(avg=Avg('score'))['avg']
        return round(float(result), 2) if result else 0.0

    def get_absolute_url(self) -> str:
        return reverse('admin_task_detail', kwargs={'pk': self.pk})


# ============================================================
# 22. ASSIGNMENT
# ============================================================

class AssignmentQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def open_now(self):
        now = timezone.now()
        return self.filter(opens_at__lte=now, closes_at__gte=now, is_active=True)

    def closed(self):
        return self.filter(closes_at__lt=timezone.now())


class Assignment(TimeStampedModel):
    """Topshiriqni guruhga biriktirish."""

    task = models.ForeignKey(
        Task, on_delete=models.CASCADE,
        related_name='assignments', verbose_name="Topshiriq"
    )
    group = models.ForeignKey(
        StudentGroup, on_delete=models.CASCADE,
        related_name='assignments', verbose_name="Guruh"
    )
    lesson = models.ForeignKey(
        Lesson, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Dars"
    )
    opens_at = models.DateTimeField(verbose_name="Ochilish vaqti")
    closes_at = models.DateTimeField(verbose_name="Yopilish vaqti")
    is_active = models.BooleanField(default=True, verbose_name="Aktiv")
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True,
        verbose_name="Kim yaratdi"
    )

    # Qo‘shimcha
    max_attempts = models.PositiveSmallIntegerField(default=1, verbose_name="Maksimal urinishlar")
    late_submission_allowed = models.BooleanField(
        default=False, verbose_name="Kechikishga ruxsat"
    )
    late_penalty_percent = models.PositiveSmallIntegerField(
        default=0, validators=[MaxValueValidator(100)],
        verbose_name="Kechikish jarimasi (%)"
    )

    objects = AssignmentQuerySet.as_manager()

    class Meta:
        ordering = ['opens_at']
        verbose_name = "Biriktirish"
        verbose_name_plural = "Biriktirishlar"
        indexes = [
            models.Index(fields=['group', 'is_active']),
        ]

    def __str__(self) -> str:
        return f"{self.task.title} → {self.group.name}"

    def clean(self):
        if self.opens_at and self.closes_at and self.opens_at >= self.closes_at:
            raise ValidationError("Ochilish vaqti yopilish vaqtidan oldin bo‘lishi kerak.")

    @property
    def is_open(self) -> bool:
        now = timezone.now()
        return self.is_active and self.opens_at <= now <= self.closes_at

    @property
    def is_closed(self) -> bool:
        return timezone.now() > self.closes_at

    @property
    def submissions_count(self) -> int:
        return self.submissions.count()

    @property
    def time_remaining(self) -> Optional[timedelta]:
        """Qolgan vaqt."""
        if self.is_closed:
            return None
        return self.closes_at - timezone.now()

    def get_absolute_url(self) -> str:
        return reverse('admin_assignment_detail', kwargs={'pk': self.pk})


# ============================================================
# 23. SUBMISSION
# ============================================================

class SubmissionQuerySet(models.QuerySet):
    def graded(self):
        return self.filter(score__isnull=False)

    def ungraded(self):
        return self.filter(score__isnull=True)

    def late(self):
        return self.filter(is_late=True)

    def on_time(self):
        return self.filter(is_late=False)


class Submission(TimeStampedModel):
    """Talabaning topshirig‘i."""

    assignment = models.ForeignKey(
        Assignment, on_delete=models.CASCADE,
        related_name='submissions', verbose_name="Biriktirish"
    )
    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE,
        related_name='submissions', verbose_name="Talaba"
    )
    submitted_at = models.DateTimeField(auto_now_add=True, verbose_name="Topshirilgan vaqt")
    is_late = models.BooleanField(default=False, verbose_name="Kechikkan")
    score = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name="Ball"
    )
    answer_text = models.TextField(blank=True, null=True, verbose_name="Javob matni")
    answer_file = models.FileField(
        upload_to=submission_file_upload_path, blank=True, null=True,
        validators=[validate_file_size],
        verbose_name="Javob fayli"
    )
    test_result = models.ForeignKey(
        TestResult, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Test natijasi"
    )

    # Qo‘shimcha
    graded_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='graded_submissions', verbose_name="Kim baholadi"
    )
    graded_at = models.DateTimeField(null=True, blank=True, verbose_name="Baholangan vaqt")
    feedback = models.TextField(blank=True, null=True, verbose_name="Fikr-mulohaza")
    coins_awarded = models.PositiveIntegerField(default=0, verbose_name="Berilgan coinlar")

    objects = SubmissionQuerySet.as_manager()

    class Meta:
        unique_together = ('assignment', 'student')
        verbose_name = "Topshirilgan ish"
        verbose_name_plural = "Topshirilgan ishlar"
        ordering = ['-submitted_at']
        indexes = [
            models.Index(fields=['student', '-submitted_at']),
            models.Index(fields=['assignment', 'is_late']),
        ]

    def __str__(self) -> str:
        name = self.student.user.get_full_name()
        return f"{name} – {self.assignment.task.title}"

    @property
    def score_percent(self) -> float:
        """Ball foizi."""
        if self.score is None:
            return 0.0
        max_score = self.assignment.task.max_score
        if not max_score:
            return 0.0
        return round(float(self.score) / max_score * 100, 1)

    @property
    def is_graded(self) -> bool:
        return self.score is not None

    @property
    def grade_letter(self) -> str:
        pct = self.score_percent
        if pct >= 90: return 'A'
        if pct >= 80: return 'B'
        if pct >= 70: return 'C'
        if pct >= 60: return 'D'
        return 'F'

    def grade(self, score: Decimal, graded_by: CustomUser = None, feedback: str = ''):
        """Baholash."""
        self.score = score
        self.graded_by = graded_by
        self.graded_at = timezone.now()
        if feedback:
            self.feedback = feedback

        # Coin berish
        if score >= self.assignment.task.max_score * 0.6:
            coins = self.assignment.task.coins_reward
            self.coins_awarded = coins
            if coins:
                self.student.add_coins(coins, reason=f"Topshiriq: {self.assignment.task.title}")

        self.save()

    def get_absolute_url(self) -> str:
        return reverse('admin_submission_detail', kwargs={'pk': self.pk})


# ============================================================
# 24. ACTIVITY LOG
# ============================================================

class ActivityLogQuerySet(models.QuerySet):
    def today(self):
        return self.filter(login_time__date=timezone.now().date())

    def for_user(self, user):
        return self.filter(user=user)

    def recent(self, days: int = 7):
        threshold = timezone.now() - timedelta(days=days)
        return self.filter(login_time__gte=threshold)


class ActivityLog(TimeStampedModel):
    """Foydalanuvchi faoliyati jurnali."""

    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE,
        related_name='activity_logs', verbose_name="Foydalanuvchi"
    )
    login_time = models.DateTimeField(null=True, blank=True, verbose_name="Kirish vaqti")
    logout_time = models.DateTimeField(null=True, blank=True, verbose_name="Chiqish vaqti")
    total_seconds = models.PositiveIntegerField(default=0, verbose_name="Umumiy sekund")
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP manzil")

    objects = ActivityLogQuerySet.as_manager()

    class Meta:
        verbose_name = "Faoliyat yozuvi"
        verbose_name_plural = "Faoliyat yozuvlari"
        ordering = ['-login_time']
        indexes = [models.Index(fields=['user', '-login_time'])]

    def __str__(self) -> str:
        return f"{self.user.phone_number} – {self.total_seconds}s"

    @property
    def duration_hours(self) -> float:
        return round(self.total_seconds / 3600, 2)

    @property
    def duration_display(self) -> str:
        s = self.total_seconds
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        if h:
            return f"{h} soat {m} daq"
        return f"{m} daq {sec} sek"

    def stop(self):
        """Faoliyatni to‘xtatish."""
        self.logout_time = timezone.now()
        if self.login_time:
            self.total_seconds = int((self.logout_time - self.login_time).total_seconds())
        self.save()


# ============================================================
# 25. NOTIFICATION
# ============================================================

class NotificationQuerySet(models.QuerySet):
    def unread(self):
        return self.filter(is_read=False)

    def read(self):
        return self.filter(is_read=True)

    def sent(self):
        return self.filter(sent=True)

    def approved(self):
        return self.filter(is_approved=True)

    def by_type(self, ntype: str):
        return self.filter(notification_type=ntype)


class Notification(TimeStampedModel):
    """Bildirishnoma (ota-onalarga SMS uchun)."""

    NOTIFICATION_TYPES = (
        ('homework_missed', 'Uy vazifasi bajarilmadi'),
        ('over_activity', 'Haddan tashqari faollik'),
        ('daily_report', 'Kunlik hisobot'),
        ('weekly_report', 'Haftalik hisobot'),
        ('achievement', 'Yutuq'),
        ('payment', 'To‘lov'),
        ('system', 'Tizim xabari'),
        ('custom', 'Boshqa'),
    )

    PRIORITY_CHOICES = (
        ('low', 'Past'),
        ('normal', 'O‘rta'),
        ('high', 'Yuqori'),
        ('urgent', 'Shoshilinch'),
    )

    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE,
        related_name='notifications', verbose_name="Foydalanuvchi"
    )
    notification_type = models.CharField(
        max_length=30, choices=NOTIFICATION_TYPES,
        verbose_name="Turi", db_index=True
    )
    message = models.TextField(verbose_name="Xabar")
    is_approved = models.BooleanField(default=False, verbose_name="Tasdiqlangan")
    approved_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='approved_notifications', verbose_name="Kim tasdiqladi"
    )
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name="Tasdiqlangan vaqt")
    sent = models.BooleanField(default=False, verbose_name="Yuborilgan")
    is_read = models.BooleanField(default=False, verbose_name="O‘qilgan")
    read_at = models.DateTimeField(null=True, blank=True, verbose_name="O‘qilgan vaqt")

    # Qo‘shimcha
    title = models.CharField(max_length=255, blank=True, null=True, verbose_name="Sarlavha")
    priority = models.CharField(
        max_length=10, choices=PRIORITY_CHOICES,
        default='normal', verbose_name="Muhimlik"
    )
    link = models.CharField(max_length=500, blank=True, null=True, verbose_name="Havola")

    objects = NotificationQuerySet.as_manager()

    class Meta:
        verbose_name = "Bildirishnoma"
        verbose_name_plural = "Bildirishnomalar"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read']),
            models.Index(fields=['sent', 'is_approved']),
        ]

    def __str__(self) -> str:
        return f"{self.get_notification_type_display()} – {self.user.phone_number}"

    @property
    def priority_color(self) -> str:
        colors = {
            'low': '#6B7280', 'normal': '#4F46E5',
            'high': '#F59E0B', 'urgent': '#dc2626',
        }
        return colors.get(self.priority, '#6B7280')

    def mark_as_read(self):
        """O‘qilgan deb belgilash."""
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])

    def approve(self, user: CustomUser):
        """Tasdiqlash."""
        self.is_approved = True
        self.approved_by = user
        self.approved_at = timezone.now()
        self.save(update_fields=['is_approved', 'approved_by', 'approved_at'])


# ============================================================
# 26. SMS LOG
# ============================================================

class SMSLog(TimeStampedModel):
    """SMS jurnali."""

    STATUS_CHOICES = (
        ('pending', 'Kutilmoqda'),
        ('sent', 'Yuborildi'),
        ('failed', 'Xato'),
        ('delivered', 'Yetkazildi'),
    )

    notification = models.ForeignKey(
        Notification, on_delete=models.CASCADE,
        related_name='sms_logs', verbose_name="Bildirishnoma"
    )
    phone_number = models.CharField(max_length=17, verbose_name="Telefon raqam")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES,
        default='pending', verbose_name="Holat"
    )
    sent_at = models.DateTimeField(null=True, blank=True, verbose_name="Yuborilgan vaqt")
    provider_response = models.TextField(blank=True, verbose_name="Provayder javobi")
    error_message = models.TextField(blank=True, verbose_name="Xatolik xabari")
    retry_count = models.PositiveSmallIntegerField(default=0, verbose_name="Qayta urinishlar")
    cost = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal('0'),
        verbose_name="Narxi (so‘m)"
    )

    class Meta:
        verbose_name = "SMS jurnali"
        verbose_name_plural = "SMS jurnallari"
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', '-created_at'])]

    def __str__(self) -> str:
        return f"{self.phone_number} – {self.get_status_display()}"

    def mark_sent(self, response: str = ''):
        self.status = 'sent'
        self.sent_at = timezone.now()
        self.provider_response = response
        self.save()

    def mark_failed(self, error: str):
        self.status = 'failed'
        self.error_message = error
        self.retry_count = F('retry_count') + 1
        self.save()


# ============================================================
# 27. LESSON QUESTION
# ============================================================

class LessonQuestion(TimeStampedModel):
    """Dars uchun savol (ota-ona uchun)."""

    lesson = models.ForeignKey(
        Lesson, on_delete=models.CASCADE,
        related_name='questions', verbose_name="Dars"
    )
    question_text = models.TextField(verbose_name="Savol matni")
    answer_text = models.TextField(
        blank=True, null=True, verbose_name="To‘g‘ri javob"
    )
    order = models.PositiveIntegerField(default=0, verbose_name="Tartib")
    points = models.PositiveSmallIntegerField(default=1, verbose_name="Ball")
    is_active = models.BooleanField(default=True, verbose_name="Aktiv")

    class Meta:
        verbose_name = "Dars savoli"
        verbose_name_plural = "Dars savollari"
        ordering = ['order', 'id']

    def __str__(self) -> str:
        return f"{self.lesson.title}: {self.question_text[:50]}"


# ============================================================
# 28. PARENT QUESTION REQUEST
# ============================================================

class ParentQuestionRequest(TimeStampedModel):
    """Ota-ona savollarni ko‘rish uchun so‘rov."""

    STATUS_CHOICES = (
        ('pending', 'Kutilmoqda'),
        ('approved', 'Tasdiqlangan'),
        ('rejected', 'Rad etilgan'),
    )

    parent = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE,
        related_name='question_requests', verbose_name="Ota-ona",
        limit_choices_to={'role': 'parent'}
    )
    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE,
        related_name='question_requests', verbose_name="Talaba"
    )
    lesson = models.ForeignKey(
        Lesson, on_delete=models.CASCADE,
        related_name='question_requests', verbose_name="Dars"
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='pending',
        verbose_name="Holat", db_index=True
    )
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name="Tasdiqlangan vaqt")
    approved_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='approved_requests', verbose_name="Kim tasdiqladi"
    )
    rejection_reason = models.TextField(blank=True, verbose_name="Rad etish sababi")

    class Meta:
        unique_together = ('parent', 'student', 'lesson')
        verbose_name = "Ota-ona savol so‘rovi"
        verbose_name_plural = "Ota-ona savol so‘rovlari"
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f"{self.parent.phone_number} → {self.lesson.title} ({self.get_status_display()})"

    def approve(self, user: CustomUser):
        self.status = 'approved'
        self.approved_at = timezone.now()
        self.approved_by = user
        self.save()

    def reject(self, reason: str = ''):
        self.status = 'rejected'
        self.rejection_reason = reason
        self.save()


# ============================================================
# 29. ACHIEVEMENT (Yutuqlar) – YANGI
# ============================================================

class Achievement(TimeStampedModel):
    """Yutuq belgisi."""

    ACHIEVEMENT_TYPES = (
        ('first_test', 'Birinchi test'),
        ('perfect_score', 'Mukammal natija'),
        ('streak_7', '7 kunlik streak'),
        ('streak_30', '30 kunlik streak'),
        ('top_student', 'Eng yaxshi talaba'),
        ('course_complete', 'Kurs tugatildi'),
        ('coins_1000', '1000 coin'),
        ('helper', 'Yordamchi'),
        ('custom', 'Boshqa'),
    )

    RARITY_CHOICES = (
        ('common', 'Oddiy'),
        ('rare', 'Kam uchraydigan'),
        ('epic', 'Epik'),
        ('legendary', 'Afsonaviy'),
    )

    name = models.CharField(max_length=100, unique=True, verbose_name="Nomi")
    description = models.TextField(blank=True, verbose_name="Tavsif")
    achievement_type = models.CharField(
        max_length=30, choices=ACHIEVEMENT_TYPES, verbose_name="Turi"
    )
    rarity = models.CharField(
        max_length=20, choices=RARITY_CHOICES,
        default='common', verbose_name="Noyobligi"
    )
    icon = models.CharField(max_length=100, default='fas fa-trophy', verbose_name="Ikonka")
    coins_reward = models.PositiveIntegerField(default=0, verbose_name="Coin mukofoti")
    points_reward = models.PositiveIntegerField(default=0, verbose_name="Ball mukofoti")
    condition_value = models.PositiveIntegerField(
        default=0, verbose_name="Shart qiymati"
    )
    is_active = models.BooleanField(default=True, verbose_name="Aktiv")

    class Meta:
        verbose_name = "Yutuq"
        verbose_name_plural = "Yutuqlar"
        ordering = ['rarity', 'name']

    def __str__(self) -> str:
        return f"{self.name} ({self.get_rarity_display()})"

    @property
    def rarity_color(self) -> str:
        colors = {
            'common': '#6B7280',
            'rare': '#0284c7',
            'epic': '#7C3AED',
            'legendary': '#F59E0B',
        }
        return colors.get(self.rarity, '#6B7280')


class StudentAchievement(TimeStampedModel):
    """Talaba olgan yutuqlar."""

    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE,
        related_name='achievements', verbose_name="Talaba"
    )
    achievement = models.ForeignKey(
        Achievement, on_delete=models.CASCADE,
        related_name='students', verbose_name="Yutuq"
    )
    unlocked_at = models.DateTimeField(auto_now_add=True, verbose_name="Ochilgan vaqt")
    progress = models.PositiveSmallIntegerField(default=100, verbose_name="Progress (%)")

    class Meta:
        unique_together = ('student', 'achievement')
        verbose_name = "Talaba yutug‘i"
        verbose_name_plural = "Talaba yutuqlari"
        ordering = ['-unlocked_at']

    def __str__(self) -> str:
        return f"{self.student.user.get_full_name()} – {self.achievement.name}"


# ============================================================
# 30. COIN TRANSACTION – YANGI
# ============================================================

class CoinTransaction(TimeStampedModel):
    """Coin tranzaksiyasi (kirim/chiqim)."""

    TRANSACTION_TYPES = (
        ('earn', 'Topildi'),
        ('spend', 'Sarflandi'),
        ('bonus', 'Bonus'),
        ('penalty', 'Jarima'),
        ('refund', 'Qaytarildi'),
    )

    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE,
        related_name='coin_transactions', verbose_name="Talaba"
    )
    amount = models.IntegerField(verbose_name="Miqdor")
    transaction_type = models.CharField(
        max_length=20, choices=TRANSACTION_TYPES, verbose_name="Turi"
    )
    reason = models.CharField(max_length=255, verbose_name="Sabab")
    balance_after = models.PositiveIntegerField(verbose_name="Keyingi balans")
    related_object_id = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="Bog‘liq obyekt ID"
    )

    class Meta:
        verbose_name = "Coin tranzaksiyasi"
        verbose_name_plural = "Coin tranzaksiyalari"
        ordering = ['-created_at']
        indexes = [models.Index(fields=['student', '-created_at'])]

    def __str__(self) -> str:
        sign = '+' if self.amount > 0 else ''
        return f"{self.student.user.get_full_name()}: {sign}{self.amount} ({self.reason})"


# ============================================================
# 31. PAYMENT – YANGI
# ============================================================

class Payment(TimeStampedModel):
    """To‘lov tranzaksiyasi."""

    PAYMENT_TYPES = (
        ('deposit', 'Depozit'),
        ('withdraw', 'Yechib olish'),
        ('course', 'Kurs to‘lovi'),
        ('refund', 'Qaytarish'),
    )

    STATUS_CHOICES = (
        ('pending', 'Kutilmoqda'),
        ('completed', 'Yakunlangan'),
        ('failed', 'Muvaffaqiyatsiz'),
        ('cancelled', 'Bekor qilingan'),
    )

    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE,
        related_name='payments', verbose_name="Talaba"
    )
    amount = models.DecimalField(
        max_digits=12, decimal_places=2, verbose_name="Miqdor (so‘m)"
    )
    payment_type = models.CharField(
        max_length=20, choices=PAYMENT_TYPES, verbose_name="Turi"
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES,
        default='pending', verbose_name="Holat"
    )
    reason = models.CharField(max_length=255, blank=True, verbose_name="Sabab")
    transaction_id = models.CharField(
        max_length=100, blank=True, null=True, unique=True, verbose_name="Tranzaksiya ID"
    )
    provider = models.CharField(max_length=50, blank=True, verbose_name="To‘lov tizimi")
    course = models.ForeignKey(
        Course, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Kurs"
    )

    class Meta:
        verbose_name = "To‘lov"
        verbose_name_plural = "To‘lovlar"
        ordering = ['-created_at']
        indexes = [models.Index(fields=['student', '-created_at'])]

    def __str__(self) -> str:
        return f"{self.student.user.get_full_name()}: {self.amount} so‘m ({self.get_status_display()})"

    def complete(self, transaction_id: str = ''):
        self.status = 'completed'
        if transaction_id:
            self.transaction_id = transaction_id
        self.save()


# ============================================================
# 32. ANNOUNCEMENT – YANGI
# ============================================================

class Announcement(TimeStampedModel):
    """E’lonlar."""

    PRIORITY_CHOICES = (
        ('low', 'Past'),
        ('normal', 'O‘rta'),
        ('high', 'Yuqori'),
        ('urgent', 'Shoshilinch'),
    )

    title = models.CharField(max_length=255, verbose_name="Sarlavha")
    content = models.TextField(verbose_name="Kontent")
    author = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE,
        related_name='announcements', verbose_name="Muallif"
    )
    priority = models.CharField(
        max_length=10, choices=PRIORITY_CHOICES,
        default='normal', verbose_name="Muhimlik"
    )
    target_roles = models.CharField(
        max_length=100, blank=True,
        help_text="Vergul bilan ajratilgan rollar: student,teacher,parent",
        verbose_name="Maqsadli rollar"
    )
    publish_at = models.DateTimeField(default=timezone.now, verbose_name="E’lon vaqti")
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name="Tugash vaqti")
    is_active = models.BooleanField(default=True, verbose_name="Aktiv")
    is_pinned = models.BooleanField(default=False, verbose_name="Qadalgan")

    class Meta:
        verbose_name = "E’lon"
        verbose_name_plural = "E’lonlar"
        ordering = ['-is_pinned', '-publish_at']

    def __str__(self) -> str:
        return self.title

    @property
    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        return timezone.now() > self.expires_at

    @property
    def is_published(self) -> bool:
        return self.is_active and self.publish_at <= timezone.now() and not self.is_expired


# ============================================================
# 33. FEEDBACK – YANGI
# ============================================================

class Feedback(TimeStampedModel):
    """Fikr-mulohazalar."""

    FEEDBACK_TYPES = (
        ('complaint', 'Shikoyat'),
        ('suggestion', 'Taklif'),
        ('bug', 'Xatolik'),
        ('praise', 'Maqtov'),
        ('other', 'Boshqa'),
    )

    STATUS_CHOICES = (
        ('new', 'Yangi'),
        ('in_progress', 'Ko‘rib chiqilmoqda'),
        ('resolved', 'Hal qilindi'),
        ('closed', 'Yopildi'),
    )

    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE,
        related_name='feedbacks', verbose_name="Foydalanuvchi"
    )
    feedback_type = models.CharField(
        max_length=20, choices=FEEDBACK_TYPES, verbose_name="Turi"
    )
    subject = models.CharField(max_length=255, verbose_name="Mavzu")
    message = models.TextField(verbose_name="Xabar")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES,
        default='new', verbose_name="Holat"
    )
    response = models.TextField(blank=True, verbose_name="Javob")
    responded_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='responded_feedbacks', verbose_name="Kim javob berdi"
    )
    responded_at = models.DateTimeField(null=True, blank=True, verbose_name="Javob vaqti")

    class Meta:
        verbose_name = "Fikr-mulohaza"
        verbose_name_plural = "Fikr-mulohazalar"
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f"{self.user.phone_number} – {self.subject}"

    def respond(self, message: str, user: CustomUser):
        self.response = message
        self.responded_by = user
        self.responded_at = timezone.now()
        self.status = 'resolved'
        self.save()


# ============================================================
# SIGNALS
# ============================================================

@receiver(post_save, sender=CustomUser)
def create_user_profile(sender, instance, created, **kwargs):
    """Yangi foydalanuvchi ro‘yxatdan o‘tganda profil yaratish."""
    if not created:
        return
    if instance.role == 'student':
        StudentProfile.objects.get_or_create(user=instance)
    elif instance.role == 'teacher':
        TeacherProfile.objects.get_or_create(user=instance, defaults={'specialization': '—'})
    elif instance.role == 'manager':
        ManagerProfile.objects.get_or_create(user=instance)


@receiver(post_save, sender=CustomUser)
def save_user_profile(sender, instance, **kwargs):
    """Profilni avtomatik saqlash."""
    if instance.role == 'student' and hasattr(instance, 'student_profile'):
        instance.student_profile.save()
    elif instance.role == 'teacher' and hasattr(instance, 'teacher_profile'):
        instance.teacher_profile.save()
    elif instance.role == 'manager' and hasattr(instance, 'manager_profile'):
        instance.manager_profile.save()


@receiver(post_save, sender=QuizCategory)
def set_category_slug(sender, instance, **kwargs):
    """Kategoriya slug ni avtomatik o‘rnatish."""
    if not instance.slug:
        instance.slug = slugify(instance.name)
        QuizCategory.objects.filter(pk=instance.pk).update(slug=instance.slug)


@receiver(post_save, sender=TestResult)
def award_quiz_achievements(sender, instance, created, **kwargs):
    """Test natijasiga qarab yutuq berish."""
    if not created:
        return
    student = instance.student

    # Birinchi test
    if student.test_results.count() == 1:
        achievement = Achievement.objects.filter(achievement_type='first_test').first()
        if achievement:
            StudentAchievement.objects.get_or_create(
                student=student, achievement=achievement
            )

    # Mukammal natija
    if instance.percentage == 100:
        achievement = Achievement.objects.filter(achievement_type='perfect_score').first()
        if achievement:
            StudentAchievement.objects.get_or_create(
                student=student, achievement=achievement
            )


@receiver(post_save, sender=Submission)
def award_submission_coins(sender, instance, created, **kwargs):
    """Topshiriq baholanganda coin berish."""
    if instance.is_graded and instance.coins_awarded > 0:
        # Coin berilganini tekshirish
        already = CoinTransaction.objects.filter(
            student=instance.student,
            related_object_id=instance.pk,
            transaction_type='earn',
        ).exists()
        if not already:
            instance.student.add_coins(
                instance.coins_awarded,
                reason=f"Topshiriq: {instance.assignment.task.title}"
            )
# ═══════════════════════════════════════════════════════════════
# TELEGRAM LINK — Telegram hisobini bog‘lash
# ═══════════════════════════════════════════════════════════════

class TelegramLink(TimeStampedModel):
    """Foydalanuvchi Telegram hisobini tizimga bog‘lash."""

    user = models.OneToOneField(
        CustomUser, on_delete=models.CASCADE,
        related_name='telegram_link', verbose_name="Foydalanuvchi"
    )
    chat_id = models.BigIntegerField(
        unique=True, db_index=True, verbose_name="Chat ID"
    )
    username = models.CharField(
        max_length=100, blank=True, null=True, verbose_name="Username"
    )
    first_name = models.CharField(
        max_length=100, blank=True, null=True, verbose_name="Telegram ismi"
    )
    is_active = models.BooleanField(default=True, verbose_name="Aktiv")
    linked_at = models.DateTimeField(
        auto_now_add=True, verbose_name="Bog‘langan vaqt"
    )
    last_login = models.DateTimeField(
        null=True, blank=True, verbose_name="Oxirgi kirish"
    )

    class Meta:
        verbose_name = "Telegram bog‘lanish"
        verbose_name_plural = "Telegram bog‘lanishlar"
        ordering = ['-linked_at']

    def __str__(self):
        return f"{self.user.phone_number} → {self.chat_id}"

# ═══════════════════════════════════════════════════════════════
# TELEGRAM NOTIFICATION TIZIMI
# ═══════════════════════════════════════════════════════════════


class TelegramNotificationTemplate(TimeStampedModel):
    """
    Avtomatik xabar shablonlari (motivatsiya, eslatma, savol).
    """
    TRIGGER_CHOICES = (
        ('welcome_back', 'Qaytib kelganda'),
        ('inactive_4h', '4 soat kirmaganda'),
        ('inactive_7h', '7 soat kirmaganda'),
        ('inactive_1d', '1 kun kirmaganda'),
        ('inactive_3d', '3 kun kirmaganda'),
        ('late_night', 'Kechqurun (22:00+)'),
        ('morning_boost', 'Ertalab (07:00)'),
        ('course_start', 'Kurs boshlanganda'),
        ('course_end', 'Kurs tugaganda'),
        ('achievement', 'Yutuq olganda'),
        ('login_telegram', 'Telegram orqali kirgan'),
        ('custom', 'Boshqa'),
    )

    # ⚠️ DIQQAT: field nomi kichik harfda!
    trigger = models.CharField(
        max_length=30,
        choices=TRIGGER_CHOICES,
        unique=True,
        verbose_name="Trigger",
    )
    title = models.CharField(max_length=200, verbose_name="Sarlavha")
    message = models.TextField(
        verbose_name="Xabar matni",
        help_text="HTML format: <b>qalin</b>, <i>kursiv</i>, <code>kod</code>",
    )
    emoji = models.CharField(max_length=10, default='📚', verbose_name="Emoji")
    button_text = models.CharField(
        max_length=50, blank=True, null=True, verbose_name="Tugma matni"
    )
    button_url = models.CharField(
        max_length=255, blank=True, null=True, verbose_name="Tugma havolasi"
    )
    is_active = models.BooleanField(default=True, verbose_name="Aktiv")

    class Meta:
        verbose_name = "Telegram xabar shabloni"
        verbose_name_plural = "Telegram xabar shablonlari"
        ordering = ['trigger']

    def __str__(self):
        return f"{self.get_trigger_display()} → {self.title}"

class StudyQuestion(TimeStampedModel):
    """
    Foydalanuvchiga Telegram orqali yuboriladigan savollar.
    Backend orqali tahrirlanadi.
    """
    CATEGORY_CHOICES = (
        ('motivation', 'Motivatsiya'),
        ('quiz', 'Test savoli'),
        ('daily', 'Kunlik savol'),
        ('feedback', 'Fikr-mulohaza'),
        ('custom', 'Boshqa'),
    )

    category = models.CharField(
        max_length=20, choices=CATEGORY_CHOICES, default='motivation',
        verbose_name="Kategoriya"
    )
    question = models.TextField(verbose_name="Savol matni")
    options = models.JSONField(
        default=list, blank=True,
        verbose_name="Variantlar",
        help_text='JSON array: ["Variant 1", "Variant 2"]'
    )
    correct_index = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name="To‘g‘ri javob raqami (0-4)"
    )
    hint = models.TextField(blank=True, null=True, verbose_name="Yordam")
    is_active = models.BooleanField(default=True, verbose_name="Aktiv")
    order = models.PositiveIntegerField(default=0, verbose_name="Tartib")
    used_count = models.PositiveIntegerField(default=0, verbose_name="Ishlatilgan")

    class Meta:
        verbose_name = "O‘quv savoli"
        verbose_name_plural = "O‘quv savollari"
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.get_category_display()}: {self.question[:50]}"


class TelegramNotificationLog(TimeStampedModel):
    """
    Telegram xabarlari tarixi — kim, qachon, nima yuborilgan.
    """
    STATUS_CHOICES = (
        ('pending', 'Kutilmoqda'),
        ('sent', 'Yuborildi'),
        ('failed', 'Xatolik'),
        ('delivered', 'Yetkazildi'),
    )

    TRIGGER_CHOICES = TelegramNotificationTemplate.TRIGGER_CHOICES + (
        ('admin_login_alert', 'Admin: login xabari'),
        ('admin_telegram_login', 'Admin: Telegram orqali kirish'),
        ('admin_custom_sms', 'Admin: qo‘lda SMS'),
    )

    recipient = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE,
        related_name='tg_notifications', verbose_name="Qabul qiluvchi"
    )
    trigger = models.CharField(
        max_length=30, choices=TRIGGER_CHOICES,
        verbose_name="Trigger", db_index=True
    )
    message = models.TextField(verbose_name="Yuborilgan xabar")
    chat_id = models.BigIntegerField(verbose_name="Chat ID")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='pending',
        verbose_name="Holat"
    )
    is_read = models.BooleanField(default=False, verbose_name="O‘qilgan")
    sent_at = models.DateTimeField(auto_now_add=True, verbose_name="Yuborilgan")
    delivered_at = models.DateTimeField(null=True, blank=True, verbose_name="Yetkazilgan")
    error_message = models.TextField(blank=True, verbose_name="Xato")
    sent_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='sent_tg_notifications', verbose_name="Kim yubordi"
    )

    class Meta:
        verbose_name = "Telegram xabar tarixi"
        verbose_name_plural = "Telegram xabarlar tarixi"
        ordering = ['-sent_at']
        indexes = [
            models.Index(fields=['recipient', '-sent_at']),
            models.Index(fields=['trigger', '-sent_at']),
        ]

    def __str__(self):
        return f"{self.recipient.phone_number} ← {self.get_trigger_display()}"
