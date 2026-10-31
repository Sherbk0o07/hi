"""
LearnCraft – Admin Panel Configuration
========================================
Professional admin panel for the new models.py (v2.0)
"""

import csv
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.utils.html import format_html, mark_safe
from django.urls import reverse, NoReverseMatch
from django.db.models import Count, Sum, Avg, Q, F
from django.utils import timezone
from django.http import HttpResponse
from datetime import timedelta


# ═══ LearnCraft modellari (apps.user app) ═══
from apps.user.models.user import (
    # User va profillar
    CustomUser, RegistrationKey, StudentProfile, TeacherProfile, ManagerProfile,
    # Quiz (LearnCraft versiyalari)
    QuizCategory, Quiz, Question, AnswerOption,
    TestResult, TestResultAnswer,
    StudentQuizAccess, StudentGroup, GroupQuizAccess,
    # Menu
    MenuSection, MenuItem,
    # Kurslar (LearnCraft versiyalari)
    Course, Lesson, Task, Assignment, Submission,
    # Activity
    ActivityLog, Notification, SMSLog,
    # Lesson Questions
    LessonQuestion, ParentQuestionRequest,
    # Telegram
    TelegramLink, TelegramNotificationTemplate, StudyQuestion, TelegramNotificationLog,
    # Achievement
    Achievement, StudentAchievement, CoinTransaction, Payment, Announcement, Feedback,
)


# ============================================================
# YORDAMCHI FUNKSIYALAR
# ============================================================

def badge(text: str, color: str = "#6B7280", icon: str = "") -> str:
    """Rangli badge yaratish."""
    return format_html(
        '<span style="background:{};color:#fff;padding:3px 10px;'
        'border-radius:999px;font-size:11px;font-weight:600;">{}{}</span>',
        color, f"{icon} " if icon else "", text
    )


def status_dot(text: str, color: str) -> str:
    """Status nuqtasi bilan."""
    return format_html(
        '<span style="color:{};font-weight:600;">● {}</span>',
        color, text
    )


# ============================================================
# 1. CUSTOM USER ADMIN
# ============================================================

class StudentProfileInline(admin.StackedInline):
    model = StudentProfile
    can_delete = False
    verbose_name_plural = "Talaba profili"
    fk_name = 'user'
    fields = (
        'birth_date', 'parent_phone', 'status',
        'balance', 'coins', 'level',
        'experience_points', 'streak_days', 'notes'
    )
    classes = ('collapse',)


class TeacherProfileInline(admin.StackedInline):
    model = TeacherProfile
    can_delete = False
    verbose_name_plural = "O‘qituvchi profili"
    fk_name = 'user'
    fields = (
        'specialization', 'experiance', 'education',
        'fixed_salary', 'salary_percentage', 'rating', 'bio'
    )
    classes = ('collapse',)


class ManagerProfileInline(admin.StackedInline):
    model = ManagerProfile
    can_delete = False
    verbose_name_plural = "Menejer profili"
    fk_name = 'user'
    classes = ('collapse',)


class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = ('phone_number', 'first_name', 'last_name', 'role')


class CustomUserChangeForm(UserChangeForm):
    class Meta:
        model = CustomUser
        fields = '__all__'


@admin.register(CustomUser)
class CustomUserAdmin(BaseUserAdmin):
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    model = CustomUser

    list_display = (
        'avatar_preview', 'phone_number', 'full_name_display',
        'role_badge', 'is_active_badge', 'is_online_badge', 'date_joined'
    )
    list_filter = (
        'role', 'is_active', 'is_staff', 'is_superuser',
        'language', 'date_joined'
    )
    search_fields = ('phone_number', 'first_name', 'last_name', 'middle_name', 'email')
    ordering = ('-date_joined',)
    list_per_page = 30
    date_hierarchy = 'date_joined'
    list_select_related = True

    fieldsets = (
        (None, {'fields': ('phone_number', 'password')}),
        ('Shaxsiy ma’lumotlar', {
            'fields': ('first_name', 'last_name', 'middle_name', 'avatar', 'email')
        }),
        ('Rol va ruxsatlar', {
            'fields': ('role', 'is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        ('Sozlamalar', {
            'fields': ('language', 'timezone', 'last_login_ip'),
            'classes': ('collapse',)
        }),
        ('Muhim sanalar', {
            'fields': ('last_login', 'date_joined'),
            'classes': ('collapse',)
        }),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('phone_number', 'first_name', 'last_name', 'role', 'password1', 'password2'),
        }),
    )

    inlines = [StudentProfileInline, TeacherProfileInline, ManagerProfileInline]
    readonly_fields = ('date_joined', 'last_login')

    actions = [
        'activate_users', 'deactivate_users',
        'make_students', 'make_teachers',
        'export_csv',
    ]

    @admin.display(description="Rasm")
    def avatar_preview(self, obj):
        if obj.avatar:
            return format_html(
                '<img src="{}" style="width:36px;height:36px;border-radius:50%;'
                'object-fit:cover;border:2px solid #e5e7eb;" />',
                obj.avatar.url
            )
        return format_html(
            '<div style="width:36px;height:36px;border-radius:50%;'
            'background:linear-gradient(135deg,#4F46E5,#7C3AED);color:#fff;'
            'display:flex;align-items:center;justify-content:center;'
            'font-weight:700;font-size:12px;">{}</div>',
            obj.initials
        )

    @admin.display(description="To‘liq ism", ordering='first_name')
    def full_name_display(self, obj):
        return obj.get_full_name() or "—"

    @admin.display(description="Rol", ordering='role')
    def role_badge(self, obj):
        colors = {
            'admin': '#7C3AED', 'manager': '#F59E0B',
            'teacher': '#06B6D4', 'student': '#4F46E5',
            'parent': '#F43F5E',
        }
        return badge(obj.get_role_display(), colors.get(obj.role, '#6B7280'))

    @admin.display(description="Holat", ordering='is_active')
    def is_active_badge(self, obj):
        return status_dot(
            "Aktiv" if obj.is_active else "Bloklangan",
            "#059669" if obj.is_active else "#dc2626"
        )

    @admin.display(description="Online", boolean=True)
    def is_online_badge(self, obj):
        return obj.is_online

    @admin.action(description="✅ Tanlanganlarni aktivlashtirish")
    def activate_users(self, request, queryset):
        n = queryset.update(is_active=True)
        self.message_user(request, f"{n} ta foydalanuvchi aktivlashtirildi.")

    @admin.action(description="🚫 Tanlanganlarni bloklash")
    def deactivate_users(self, request, queryset):
        n = queryset.update(is_active=False)
        self.message_user(request, f"{n} ta foydalanuvchi bloklandi.")

    @admin.action(description="🎓 'Talaba' rolini o‘rnatish")
    def make_students(self, request, queryset):
        n = queryset.update(role='student')
        self.message_user(request, f"{n} ta foydalanuvchi talaba qilindi.")

    @admin.action(description="👨‍🏫 'O‘qituvchi' rolini o‘rnatish")
    def make_teachers(self, request, queryset):
        n = queryset.update(role='teacher')
        self.message_user(request, f"{n} ta foydalanuvchi o‘qituvchi qilindi.")

    @admin.action(description="📥 CSV formatda eksport")
    def export_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="users.csv"'
        response.write('\ufeff')  # BOM for Excel
        writer = csv.writer(response)
        writer.writerow(['Telefon', 'Ism', 'Familiya', 'Sharif', 'Rol', 'Aktiv', 'Sana'])
        for u in queryset:
            writer.writerow([
                u.phone_number, u.first_name, u.last_name,
                u.middle_name or '', u.role, u.is_active, u.date_joined
            ])
        return response

#
# ============================================================
# 2. REGISTRATION KEY ADMIN
# ============================================================

@admin.register(RegistrationKey)
class RegistrationKeyAdmin(admin.ModelAdmin):
    list_display = (
        'key', 'is_active', 'usage_limit', 'used_count',
        'is_valid_badge', 'expires_at', 'created_at'
    )
    list_filter = ('is_active', 'created_at', 'expires_at')
    search_fields = ('key',)
    readonly_fields = ('created_at', 'updated_at', 'used_count')
    ordering = ('-created_at',)
    autocomplete_fields = ('created_by',)
    actions = ['activate_keys', 'deactivate_keys']

    fieldsets = (
        ('Asosiy', {'fields': ('key', 'is_active', 'created_by')}),
        ('Limitlar', {'fields': ('usage_limit', 'used_count', 'expires_at')}),
        ('Sanalar', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    @admin.display(description="Yaroqli?")
    def is_valid_badge(self, obj):
        if obj.is_valid:
            return status_dot("Ha", "#059669")
        return status_dot("Yo‘q", "#dc2626")

    @admin.action(description="✅ Aktivlashtirish")
    def activate_keys(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description="🚫 O‘chirish")
    def deactivate_keys(self, request, queryset):
        queryset.update(is_active=False)


# ============================================================
# 3. STUDENT PROFILE ADMIN
# ============================================================

class CoinTransactionInline(admin.TabularInline):
    model = CoinTransaction
    extra = 0
    fields = ('amount', 'transaction_type', 'reason', 'balance_after', 'created_at')
    readonly_fields = ('created_at',)
    can_delete = False
    max_num = 10


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    fields = ('amount', 'payment_type', 'status', 'reason', 'created_at')
    readonly_fields = ('created_at',)
    can_delete = False
    max_num = 10


class StudentAchievementInline(admin.TabularInline):
    model = StudentAchievement
    extra = 0
    fields = ('achievement', 'progress', 'unlocked_at')
    readonly_fields = ('unlocked_at',)
    autocomplete_fields = ('achievement',)
    max_num = 10


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = (
        'user', 'status_badge', 'balance_display',
        'coins_display', 'level_badge', 'streak_display',
        'groups_count', 'parent_phone'
    )
    list_filter = ('status', 'level', 'created_at')
    search_fields = (
        'user__phone_number', 'user__first_name',
        'user__last_name', 'parent_phone'
    )
    autocomplete_fields = ('user',)
    list_per_page = 30
    list_editable = ()
    readonly_fields = (
        'created_at', 'updated_at', 'last_activity',
        'total_tests_display', 'total_score_display',
        'average_score_display', 'completion_rate_display'
    )
    inlines = [StudentAchievementInline, CoinTransactionInline, PaymentInline]

    fieldsets = (
        ('Foydalanuvchi', {'fields': ('user',)}),
        ('Shaxsiy ma’lumotlar', {'fields': ('birth_date', 'parent_phone', 'notes')}),
        ('Moliya', {'fields': ('balance', 'coins')}),
        ('Gamifikatsiya', {
            'fields': ('level', 'experience_points', 'streak_days', 'last_activity')
        }),
        ('Holat', {'fields': ('status',)}),
        ('Statistika', {
            'fields': (
                'total_tests_display', 'total_score_display',
                'average_score_display', 'completion_rate_display'
            ),
            'classes': ('collapse',)
        }),
        ('Sanalar', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    actions = [
        'freeze_students', 'activate_students',
        'add_100_coins', 'add_500_coins',
        'level_up', 'export_csv',
    ]

    @admin.display(description="Holat", ordering='status')
    def status_badge(self, obj):
        colors = {
            'active': '#059669', 'frozen': '#0284c7',
            'graduated': '#7C3AED', 'dropped': '#dc2626',
        }
        return badge(obj.get_status_display(), colors.get(obj.status, '#6B7280'))

    @admin.display(description="Balans", ordering='balance')
    def balance_display(self, obj):
        return format_html(
            '<span style="font-weight:600;">{:,.0f} so‘m</span>', obj.balance
        )

    @admin.display(description="Coinlar", ordering='coins')
    def coins_display(self, obj):
        return format_html(
            '<span style="color:#F59E0B;font-weight:700;">🪙 {}</span>', obj.coins
        )

    @admin.display(description="Daraja", ordering='level')
    def level_badge(self, obj):
        return badge(f"Lv. {obj.level}", "#7C3AED")

    @admin.display(description="Streak", ordering='streak_days')
    def streak_display(self, obj):
        return format_html(
            '<span style="color:#dc2626;font-weight:600;">🔥 {}</span>',
            obj.streak_days
        )

    @admin.display(description="Guruhlar")
    def groups_count(self, obj):
        return obj.groups.count()

    @admin.display(description="Testlar soni")
    def total_tests_display(self, obj):
        return obj.total_tests

    @admin.display(description="Umumiy ball")
    def total_score_display(self, obj):
        return obj.total_score

    @admin.display(description="O‘rtacha ball")
    def average_score_display(self, obj):
        return f"{obj.average_score}"

    @admin.display(description="Tugatish foizi")
    def completion_rate_display(self, obj):
        pct = obj.completion_rate
        color = '#059669' if pct >= 70 else '#F59E0B' if pct >= 40 else '#dc2626'
        return format_html(
            '<span style="color:{};font-weight:600;">{}%</span>', color, pct
        )

    @admin.action(description="🧊 Muzlatish")
    def freeze_students(self, request, queryset):
        n = queryset.update(status='frozen')
        self.message_user(request, f"{n} ta talaba muzlatildi.")

    @admin.action(description="✅ Aktivlashtirish")
    def activate_students(self, request, queryset):
        n = queryset.update(status='active')
        self.message_user(request, f"{n} ta talaba aktivlashtirildi.")

    @admin.action(description="🪙 100 coin qo‘shish")
    def add_100_coins(self, request, queryset):
        for s in queryset:
            s.add_coins(100, reason="Admin panel orqali")
        self.message_user(request, f"{queryset.count()} ta talabaga 100 coin qo‘shildi.")

    @admin.action(description="🪙 500 coin qo‘shish")
    def add_500_coins(self, request, queryset):
        for s in queryset:
            s.add_coins(500, reason="Admin panel orqali")
        self.message_user(request, f"{queryset.count()} ta talabaga 500 coin qo‘shildi.")

    @admin.action(description="⬆️ Darajani oshirish")
    def level_up(self, request, queryset):
        n = queryset.update(level=F('level') + 1)
        self.message_user(request, f"{n} ta talabaning darajasi oshirildi.")

    @admin.action(description="📥 CSV eksport")
    def export_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="students.csv"'
        response.write('\ufeff')
        writer = csv.writer(response)
        writer.writerow(['Ism', 'Telefon', 'Holat', 'Balans', 'Coinlar', 'Daraja'])
        for s in queryset:
            writer.writerow([
                s.user.get_full_name(), s.user.phone_number,
                s.status, s.balance, s.coins, s.level
            ])
        return response


# ============================================================
# 4. TEACHER PROFILE ADMIN
# ============================================================

@admin.register(TeacherProfile)
class TeacherProfileAdmin(admin.ModelAdmin):
    list_display = (
        'user', 'specialization', 'experiance_years',
        'fixed_salary_display', 'salary_percentage_display',
        'rating_badge', 'average_rating'
    )
    list_filter = ('experiance', 'specialization', 'rating')
    search_fields = (
        'user__phone_number', 'user__first_name',
        'user__last_name', 'specialization'
    )
    autocomplete_fields = ('user',)
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        ('Foydalanuvchi', {'fields': ('user',)}),
        ('Kasbiy', {'fields': ('specialization', 'experiance', 'education')}),
        ('Moliya', {'fields': ('fixed_salary', 'salary_percentage')}),
        ('Reyting', {'fields': ('rating', 'average_rating')}),
        ('Qo‘shimcha', {'fields': ('bio', 'certificates')}),
        ('Sanalar', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    @admin.display(description="Tajriba")
    def experiance_years(self, obj):
        return f"{obj.experiance} yil"

    @admin.display(description="Oylik")
    def fixed_salary_display(self, obj):
        if not obj.fixed_salary:
            return "—"
        return f"{obj.fixed_salary:,.0f} so‘m"

    @admin.display(description="Foiz")
    def salary_percentage_display(self, obj):
        return f"{obj.salary_percentage}%"

    @admin.display(description="Reyting")
    def rating_badge(self, obj):
        r = float(obj.rating)
        color = '#059669' if r >= 4 else '#F59E0B' if r >= 3 else '#dc2626'
        return format_html(
            '<span style="color:{};font-weight:700;">★ {}</span>', color, r
        )


# ============================================================
# 5. MANAGER PROFILE ADMIN
# ============================================================

@admin.register(ManagerProfile)
class ManagerProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'branch', 'permissions_level')
    list_filter = ('permissions_level', 'branch')
    search_fields = ('user__phone_number', 'user__first_name', 'branch')
    autocomplete_fields = ('user',)
    readonly_fields = ('created_at', 'updated_at')


# ============================================================
# 6. QUIZ CATEGORY ADMIN
# ============================================================

@admin.register(QuizCategory)
class QuizCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'icon_preview', 'order', 'is_active', 'quizzes_count')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'slug', 'description')
    prepopulated_fields = {'slug': ('name',)}
    list_editable = ('order', 'is_active')
    ordering = ('order', 'name')
    readonly_fields = ('created_at', 'updated_at')

    @admin.display(description="Ikonka")
    def icon_preview(self, obj):
        return format_html(
            '<i class="{}" style="color:{};font-size:20px;"></i>',
            obj.icon, obj.color
        )

    @admin.display(description="Testlar")
    def quizzes_count(self, obj):
        return obj.total_quizzes


# ============================================================
# 7. ANSWER OPTION INLINE
# ============================================================

class AnswerOptionInline(admin.TabularInline):
    model = AnswerOption
    extra = 4
    min_num = 2
    max_num = 8
    fields = ('text', 'is_correct', 'order')
    ordering = ('order',)


# ============================================================
# 8. QUESTION INLINE (for Quiz)
# ============================================================

class QuestionInline(admin.StackedInline):
    model = Question
    extra = 1
    show_change_link = True
    fields = ('text', 'image', 'points', 'order', 'explanation')
    classes = ('collapse',)


# ============================================================
# 9. QUIZ ADMIN
# ============================================================



# ============================================================
# 10. QUESTION ADMIN
# ============================================================



# ============================================================
# 11. ANSWER OPTION ADMIN
# ============================================================


# ============================================================
# 12. TEST RESULT ANSWER INLINE
# ============================================================

class TestResultAnswerInline(admin.TabularInline):
    model = TestResultAnswer
    extra = 0
    readonly_fields = ('question', 'selected_option', 'is_correct')
    can_delete = False
    max_num = 100


# ============================================================
# 13. TEST RESULT ADMIN
# ============================================================

@admin.register(TestResult)
class TestResultAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'student', 'quiz', 'score_display',
        'percentage_display', 'grade_badge',
        'coins_awarded', 'time_spent_display', 'taken_at'
    )
    list_filter = ('quiz', 'taken_at', 'coins_awarded')
    search_fields = (
        'student__user__phone_number',
        'student__user__first_name',
        'quiz__title'
    )
    ordering = ('-taken_at',)
    readonly_fields = (
        'taken_at', 'percentage_display',
        'grade_display', 'time_spent_display',
        'wrong_answers_display'
    )
    date_hierarchy = 'taken_at'
    list_per_page = 40
    inlines = [TestResultAnswerInline]
    raw_id_fields = ('student', 'quiz')

    fieldsets = (
        ('Asosiy', {'fields': ('student', 'quiz')}),
        ('Natija', {
            'fields': (
                'correct_answers', 'total_score', 'coins_awarded',
                'attempt_number', 'time_spent_seconds'
            )
        }),
        ('Hisoblangan', {
            'fields': (
                'percentage_display', 'grade_display',
                'time_spent_display', 'wrong_answers_display'
            )
        }),
        ('Sana', {'fields': ('taken_at',), 'classes': ('collapse',)}),
    )

    @admin.display(description="Ball", ordering='total_score')
    def score_display(self, obj):
        return f"{obj.total_score} / {obj.quiz.max_score}"

    @admin.display(description="Foiz")
    def percentage_display(self, obj):
        pct = obj.percentage
        color = '#059669' if pct >= 70 else '#F59E0B' if pct >= 50 else '#dc2626'
        return format_html(
            '<span style="color:{};font-weight:700;">{}%</span>', color, pct
        )

    @admin.display(description="Baho")
    def grade_badge(self, obj):
        colors = {'A': '#059669', 'B': '#0284c7', 'C': '#F59E0B', 'D': '#d97706', 'F': '#dc2626'}
        return badge(obj.grade, colors.get(obj.grade, '#6B7280'))

    @admin.display(description="O‘tgan?")
    def grade_display(self, obj):
        if obj.is_passed:
            return status_dot("O‘tdi", "#059669")
        return status_dot("O‘tmadi", "#dc2626")

    @admin.display(description="Sarflangan vaqt")
    def time_spent_display(self, obj):
        return obj.time_spent_display

    @admin.display(description="Xato javoblar")
    def wrong_answers_display(self, obj):
        return obj.wrong_answers


# ============================================================
# 14. TEST RESULT ANSWER ADMIN
# ============================================================

@admin.register(TestResultAnswer)
class TestResultAnswerAdmin(admin.ModelAdmin):
    list_display = ('id', 'result', 'question', 'selected_option', 'is_correct_badge')
    list_filter = ('is_correct', 'created_at')
    search_fields = (
        'result__student__user__phone_number',
        'question__text'
    )
    raw_id_fields = ('result', 'question', 'selected_option')    
    readonly_fields = ('created_at', 'updated_at')

    @admin.display(description="To‘g‘ri?")
    def is_correct_badge(self, obj):
        if obj.is_correct:
            return status_dot("✓", "#059669")
        return status_dot("✗", "#dc2626")


# ============================================================
# 15. STUDENT QUIZ ACCESS ADMIN
# ============================================================

@admin.register(StudentQuizAccess)
class StudentQuizAccessAdmin(admin.ModelAdmin):
    list_display = ('student', 'quiz', 'is_allowed', 'is_valid_badge', 'expires_at', 'assigned_at')
    list_editable = ('is_allowed',)
    list_filter = ('is_allowed', 'assigned_at', 'expires_at')
    search_fields = ('student__user__phone_number', 'quiz__title')
    raw_id_fields = ('student', 'quiz', 'assigned_by')
    readonly_fields = ('assigned_at', 'created_at', 'updated_at')
    actions = ['allow_access', 'deny_access']

    @admin.display(description="Ruxsat")
    def is_allowed_badge(self, obj):
        if obj.is_allowed:
            return status_dot("✅ Ha", "#059669")
        return status_dot("⛔ Yo‘q", "#dc2626")

    @admin.display(description="Yaroqli?")
    def is_valid_badge(self, obj):
        if obj.is_valid:
            return status_dot("Ha", "#059669")
        return status_dot("Yo‘q", "#dc2626")

    @admin.action(description="✅ Ruxsat berish")
    def allow_access(self, request, queryset):
        queryset.update(is_allowed=True)

    @admin.action(description="⛔ Ruxsatni bekor qilish")
    def deny_access(self, request, queryset):
        queryset.update(is_allowed=False)


# ============================================================
# 16. STUDENT GROUP ADMIN
# ============================================================



# ============================================================
# 17. GROUP QUIZ ACCESS ADMIN
# ============================================================

@admin.register(GroupQuizAccess)
class GroupQuizAccessAdmin(admin.ModelAdmin):
    list_display = ('group', 'quiz', 'is_allowed', 'deadline', 'is_expired_badge', 'assigned_at')
    list_editable = ('is_allowed',)
    list_filter = ('is_allowed', 'assigned_at', 'deadline')
    search_fields = ('group__name', 'quiz__title')
    readonly_fields = ('assigned_at', 'created_at', 'updated_at')
    raw_id_fields = ('group', 'quiz', 'assigned_by')
    @admin.display(description="Ruxsat")
    def is_allowed_badge(self, obj):
        if obj.is_allowed:
            return status_dot("✅", "#059669")
        return status_dot("⛔", "#dc2626")

    @admin.display(description="Muddati o‘tgan?")
    def is_expired_badge(self, obj):
        if obj.is_expired:
            return status_dot("Ha", "#dc2626")
        return status_dot("Yo‘q", "#059669")


# ============================================================
# 18. MENU ITEM INLINE
# ============================================================

class MenuItemInline(admin.TabularInline):
    model = MenuItem
    extra = 1
    fields = (
        'title', 'icon_class', 'url_name', 'url',
        'order', 'is_active', 'badge_text', 'required_role'
    )


# ============================================================
# 19. MENU SECTION ADMIN
# ============================================================

@admin.register(MenuSection)
class MenuSectionAdmin(admin.ModelAdmin):
    list_display = ('title', 'order', 'is_active', 'items_count_display', 'icon_preview')
    list_filter = ('is_active',)
    ordering = ('order',)
    list_editable = ('order', 'is_active')
    inlines = [MenuItemInline]
    search_fields = ('title',)
    readonly_fields = ('created_at', 'updated_at')

    @admin.display(description="Elementlar")
    def items_count_display(self, obj):
        return obj.items_count

    @admin.display(description="Ikonka")
    def icon_preview(self, obj):
        if obj.icon:
            return format_html('<i class="{}"></i>', obj.icon)
        return "—"


# ============================================================
# 20. MENU ITEM ADMIN
# ============================================================

@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'section', 'icon_preview', 'order',
        'is_active', 'badge_text', 'required_role'
    )
    list_filter = ('is_active', 'section', 'required_role')
    search_fields = ('title', 'url_name')
    ordering = ('section__order', 'order')
    list_editable = ('order', 'is_active')
    autocomplete_fields = ('section',)
    readonly_fields = ('created_at', 'updated_at')

    @admin.display(description="Ikonka")
    def icon_preview(self, obj):
        return format_html('<i class="{}" style="font-size:16px;"></i>', obj.icon_class)


# ============================================================
# 21. LESSON INLINE
# ============================================================

class LessonInline(admin.TabularInline):
    model = Lesson
    extra = 1
    fields = ('title', 'date', 'order', 'group', 'is_published')
    show_change_link = True


# ============================================================
# 22. COURSE ADMIN
# ============================================================



# ============================================================
# 23. LESSON QUESTION INLINE
# ============================================================

class LessonQuestionInline(admin.TabularInline):
    model = LessonQuestion
    extra = 1
    fields = ('question_text', 'answer_text', 'points', 'order', 'is_active')


# ============================================================
# 24. LESSON ADMIN
# ============================================================



# ============================================================
# 25. ASSIGNMENT INLINE
# ============================================================

class AssignmentInline(admin.TabularInline):
    model = Assignment
    extra = 1
    fields = ('group', 'lesson', 'opens_at', 'closes_at', 'is_active')


# ============================================================
# 26. TASK ADMIN
# ============================================================

@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'task_type_badge', 'difficulty_badge',
        'max_score', 'coins_reward',
        'assignments_count_display', 'is_published', 'created_at'
    )
    list_filter = ('task_type', 'difficulty', 'is_published', 'created_at')
    search_fields = ('title', 'description')
    readonly_fields = (
        'created_at', 'updated_at',
        'assignments_count_display', 'submissions_count_display',
        'average_score_display'
    )
    inlines = [AssignmentInline]
    date_hierarchy = 'created_at'
    raw_id_fields = ('quiz',)

    fieldsets = (
        ('Asosiy', {'fields': ('task_type', 'title', 'description', 'difficulty')}),
        ('Kontent', {'fields': ('quiz', 'flag', 'file')}),
        ('Ballar', {'fields': ('max_score', 'coins_reward')}),
        ('Sozlamalar', {'fields': ('time_limit_minutes', 'is_published')}),
        ('Statistika', {
            'fields': (
                'assignments_count_display', 'submissions_count_display',
                'average_score_display'
            ),
            'classes': ('collapse',)
        }),
        ('Sanalar', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    @admin.display(description="Turi")
    def task_type_badge(self, obj):
        colors = {
            'quiz': '#4F46E5', 'open_question': '#06B6D4',
            'file_upload': '#F59E0B', 'ctf': '#F43F5E',
            'problem': '#7C3AED',
        }
        return badge(obj.get_task_type_display(), colors.get(obj.task_type, '#6B7280'))

    @admin.display(description="Qiyinlik")
    def difficulty_badge(self, obj):
        colors = {'easy': '#059669', 'medium': '#F59E0B', 'hard': '#dc2626'}
        return badge(obj.get_difficulty_display(), colors.get(obj.difficulty, '#6B7280'))

    @admin.display(description="Biriktirishlar")
    def assignments_count_display(self, obj):
        return obj.assignments_count

    @admin.display(description="Topshiriqlar")
    def submissions_count_display(self, obj):
        return obj.submissions_count

    @admin.display(description="O‘rtacha ball")
    def average_score_display(self, obj):
        return f"{obj.average_score}"


# ============================================================
# 27. SUBMISSION INLINE
# ============================================================

class SubmissionInline(admin.TabularInline):
    model = Submission
    extra = 0
    fields = ('student', 'submitted_at', 'is_late', 'score', 'coins_awarded')
    readonly_fields = ('submitted_at',)
    show_change_link = True
    autocomplete_fields = ('student',)


# ============================================================
# 28. ASSIGNMENT ADMIN
# ============================================================

@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = (
        'task', 'group', 'lesson', 'opens_at', 'closes_at',
        'is_open_badge', 'is_active', 'submissions_count_display',
        'time_remaining_display'
    )
    list_filter = ('is_active', 'opens_at', 'closes_at', 'group')
    search_fields = ('task__title', 'group__name')
    raw_id_fields = ('task', 'group', 'lesson', 'created_by')   # muqobil
    date_hierarchy = 'opens_at'
    inlines = [SubmissionInline]
    readonly_fields = ('created_at', 'updated_at')
    save_on_top = True

    fieldsets = (
        ('Asosiy', {'fields': ('task', 'group', 'lesson')}),
        ('Vaqt', {'fields': ('opens_at', 'closes_at')}),
        ('Sozlamalar', {
            'fields': (
                'max_attempts', 'late_submission_allowed',
                'late_penalty_percent', 'is_active', 'created_by'
            )
        }),
        ('Sanalar', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    @admin.display(description="Ochiq?", boolean=True)
    def is_open_badge(self, obj):
        return obj.is_open

    @admin.display(description="Topshirilgan")
    def submissions_count_display(self, obj):
        return obj.submissions_count

    @admin.display(description="Qolgan vaqt")
    def time_remaining_display(self, obj):
        delta = obj.time_remaining
        if delta is None:
            return "—"
        total = int(delta.total_seconds())
        days, rem = divmod(total, 86400)
        hours, _ = divmod(rem, 3600)
        if days > 0:
            return f"{days} kun {hours} soat"
        return f"{hours} soat"


# ============================================================
# 29. SUBMISSION ADMIN
# ============================================================

@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = (
        'student', 'assignment', 'submitted_at',
        'is_late_badge', 'score_display', 'grade_badge',
        'coins_awarded', 'is_graded_badge'
    )
    list_filter = ('is_late', 'submitted_at', 'assignment__group')
    search_fields = ('student__user__phone_number', 'assignment__task__title')
    autocomplete_fields = ('assignment', 'student', 'test_result', 'graded_by')
    date_hierarchy = 'submitted_at'
    readonly_fields = (
        'submitted_at', 'created_at', 'updated_at',
        'score_percent_display', 'grade_letter_display', 'graded_at'
    )
    save_on_top = True

    fieldsets = (
        ('Asosiy', {'fields': ('assignment', 'student', 'submitted_at', 'is_late')}),
        ('Javob', {'fields': ('answer_text', 'answer_file', 'test_result')}),
        ('Baholash', {
            'fields': (
                'score', 'score_percent_display', 'grade_letter_display',
                'feedback', 'graded_by', 'graded_at', 'coins_awarded'
            )
        }),
        ('Sanalar', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    @admin.display(description="Kech?", ordering='is_late')
    def is_late_badge(self, obj):
        if obj.is_late:
            return status_dot("⏰ Kechikkan", "#dc2626")
        return status_dot("✓ Vaqtida", "#059669")

    @admin.display(description="Ball")
    def score_display(self, obj):
        if obj.score is None:
            return "—"
        return f"{obj.score} / {obj.assignment.task.max_score}"

    @admin.display(description="Baho")
    def grade_badge(self, obj):
        if not obj.is_graded:
            return "—"
        colors = {'A': '#059669', 'B': '#0284c7', 'C': '#F59E0B', 'D': '#d97706', 'F': '#dc2626'}
        return badge(obj.grade_letter, colors.get(obj.grade_letter, '#6B7280'))

    @admin.display(description="Baholangan?", boolean=True)
    def is_graded_badge(self, obj):
        return obj.is_graded

    @admin.display(description="Foiz")
    def score_percent_display(self, obj):
        return f"{obj.score_percent}%"

    @admin.display(description="Harf baho")
    def grade_letter_display(self, obj):
        return obj.grade_letter


# ============================================================
# 30. ACTIVITY LOG ADMIN
# ============================================================

@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = (
        'user', 'login_time', 'logout_time',
        'duration_display', 'ip_address'
    )
    list_filter = ('login_time', 'logout_time')
    search_fields = ('user__phone_number', 'user__first_name', 'ip_address')
    date_hierarchy = 'login_time'
    readonly_fields = ('total_seconds', 'created_at', 'updated_at')
    autocomplete_fields = ('user',)

    @admin.display(description="Davomiylik")
    def duration_display(self, obj):
        return obj.duration_display


# ============================================================
# 31. NOTIFICATION ADMIN
# ============================================================

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        'user', 'notification_type_badge', 'priority_badge',
        'is_approved_badge', 'sent', 'is_read',
        'created_at'
    )
    list_filter = (
        'notification_type', 'priority', 'is_approved',
        'sent', 'is_read', 'created_at'
    )
    search_fields = ('user__phone_number', 'message', 'title')
    autocomplete_fields = ('user', 'approved_by')
    readonly_fields = ('created_at', 'updated_at', 'approved_at', 'read_at')
    date_hierarchy = 'created_at'
    save_on_top = True

    fieldsets = (
        ('Asosiy', {'fields': ('user', 'notification_type', 'priority', 'title', 'message')}),
        ('Holat', {
            'fields': (
                'is_approved', 'approved_by', 'approved_at',
                'sent', 'is_read', 'read_at', 'link'
            )
        }),
        ('Sanalar', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    actions = ['approve_notifications', 'mark_as_sent', 'mark_as_read']

    @admin.display(description="Turi")
    def notification_type_badge(self, obj):
        colors = {
            'homework_missed': '#dc2626', 'over_activity': '#F59E0B',
            'daily_report': '#06B6D4', 'weekly_report': '#7C3AED',
            'achievement': '#059669', 'payment': '#0284c7',
            'system': '#6B7280', 'custom': '#6B7280',
        }
        return badge(
            obj.get_notification_type_display(),
            colors.get(obj.notification_type, '#6B7280')
        )

    @admin.display(description="Muhimlik")
    def priority_badge(self, obj):
        return badge(obj.get_priority_display(), obj.priority_color)

    @admin.display(description="Tasdiqlangan?", boolean=True)
    def is_approved_badge(self, obj):
        return obj.is_approved

    @admin.action(description="✅ Tasdiqlash")
    def approve_notifications(self, request, queryset):
        for n in queryset:
            n.approve(request.user)
        self.message_user(request, f"{queryset.count()} ta bildirishnoma tasdiqlandi.")

    @admin.action(description="📤 Yuborilgan deb belgilash")
    def mark_as_sent(self, request, queryset):
        queryset.update(sent=True)

    @admin.action(description="📖 O‘qilgan deb belgilash")
    def mark_as_read(self, request, queryset):
        for n in queryset:
            n.mark_as_read()


# ============================================================
# 32. SMS LOG ADMIN
# ============================================================

@admin.register(SMSLog)
class SMSLogAdmin(admin.ModelAdmin):
    list_display = (
        'phone_number', 'notification', 'status_badge',
        'sent_at', 'retry_count', 'cost'
    )
    list_filter = ('status', 'sent_at')
    search_fields = ('phone_number',)
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'created_at'

    @admin.display(description="Holat")
    def status_badge(self, obj):
        colors = {
            'pending': '#F59E0B', 'sent': '#059669',
            'failed': '#dc2626', 'delivered': '#0284c7',
        }
        icons = {
            'pending': '⏳', 'sent': '✅',
            'failed': '❌', 'delivered': '📬',
        }
        return badge(
            obj.get_status_display(),
            colors.get(obj.status, '#6B7280'),
            icons.get(obj.status, '')
        )


# ============================================================
# 33. LESSON QUESTION ADMIN
# ============================================================

@admin.register(LessonQuestion)
class LessonQuestionAdmin(admin.ModelAdmin):
    list_display = ('id', 'lesson', 'question_short', 'points', 'order', 'is_active')
    list_filter = ('is_active', 'lesson__course', 'lesson')
    search_fields = ('question_text', 'answer_text')
    raw_id_fields = ('lesson',)  

    ordering = ('lesson', 'order')
    list_editable = ('points', 'order', 'is_active')
    readonly_fields = ('created_at', 'updated_at')

    @admin.display(description="Savol")
    def question_short(self, obj):
        return obj.question_text[:60] + ('…' if len(obj.question_text) > 60 else '')


# ============================================================
# 34. PARENT QUESTION REQUEST ADMIN
# ============================================================

@admin.register(ParentQuestionRequest)
class ParentQuestionRequestAdmin(admin.ModelAdmin):
    list_display = (
        'parent', 'student', 'lesson',
        'status_badge', 'created_at', 'approved_at'
    )
    list_filter = ('status', 'created_at', 'approved_at')
    search_fields = (
        'parent__phone_number',
        'student__user__phone_number',
        'lesson__title'
    )
    autocomplete_fields = ('parent', 'student', 'lesson', 'approved_by')
    readonly_fields = ('created_at', 'updated_at', 'approved_at')
    date_hierarchy = 'created_at'
    actions = ['approve_requests', 'reject_requests']

    @admin.display(description="Holat")
    def status_badge(self, obj):
        colors = {'pending': '#F59E0B', 'approved': '#059669', 'rejected': '#dc2626'}
        icons = {'pending': '⏳', 'approved': '✅', 'rejected': '❌'}
        return badge(
            obj.get_status_display(),
            colors.get(obj.status, '#6B7280'),
            icons.get(obj.status, '')
        )

    @admin.action(description="✅ Tasdiqlash")
    def approve_requests(self, request, queryset):
        for r in queryset:
            r.approve(request.user)
        self.message_user(request, f"{queryset.count()} ta so‘rov tasdiqlandi.")

    @admin.action(description="❌ Rad etish")
    def reject_requests(self, request, queryset):
        for r in queryset:
            r.reject('Admin tomonidan rad etildi')
        self.message_user(request, f"{queryset.count()} ta so‘rov rad etildi.")


# ============================================================
# 35. ACHIEVEMENT ADMIN (YANGI)
# ============================================================

@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'achievement_type_badge', 'rarity_badge',
        'icon_preview', 'coins_reward', 'points_reward',
        'condition_value', 'is_active'
    )
    list_filter = ('achievement_type', 'rarity', 'is_active')
    search_fields = ('name', 'description')
    list_editable = ('is_active',)
    ordering = ('rarity', 'name')
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        ('Asosiy', {'fields': ('name', 'description', 'icon')}),
        ('Sozlamalar', {'fields': ('achievement_type', 'rarity', 'condition_value')}),
        ('Mukofotlar', {'fields': ('coins_reward', 'points_reward')}),
        ('Holat', {'fields': ('is_active',)}),
        ('Sanalar', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    @admin.display(description="Turi")
    def achievement_type_badge(self, obj):
        return badge(obj.get_achievement_type_display(), '#4F46E5')

    @admin.display(description="Noyobligi")
    def rarity_badge(self, obj):
        return badge(obj.get_rarity_display(), obj.rarity_color)

    @admin.display(description="Ikonka")
    def icon_preview(self, obj):
        return format_html(
            '<i class="{}" style="color:{};font-size:20px;"></i>',
            obj.icon, obj.rarity_color
        )


@admin.register(StudentAchievement)
class StudentAchievementAdmin(admin.ModelAdmin):
    list_display = ('student', 'achievement', 'progress', 'unlocked_at')
    list_filter = ('achievement__rarity', 'unlocked_at')
    search_fields = (
        'student__user__phone_number',
        'achievement__name'
    )
    autocomplete_fields = ('student', 'achievement')
    readonly_fields = ('unlocked_at', 'created_at', 'updated_at')


# ============================================================
# 36. COIN TRANSACTION ADMIN (YANGI)
# ============================================================

@admin.register(CoinTransaction)
class CoinTransactionAdmin(admin.ModelAdmin):
    list_display = (
        'student', 'amount_display', 'transaction_type_badge',
        'reason', 'balance_after', 'created_at'
    )
    list_filter = ('transaction_type', 'created_at')
    search_fields = (
        'student__user__phone_number',
        'student__user__first_name',
        'reason'
    )
    autocomplete_fields = ('student',)
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'created_at'

    @admin.display(description="Miqdor")
    def amount_display(self, obj):
        color = '#059669' if obj.amount > 0 else '#dc2626'
        sign = '+' if obj.amount > 0 else ''
        return format_html(
            '<span style="color:{};font-weight:700;">{}{}</span>',
            color, sign, obj.amount
        )

    @admin.display(description="Turi")
    def transaction_type_badge(self, obj):
        colors = {
            'earn': '#059669', 'spend': '#dc2626',
            'bonus': '#7C3AED', 'penalty': '#F59E0B',
            'refund': '#0284c7',
        }
        return badge(obj.get_transaction_type_display(), colors.get(obj.transaction_type, '#6B7280'))


# ============================================================
# 37. PAYMENT ADMIN (YANGI)
# ============================================================

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        'student', 'amount_display', 'payment_type_badge',
        'status_badge', 'provider', 'course', 'created_at'
    )
    list_filter = ('payment_type', 'status', 'provider', 'created_at')
    search_fields = (
        'student__user__phone_number',
        'transaction_id',
        'reason'
    )
    raw_id_fields = ('student', 'course')
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'created_at'
    actions = ['mark_completed', 'mark_failed']

    @admin.display(description="Miqdor")
    def amount_display(self, obj):
        return format_html(
            '<span style="font-weight:700;">{:,.0f} so‘m</span>', obj.amount
        )

    @admin.display(description="Turi")
    def payment_type_badge(self, obj):
        colors = {
            'deposit': '#059669', 'withdraw': '#dc2626',
            'course': '#4F46E5', 'refund': '#F59E0B',
        }
        return badge(obj.get_payment_type_display(), colors.get(obj.payment_type, '#6B7280'))

    @admin.display(description="Holat")
    def status_badge(self, obj):
        colors = {
            'pending': '#F59E0B', 'completed': '#059669',
            'failed': '#dc2626', 'cancelled': '#6B7280',
        }
        return badge(obj.get_status_display(), colors.get(obj.status, '#6B7280'))

    @admin.action(description="✅ Yakunlangan deb belgilash")
    def mark_completed(self, request, queryset):
        for p in queryset:
            p.complete()
        self.message_user(request, f"{queryset.count()} ta to‘lov yakunlandi.")

    @admin.action(description="❌ Muvaffaqiyatsiz deb belgilash")
    def mark_failed(self, request, queryset):
        queryset.update(status='failed')


# ============================================================
# 38. ANNOUNCEMENT ADMIN (YANGI)
# ============================================================

@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'author', 'priority_badge',
        'is_pinned', 'is_published_badge',
        'publish_at', 'expires_at'
    )
    list_filter = ('priority', 'is_active', 'is_pinned', 'publish_at')
    search_fields = ('title', 'content')
    autocomplete_fields = ('author',)
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'publish_at'
    save_on_top = True

    fieldsets = (
        ('Asosiy', {'fields': ('title', 'content', 'author')}),
        ('Sozlamalar', {
            'fields': (
                'priority', 'target_roles', 'is_pinned', 'is_active'
            )
        }),
        ('Vaqt', {'fields': ('publish_at', 'expires_at')}),
        ('Sanalar', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    @admin.display(description="Muhimlik")
    def priority_badge(self, obj):
        colors = {
            'low': '#6B7280', 'normal': '#4F46E5',
            'high': '#F59E0B', 'urgent': '#dc2626',
        }
        return badge(obj.get_priority_display(), colors.get(obj.priority, '#6B7280'))

    @admin.display(description="Faol?", boolean=True)
    def is_published_badge(self, obj):
        return obj.is_published


# ============================================================
# 39. FEEDBACK ADMIN (YANGI)
# ============================================================

@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = (
        'subject', 'user', 'feedback_type_badge',
        'status_badge', 'created_at', 'responded_at'
    )
    list_filter = ('feedback_type', 'status', 'created_at')
    search_fields = ('subject', 'message', 'user__phone_number')
    autocomplete_fields = ('user', 'responded_by')
    readonly_fields = ('created_at', 'updated_at', 'responded_at')
    date_hierarchy = 'created_at'
    save_on_top = True

    fieldsets = (
        ('Asosiy', {'fields': ('user', 'feedback_type', 'subject', 'message')}),
        ('Javob', {
            'fields': (
                'status', 'response', 'responded_by', 'responded_at'
            )
        }),
        ('Sanalar', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    actions = ['mark_resolved', 'mark_closed']

    @admin.display(description="Turi")
    def feedback_type_badge(self, obj):
        colors = {
            'complaint': '#dc2626', 'suggestion': '#4F46E5',
            'bug': '#F59E0B', 'praise': '#059669',
            'other': '#6B7280',
        }
        return badge(obj.get_feedback_type_display(), colors.get(obj.feedback_type, '#6B7280'))

    @admin.display(description="Holat")
    def status_badge(self, obj):
        colors = {
            'new': '#F59E0B', 'in_progress': '#0284c7',
            'resolved': '#059669', 'closed': '#6B7280',
        }
        return badge(obj.get_status_display(), colors.get(obj.status, '#6B7280'))

    @admin.action(description="✅ Hal qilindi")
    def mark_resolved(self, request, queryset):
        queryset.update(status='resolved')

    @admin.action(description="🔒 Yopildi")
    def mark_closed(self, request, queryset):
        queryset.update(status='closed')


# ============================================================
# ADMIN SITE SOZLAMALARI
# ============================================================

admin.site.site_header = "LearnCraft – Boshqaruv Paneli"
admin.site.site_title = "LearnCraft Admin"
admin.site.index_title = "Xush kelibsiz! Boshqaruv paneli"

# ═══════════════════════════════════════════════════════════════
# TELEGRAM NOTIFICATION ADMIN
# ═══════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════
# TELEGRAM NOTIFICATION ADMIN
# ═══════════════════════════════════════════════════════════════

@admin.register(TelegramNotificationTemplate)
class TelegramNotificationTemplateAdmin(admin.ModelAdmin):
    list_display = (
        'trigger_badge', 'title_preview', 'emoji',
        'has_button', 'is_active',
    )
    list_filter = ('is_active',)
    search_fields = ('title', 'message')
    list_editable = ('is_active',)

    fieldsets = (
        ('Trigger', {'fields': ('trigger', 'is_active')}),
        ('Kontent', {'fields': ('emoji', 'title', 'message')}),
        ('Tugma', {'fields': ('button_text', 'button_url')}),
    )

    @admin.display(description="Trigger")
    def trigger_badge(self, obj):
        colors = {
            'welcome_back': '#059669',
            'inactive_4h': '#F59E0B',
            'inactive_7h': '#ea580c',
            'inactive_1d': '#dc2626',
            'inactive_3d': '#7C3AED',
            'late_night': '#1e40af',
            'morning_boost': '#10b981',
            'login_telegram': '#229ed9',
        }
        return format_html(
            '<span style="background:{};color:#fff;padding:3px 10px;'
            'border-radius:999px;font-size:11px;font-weight:600;">{}</span>',
            colors.get(obj.trigger, '#6B7280'),
            obj.get_trigger_display()
        )

    @admin.display(description="Sarlavha")
    def title_preview(self, obj):
        return obj.title[:50]

    @admin.display(description="Tugma", boolean=True)
    def has_button(self, obj):
        return bool(obj.button_text)


@admin.register(StudyQuestion)
class StudyQuestionAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'category_badge', 'question_preview',
        'has_options', 'used_count', 'order', 'is_active'
    )
    list_filter = ('category', 'is_active')
    search_fields = ('question',)
    list_editable = ('order', 'is_active')
    ordering = ('order', 'id')

    fieldsets = (
        ('Asosiy', {'fields': ('category', 'question', 'hint')}),
        ('Variantlar', {
            'fields': ('options', 'correct_index'),
            'description': 'Bo‘sh qoldirsa — savol ochiq matnli bo‘ladi'
        }),
        ('Holat', {'fields': ('order', 'is_active', 'used_count')}),
    )

    @admin.display(description="Kategoriya")
    def category_badge(self, obj):
        colors = {
            'motivation': '#6366f1', 'quiz': '#ec4899',
            'daily': '#06b6d4', 'feedback': '#f59e0b',
        }
        return format_html(
            '<span style="background:{};color:#fff;padding:3px 10px;'
            'border-radius:999px;font-size:11px;">{}</span>',
            colors.get(obj.category, '#6B7280'),
            obj.get_category_display()
        )

    @admin.display(description="Savol")
    def question_preview(self, obj):
        return obj.question[:60]

    @admin.display(description="Variantlar", boolean=True)
    def has_options(self, obj):
        return bool(obj.options)


@admin.register(TelegramNotificationLog)
class TelegramNotificationLogAdmin(admin.ModelAdmin):
    list_display = (
        'recipient', 'trigger_badge', 'status_badge',
        'is_read', 'sent_at', 'sent_by'
    )
    list_filter = ('trigger', 'status', 'is_read', 'sent_at')
    search_fields = (
        'recipient__phone_number', 'recipient__first_name', 'message',
    )
    readonly_fields = ('sent_at', 'delivered_at', 'chat_id', 'error_message')
    autocomplete_fields = ('recipient', 'sent_by')
    date_hierarchy = 'sent_at'

    @admin.display(description="Trigger")
    def trigger_badge(self, obj):
        return format_html(
            '<span style="background:#6366f1;color:#fff;padding:3px 10px;'
            'border-radius:999px;font-size:11px;">{}</span>',
            obj.get_trigger_display()
        )

    @admin.display(description="Holat")
    def status_badge(self, obj):
        colors = {
            'pending': '#F59E0B', 'sent': '#059669',
            'failed': '#dc2626', 'delivered': '#0284c7',
        }
        icons = {
            'pending': '⏳', 'sent': '✅', 'failed': '❌', 'delivered': '📬',
        }
        return format_html(
            '<span style="color:{};font-weight:600;">{} {}</span>',
            colors.get(obj.status, '#6B7280'),
            icons.get(obj.status, ''),
            obj.get_status_display()
        )


# ═══════════════════════════════════════════════════════════════
# LEARNCRAFT KURS MODELLARI UCHUN SODDA ADMINLAR
# (autocomplete_fields ishlashi uchun kerak)
# ═══════════════════════════════════════════════════════════════

@admin.register(Course)
class SimpleCourseAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'teacher', 'start_date', 'is_active')
    search_fields = ('title',)
    list_filter = ('is_active',)
    autocomplete_fields = ('teacher',)


@admin.register(Lesson)
class SimpleLessonAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'course', 'date', 'order')
    search_fields = ('title',)
    list_filter = ('course',)
    autocomplete_fields = ('course', 'group')


@admin.register(Quiz)
class SimpleQuizAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'category', 'difficulty', 'is_active')
    search_fields = ('title',)
    list_filter = ('difficulty', 'is_active')
    autocomplete_fields = ('category',)


@admin.register(Question)
class SimpleQuestionAdmin(admin.ModelAdmin):
    list_display = ('id', 'text', 'quiz', 'points', 'order')
    search_fields = ('text',)
    list_filter = ('quiz',)
    autocomplete_fields = ('quiz',)


@admin.register(AnswerOption)
class SimpleAnswerOptionAdmin(admin.ModelAdmin):
    list_display = ('id', 'text', 'question', 'is_correct', 'order')
    search_fields = ('text',)
    list_filter = ('is_correct',)
    autocomplete_fields = ('question',)


@admin.register(StudentGroup)
class SimpleStudentGroupAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'teacher', 'is_active')
    search_fields = ('name',)
    list_filter = ('is_active',)
    autocomplete_fields = ('teacher',)