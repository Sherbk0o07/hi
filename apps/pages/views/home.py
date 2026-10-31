"""
Asosiy sahifalar va rolga asoslangan yo‘naltirish.
"""
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.views.generic import TemplateView
from datetime import timedelta
from django.db.models import Count, Sum, Avg, Q, F, Case, When, Value, IntegerField
from apps.user.models import (
    StudentProfile,
    TeacherProfile,
    CustomUser,
    ParentQuestionRequest,
    Lesson,
    Quiz,
    Notification,
    SMSLog,
    ActivityLog,
    Assignment,
    Submission,
)


# ═══════════════════════════════════════════════════════════════
# MIXINLAR
# ═══════════════════════════════════════════════════════════════

class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Faqat admin va superuser uchun."""

    def test_func(self):
        user = self.request.user
        return user.is_authenticated and (user.is_superuser or user.role == 'admin')

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        return redirect('home_page_view')


class RoleRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Muayyan rol uchun."""
    allowed_roles = ()

    def test_func(self):
        user = self.request.user
        return user.is_authenticated and (
            user.is_superuser or user.role in self.allowed_roles
        )

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        return redirect('home_page_view')


# ═══════════════════════════════════════════════════════════════
# YO‘NALTIRUVCHI
# ═══════════════════════════════════════════════════════════════

def get_user_home_url(user):
    """Foydalanuvchi roliga qarab yo‘naltirish URL ini qaytaradi."""
    if not user.is_authenticated:
        return reverse('login_page_view')

    if user.is_superuser or user.role == 'admin':
        return reverse('admin_dashboard')
    if user.role == 'parent':
        return reverse('parent_dashboard')
    if user.role == 'teacher':
        return reverse('teacher_dashboard')  # kerak bo‘lsa yarating
    if user.role == 'manager':
        return reverse('manager_dashboard')  # kerak bo‘lsa yarating
    return reverse('student_home')  # student uchun


class HomePageView(LoginRequiredMixin, TemplateView):
    """
    Rolga qarab yo‘naltiruvchi.
    Student uchun maxsus template, boshqalar uchun redirect.
    """
    template_name = 'student/student.html'

    def get(self, request, *args, **kwargs):
        user = request.user

        # Admin / parent / teacher / manager uchun redirect
        if user.is_superuser or user.role != 'student':
            return redirect(get_user_home_url(user))

        return super().get(request, *args, **kwargs)


# ═══════════════════════════════════════════════════════════════
# OTA-ONA
# ═══════════════════════════════════════════════════════════════

class ParentDashboardView(RoleRequiredMixin, TemplateView):
    template_name = 'parent/dashboard.html'
    allowed_roles = ('parent',)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        parent = self.request.user

        children = (
            StudentProfile.objects
            .filter(parent_phone=parent.phone_number)
            .select_related('user')
        )
        context['children'] = children

        # So‘rovlar statistikasi
        context['pending_request_count'] = ParentQuestionRequest.objects.filter(
            parent=parent, student__in=children, status='pending'
        ).count()
        context['approved_request_count'] = ParentQuestionRequest.objects.filter(
            parent=parent, student__in=children, status='approved'
        ).count()

        if not children.exists():
            context.update({
                'overall_progress': 0,
                'recent_submissions': [],
                'sms_history': [],
            })
            return context

        child_user_ids = list(children.values_list('user_id', flat=True))

        total_assignments = Assignment.objects.filter(
            group__students__user_id__in=child_user_ids,
            is_active=True,
        ).distinct().count()

        completed_submissions = Submission.objects.filter(
            student__user_id__in=child_user_ids,
            assignment__is_active=True,
        ).count()

        overall_progress = (
            round((completed_submissions / total_assignments) * 100)
            if total_assignments else 0
        )

        context.update({
            'overall_progress': overall_progress,
            'recent_submissions': Submission.objects
                .filter(student__user_id__in=child_user_ids)
                .select_related('assignment__task', 'test_result')
                .order_by('-submitted_at')[:10],
            'sms_history': Notification.objects
                .filter(user_id__in=child_user_ids, sent=True)
                .order_by('-created_at')[:10],
        })
        return context


class ParentQuestionView(RoleRequiredMixin, TemplateView):
    template_name = 'parent/questions.html'
    allowed_roles = ('parent',)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        parent = self.request.user

        children = (
            StudentProfile.objects
            .filter(parent_phone=parent.phone_number)
            .select_related('user')
        )
        context['children'] = children

        context['pending_request_count'] = ParentQuestionRequest.objects.filter(
            parent=parent, student__in=children, status='pending'
        ).count()
        context['approved_request_count'] = ParentQuestionRequest.objects.filter(
            parent=parent, student__in=children, status='approved'
        ).count()

        if not children.exists():
            context['lessons'] = []
            return context

        child_user_ids = list(children.values_list('user_id', flat=True))

        lessons = list(
            Lesson.objects
            .filter(
                group__students__user_id__in=child_user_ids,
                lesson_date=timezone.now().date(),
            )
            .distinct()
            .order_by('lesson_date')
        )

        # Prefetch so‘rovlar va savollar (N+1 oldini olish)
        requests_map = {
            r.lesson_id: r for r in ParentQuestionRequest.objects.filter(
                parent=parent, student__in=children, lesson__in=lessons
            )
        }

        for lesson in lessons:
            req = requests_map.get(lesson.id)
            lesson.parent_request = req
            if req and req.status == 'approved':
                lesson.approved_questions = list(lesson.questions.all())
            else:
                lesson.approved_questions = []

        context['lessons'] = lessons
        return context

    def post(self, request, *args, **kwargs):
        lesson_id = request.POST.get('lesson_id')
        student_id = request.POST.get('student_id')

        if not (lesson_id and student_id):
            return redirect('parent_questions')

        lesson = get_object_or_404(Lesson, id=lesson_id)
        student = get_object_or_404(StudentProfile, id=student_id)

        # Xavfsizlik: faqat o‘z farzandi uchun
        if student.parent_phone != request.user.phone_number:
            return redirect('parent_questions')

        ParentQuestionRequest.objects.get_or_create(
            parent=request.user,
            student=student,
            lesson=lesson,
        )
        return redirect('parent_questions')


# ═══════════════════════════════════════════════════════════════
# ADMIN DASHBOARD
# ═══════════════════════════════════════════════════════════════

class AdminDashboardView(AdminRequiredMixin, TemplateView):
    template_name = 'admin_user/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Statistika
        context.update({
            'total_students': StudentProfile.objects.count(),
            'total_parents': CustomUser.objects.filter(role='parent').count(),
            'total_teachers': TeacherProfile.objects.count(),
            'pending_requests': ParentQuestionRequest.objects.filter(status='pending').count(),
            'total_lessons': Lesson.objects.count(),
            'total_quizzes': Quiz.objects.count(),
            'pending_notifications': Notification.objects.filter(is_approved=False).count(),
        })

        # So‘nggi so‘rovlar
        context['latest_requests'] = (
            ParentQuestionRequest.objects
            .select_related('parent', 'student', 'lesson')
            .order_by('-created_at')[:5]
        )

        # Yaqin darslar
        today = timezone.now().date()
        next_week = today + timedelta(days=7)

        context['upcoming_lessons'] = (
            Lesson.objects
            .select_related('course')  # ✅ Faqat 'course'
            .filter(lesson_date__gte=today, lesson_date__lte=next_week)
            .order_by('lesson_date')[:6]
        )

        # So‘nggi SMS
        context['recent_sms_logs'] = (
            SMSLog.objects
            .select_related('notification')
            .order_by('-sent_at')[:5]
        )

        # So‘nggi faolliklar
        context['recent_activities'] = (
            ActivityLog.objects
            .select_related('user')
            .order_by('-login_time')[:5]
        )

        return context


# ═══════════════════════════════════════════════════════════════
# LOGOUT
# ═══════════════════════════════════════════════════════════════

@require_http_methods(["GET", "POST"])
def logout_view(request):
    """Xavfsiz chiqish + ActivityLog yangilash."""
    user = request.user

    if user.is_authenticated:
        try:
            log = ActivityLog.objects.filter(
                user=user, logout_time__isnull=True
            ).order_by('-login_time').first()

            if log:
                log.logout_time = timezone.now()
                if log.login_time:
                    log.total_seconds = int(
                        (log.logout_time - log.login_time).total_seconds()
                    )
                log.save(update_fields=['logout_time', 'total_seconds'])
        except Exception:
            pass

        auth_logout(request)

    return redirect('login_page_view')
# ═══════════════════════════════════════════════════════════════
# ADMIN SECTION (placeholder sahifalar)
# ═══════════════════════════════════════════════════════════════

class AdminSectionView(AdminRequiredMixin, TemplateView):
    """
    Bo‘sh bo‘limlar uchun umumiy placeholder sahifa.
    Har bir URL `section_title` va `section_icon` bilan sozlanadi.
    """
    template_name = 'admin_user/section_placeholder.html'
    section_title = 'Admin bo‘limi'
    section_icon = 'fas fa-cog'
    section_description = 'Bu bo‘lim tez orada ishga tushadi.'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'section_title': self.section_title,
            'section_icon': self.section_icon,
            'section_description': self.section_description,
        })
        return context


"""
apps/courses/views.py
================================================
DIGION LMS — Kurslar tizimi uchun to‘liq viewlar.

XUSUSIYATLAR:
- Admin: CRUD, statistika, approval workflow
- O‘qituvchi: dars boshqaruvi, baholash
- Talaba: dars ko‘rish, test topshirish, vazifa bajarish
- AJAX endpoints
- API endpoints
- File upload
- CSV/PDF export
- Search, filter, pagination
"""

import csv
import json
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db import transaction
from django.db.models import (
    Count, Sum, Avg, Max, Min, Q, F,
    Case, When, Value, IntegerField,
)
from django.http import (
    HttpResponse, JsonResponse, HttpResponseRedirect,
    Http404, FileResponse,
)
from django.shortcuts import (
    get_object_or_404, redirect, render, reverse,
)
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import (
    ListView, DetailView, CreateView, UpdateView, DeleteView,
    TemplateView, FormView, View,
)

from apps.user.models import (
    StudentProfile, CustomUser,
    TelegramLink, TelegramNotificationLog,
)
from apps.service.notification_service import (
    send_homework_to_group,
    notify_admin_about_submission,
    notify_admin_about_login,
)

from apps.courses.models import (
    CourseCategory, Tag, Course,
    CourseMonth, Lesson,
    Homework, HomeworkSubmission,
    Quiz, Question, AnswerOption,
    QuizAttempt, AttemptAnswer,
    StudentGroup, GroupMember,
    Enrollment, Attendance,
    Review, Certificate,
    CourseModule, CourseFAQ, CourseAnnouncement,
    CourseResource, LessonLog, AuditLog,
)


# ═══════════════════════════════════════════════════════════════
# MIXINLAR
# ═══════════════════════════════════════════════════════════════

class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Faqat admin uchun."""

    def test_func(self):
        user = self.request.user
        return user.is_authenticated and (
                user.is_superuser or user.role == 'admin'
        )

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        messages.error(self.request, "Ruxsat yo‘q!")
        return redirect('home_page_view')


class TeacherRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Faqat o‘qituvchi uchun."""

    def test_func(self):
        user = self.request.user
        return user.is_authenticated and user.role in ('admin', 'teacher')

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        messages.error(self.request, "Ruxsat yo‘q!")
        return redirect('home_page_view')


class StudentRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Faqat talaba uchun."""

    def test_func(self):
        user = self.request.user
        return user.is_authenticated and user.role == 'student'

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        messages.error(self.request, "Faqat talabalar uchun!")
        return redirect('home_page_view')


# ═══════════════════════════════════════════════════════════════
# YORDAMCHI FUNKSIYALAR
# ═══════════════════════════════════════════════════════════════

def paginate_queryset(request, queryset, per_page=12):
    """Pagination yordamchisi."""
    paginator = Paginator(queryset, per_page)
    page = request.GET.get('page', 1)
    try:
        return paginator.page(page)
    except PageNotAnInteger:
        return paginator.page(1)
    except EmptyPage:
        return paginator.page(paginator.num_pages)


def get_client_ip(request):
    """Foydalanuvchi IP manzili."""
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def log_audit(user, action, obj=None, description='', changes=None):
    """Audit log yozish."""
    try:
        from django.contrib.contenttypes.models import ContentType

        audit = AuditLog(
            user=user,
            action=action,
            description=description,
            changes=changes or {},
        )

        if obj:
            audit.content_type = ContentType.objects.get_for_model(obj)
            audit.object_id = obj.pk

        audit.save()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Audit log xatosi: {e}")


# ═══════════════════════════════════════════════════════════════
# ADMIN: KURSLAR RO‘YXATI
# ═══════════════════════════════════════════════════════════════

class AdminCourseListView(AdminRequiredMixin, ListView):
    """Barcha kurslar ro‘yxati."""

    model = Course
    template_name = 'admin_user/courses/list.html'
    context_object_name = 'courses'
    paginate_by = 12

    def get_queryset(self):
        queryset = Course.objects.filter(
            is_deleted=False
        ).select_related('category', 'teacher').prefetch_related('tags')

        # Qidiruv
        search = self.request.GET.get('search', '').strip()
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) |
                Q(short_description__icontains=search) |
                Q(description__icontains=search) |
                Q(teacher__first_name__icontains=search) |
                Q(teacher__last_name__icontains=search)
            )

        # Filter: Status
        status = self.request.GET.get('status', 'all')
        if status != 'all':
            queryset = queryset.filter(status=status)

        # Filter: Category
        category = self.request.GET.get('category', 'all')
        if category != 'all':
            queryset = queryset.filter(category_id=category)

        # Filter: Level
        level = self.request.GET.get('level', 'all')
        if level != 'all':
            queryset = queryset.filter(level=level)

        # Filter: Language
        language = self.request.GET.get('language', 'all')
        if language != 'all':
            queryset = queryset.filter(language=language)

        # Sorting
        sort = self.request.GET.get('sort', '-created_at')
        queryset = queryset.order_by(sort)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Statistika
        context['total_courses'] = Course.objects.filter(is_deleted=False).count()
        context['published_count'] = Course.objects.filter(
            status='published', is_deleted=False
        ).count()
        context['draft_count'] = Course.objects.filter(
            status='draft', is_deleted=False
        ).count()
        context['featured_count'] = Course.objects.filter(
            is_featured=True, is_deleted=False
        ).count()

        # Filterlar
        context['categories'] = CourseCategory.objects.filter(is_active=True)
        context['status_choices'] = Course._meta.get_field('status').choices
        context['level_choices'] = Course._meta.get_field('level').choices
        context['language_choices'] = Course._meta.get_field('language').choices

        # Joriy filterlar
        context['search'] = self.request.GET.get('search', '')
        context['current_status'] = self.request.GET.get('status', 'all')
        context['current_category'] = self.request.GET.get('category', 'all')
        context['current_level'] = self.request.GET.get('level', 'all')
        context['current_language'] = self.request.GET.get('language', 'all')
        context['current_sort'] = self.request.GET.get('sort', '-created_at')

        return context


# ═══════════════════════════════════════════════════════════════
# ADMIN: KURS TAFSILOTI
# ═══════════════════════════════════════════════════════════════

class AdminCourseDetailView(AdminRequiredMixin, DetailView):
    """Kurs tafsiloti — 9 oylik reja bilan."""

    model = Course
    template_name = 'admin_user/courses/detail.html'
    context_object_name = 'course'

    def get_object(self, queryset=None):
        pk = self.kwargs.get('pk')
        return get_object_or_404(Course, pk=pk, is_deleted=False)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        course = self.get_object()

        # Oylar va darslar
        months = course.months.prefetch_related(
            'lessons__homework'
        ).order_by('month_number')

        context['months'] = months

        # Guruhlar
        context['groups'] = StudentGroup.objects.filter(
            course=course, is_deleted=False
        ).select_related('teacher')

        # Statistika
        context['total_students'] = Enrollment.objects.filter(
            course=course, status='active'
        ).count()
        context['total_lessons'] = course.total_lessons
        context['total_homework'] = course.total_homework
        context['total_tests'] = course.total_tests
        context['avg_rating'] = course.average_rating

        # Oxirgi e’lonlar
        context['recent_announcements'] = CourseAnnouncement.objects.filter(
            course=course, is_published=True
        ).order_by('-publish_at')[:5]

        # Resurslar
        context['resources'] = CourseResource.objects.filter(
            course=course
        ).order_by('-created_at')[:10]

        # So‘nggi yozilganlar
        context['recent_enrollments'] = Enrollment.objects.filter(
            course=course
        ).select_related('student__user').order_by('-enrolled_at')[:10]

        return context


# ═══════════════════════════════════════════════════════════════
# ADMIN: KURS YARATISH
# ═══════════════════════════════════════════════════════════════

class AdminCourseCreateView(AdminRequiredMixin, View):
    """Kurs yaratish."""

    template_name = 'admin_user/courses/create.html'

    def get(self, request):
        context = {
            'categories': CourseCategory.objects.filter(is_active=True),
            'teachers': CustomUser.objects.filter(role='teacher', is_active=True),
            'tags': Tag.objects.all(),
            'level_choices': Course._meta.get_field('level').choices,
            'language_choices': Course._meta.get_field('language').choices,
        }
        return render(request, self.template_name, context)

    def post(self, request):
        try:
            with transaction.atomic():
                # Asosiy ma’lumotlar
                course = Course.objects.create(
                    title=request.POST.get('title', '').strip(),
                    short_description=request.POST.get('short_description', '').strip(),
                    description=request.POST.get('description', '').strip(),
                    category_id=request.POST.get('category') or None,
                    teacher_id=request.POST.get('teacher') or None,
                    start_date=request.POST.get('start_date'),
                    end_date=request.POST.get('end_date'),
                    duration_months=int(request.POST.get('duration_months', 9)),
                    language=request.POST.get('language', 'uz'),
                    level=request.POST.get('level', 'beginner'),
                    status=request.POST.get('status', 'draft'),
                    price=Decimal(request.POST.get('price', '0') or '0'),
                    discounted_price=Decimal(request.POST.get('discounted_price') or '0') or None,
                    is_active=request.POST.get('is_active') == 'on',
                    is_featured=request.POST.get('is_featured') == 'on',
                    created_by=request.user,
                )

                # Rasm
                if 'cover_image' in request.FILES:
                    course.cover_image = request.FILES['cover_image']
                    course.save()

                # Teglar
                tag_ids = request.POST.getlist('tags')
                if tag_ids:
                    course.tags.set(tag_ids)

                # Audit
                log_audit(
                    request.user, 'create', course,
                    f"Yangi kurs yaratildi: {course.title}"
                )

                messages.success(request, f"✅ '{course.title}' muvaffaqiyatli yaratildi!")
                return redirect('admin_course_detail', pk=course.pk)

        except Exception as e:
            messages.error(request, f"❌ Xatolik: {e}")
            return render(request, self.template_name, {
                'form_data': request.POST,
                'categories': CourseCategory.objects.filter(is_active=True),
                'teachers': CustomUser.objects.filter(role='teacher', is_active=True),
            })


# ═══════════════════════════════════════════════════════════════
# ADMIN: KURS TAHRIRLASH
# ═══════════════════════════════════════════════════════════════

class AdminCourseEditView(AdminRequiredMixin, View):
    """Kursni tahrirlash."""

    template_name = 'admin_user/courses/edit.html'

    def get(self, request, pk):
        course = get_object_or_404(Course, pk=pk, is_deleted=False)

        context = {
            'course': course,
            'categories': CourseCategory.objects.filter(is_active=True),
            'teachers': CustomUser.objects.filter(role='teacher', is_active=True),
            'tags': Tag.objects.all(),
            'selected_tags': course.tags.values_list('id', flat=True),
            'level_choices': Course._meta.get_field('level').choices,
            'language_choices': Course._meta.get_field('language').choices,
        }
        return render(request, self.template_name, context)

    def post(self, request, pk):
        course = get_object_or_404(Course, pk=pk, is_deleted=False)

        try:
            with transaction.atomic():
                old_values = {
                    'title': course.title,
                    'status': course.status,
                    'price': float(course.price),
                }

                # Yangilash
                course.title = request.POST.get('title', course.title).strip()
                course.short_description = request.POST.get('short_description', '').strip()
                course.description = request.POST.get('description', '').strip()
                course.category_id = request.POST.get('category') or None
                course.teacher_id = request.POST.get('teacher') or None
                course.start_date = request.POST.get('start_date')
                course.end_date = request.POST.get('end_date')
                course.duration_months = int(request.POST.get('duration_months', 9))
                course.language = request.POST.get('language', 'uz')
                course.level = request.POST.get('level', 'beginner')
                course.status = request.POST.get('status', 'draft')
                course.price = Decimal(request.POST.get('price', '0') or '0')
                course.discounted_price = Decimal(request.POST.get('discounted_price') or '0') or None
                course.is_active = request.POST.get('is_active') == 'on'
                course.is_featured = request.POST.get('is_featured') == 'on'

                if 'cover_image' in request.FILES:
                    course.cover_image = request.FILES['cover_image']

                course.save()

                # Teglar
                tag_ids = request.POST.getlist('tags')
                course.tags.set(tag_ids)

                # Audit
                new_values = {
                    'title': course.title,
                    'status': course.status,
                    'price': float(course.price),
                }
                changes = {
                    k: {'old': old_values[k], 'new': new_values[k]}
                    for k in old_values if old_values[k] != new_values[k]
                }

                log_audit(
                    request.user, 'update', course,
                    f"Kurs tahrirlandi: {course.title}",
                    changes
                )

                messages.success(request, f"✅ '{course.title}' yangilandi!")
                return redirect('admin_course_detail', pk=course.pk)

        except Exception as e:
            messages.error(request, f"❌ Xatolik: {e}")
            return redirect('admin_course_detail', pk=course.pk)


# ═══════════════════════════════════════════════════════════════
# ADMIN: KURS O‘CHIRISH (Soft Delete)
# ═══════════════════════════════════════════════════════════════

class AdminCourseDeleteView(AdminRequiredMixin, View):
    """Kursni o‘chirish (yumshoq)."""

    def post(self, request, pk):
        course = get_object_or_404(Course, pk=pk, is_deleted=False)

        try:
            course.soft_delete(request.user)
            log_audit(
                request.user, 'delete', course,
                f"Kurs o‘chirildi: {course.title}"
            )

            messages.success(request, f"🗑 '{course.title}' o‘chirildi!")
            return JsonResponse({'success': True})

        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)


# ═══════════════════════════════════════════════════════════════
# ADMIN: OYLAR BOSHQARUVI
# ═══════════════════════════════════════════════════════════════

class AdminCourseMonthCreateView(AdminRequiredMixin, View):
    """Kurs oyi qo‘shish."""

    def post(self, request, course_id):
        course = get_object_or_404(Course, pk=course_id)

        try:
            month = CourseMonth.objects.create(
                course=course,
                month_number=int(request.POST.get('month_number', 1)),
                title=request.POST.get('title', '').strip(),
                description=request.POST.get('description', '').strip(),
                goals=request.POST.get('goals', '').strip(),
                start_date=request.POST.get('start_date'),
                end_date=request.POST.get('end_date'),
                is_active=True,
            )

            messages.success(request, f"✅ {month.month_number}-oy qo‘shildi!")

        except Exception as e:
            messages.error(request, f"❌ Xatolik: {e}")

        return redirect('admin_course_detail', pk=course.id)


# ═══════════════════════════════════════════════════════════════
# ADMIN: DARSLAR BOSHQARUVI
# ═══════════════════════════════════════════════════════════════

class AdminLessonCreateView(AdminRequiredMixin, View):
    """Dars yaratish."""

    template_name = 'admin_user/courses/lesson_form.html'

    def get(self, request, course_id):
        course = get_object_or_404(Course, pk=course_id)

        context = {
            'course': course,
            'months': course.months.all(),
            'groups': StudentGroup.objects.filter(course=course, is_deleted=False),
            'day_choices': Lesson._meta.get_field('day_of_week').choices,
            'type_choices': Lesson._meta.get_field('lesson_type').choices,
        }
        return render(request, self.template_name, context)

    def post(self, request, course_id):
        course = get_object_or_404(Course, pk=course_id)

        try:
            with transaction.atomic():
                lesson = Lesson.objects.create(
                    course=course,
                    month_id=request.POST.get('month') or None,
                    group_id=request.POST.get('group') or None,
                    week_number=int(request.POST.get('week_number', 1)),
                    day_of_week=request.POST.get('day_of_week', 'monday'),
                    order=int(request.POST.get('order', 1)),
                    title=request.POST.get('title', '').strip(),
                    short_description=request.POST.get('short_description', '').strip(),
                    content=request.POST.get('content', '').strip(),
                    lesson_type=request.POST.get('lesson_type', 'theory'),
                    video_url=request.POST.get('video_url', '').strip() or None,
                    lesson_date=request.POST.get('lesson_date') or None,
                    start_time=request.POST.get('start_time') or None,
                    end_time=request.POST.get('end_time') or None,
                    duration_minutes=int(request.POST.get('duration_minutes', 90)),
                    live_url=request.POST.get('live_url', '').strip() or None,
                    live_password=request.POST.get('live_password', '').strip(),
                    is_published=request.POST.get('is_published') == 'on',
                    is_mandatory=request.POST.get('is_mandatory') == 'on',
                )

                # Fayllar
                if 'video_file' in request.FILES:
                    lesson.video_file = request.FILES['video_file']
                if 'presentation' in request.FILES:
                    lesson.presentation = request.FILES['presentation']
                if 'audio_file' in request.FILES:
                    lesson.audio_file = request.FILES['audio_file']
                lesson.save()

                log_audit(
                    request.user, 'create', lesson,
                    f"Dars yaratildi: {lesson.title}"
                )

                messages.success(request, f"✅ '{lesson.title}' dars qo‘shildi!")
                return redirect('admin_course_detail', pk=course.id)

        except Exception as e:
            messages.error(request, f"❌ Xatolik: {e}")
            return redirect('admin_course_detail', pk=course.id)


class AdminLessonDetailView(AdminRequiredMixin, DetailView):
    """Dars tafsiloti."""

    model = Lesson
    template_name = 'admin_user/courses/lesson_detail.html'
    context_object_name = 'lesson'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        lesson = self.get_object()

        # Homework
        context['homework'] = getattr(lesson, 'homework', None)

        # Test
        context['quiz'] = getattr(lesson, 'test', None)

        # Davomat
        context['attendance'] = Attendance.objects.filter(
            lesson=lesson
        ).select_related('student__user')

        # Statistika
        context['attendance_count'] = context['attendance'].count()
        context['present_count'] = context['attendance'].filter(
            status='present'
        ).count()

        return context


# ═══════════════════════════════════════════════════════════════
# ADMIN: DARS KUNI TASDIQLASH (WORKFLOW)
# ═══════════════════════════════════════════════════════════════

class LessonDayApprovalView(AdminRequiredMixin, View):
    """
    Dars kuni tasdiqlash va uyga vazifa yuborish.
    Workflow:
    1. O‘qituvchi darsni o‘tgan deb belgilaydi
    2. Admin tasdiqlaydi
    3. Uyga vazifa guruhga yuboriladi
    """

    template_name = 'admin_user/courses/approve_lesson.html'

    def get(self, request, topic_id):
        lesson = get_object_or_404(Lesson, id=topic_id)
        groups = StudentGroup.objects.filter(
            course=lesson.course, is_deleted=False
        )

        context = {
            'lesson': lesson,
            'topic': lesson,  # backward compat
            'groups': groups,
            'homework': getattr(lesson, 'homework', None),
            'quiz': getattr(lesson, 'test', None),
        }
        return render(request, self.template_name, context)

    def post(self, request, topic_id):
        lesson = get_object_or_404(Lesson, id=topic_id)
        action = request.POST.get('action', '')

        try:
            with transaction.atomic():
                # 1. O‘tilgan deb belgilash
                if action == 'mark_completed' or not action:
                    lesson.status = 'completed'
                    lesson.lesson_date = timezone.now().date()
                    lesson.save(update_fields=['status', 'lesson_date'])

                    log_audit(
                        request.user, 'approve', lesson,
                        f"Dars o‘tilgan deb belgilandi: {lesson.title}"
                    )

                    messages.success(
                        request,
                        f"✅ '{lesson.title}' o‘tilgan deb belgilandi."
                    )

                # 2. Uyga vazifa yuborish
                group_ids = request.POST.getlist('group_ids')
                homework = getattr(lesson, 'homework', None)

                if group_ids and homework:
                    total_sent = 0
                    total_failed = 0

                    for group_id in group_ids:
                        group = get_object_or_404(StudentGroup, id=group_id)

                        # Tasdiqlash
                        homework.is_approved = True
                        homework.approved_by = request.user
                        homework.approved_at = timezone.now()
                        homework.save()

                        # Yuborish
                        result = send_homework_to_group(
                            homework, group, request.user
                        )

                        if result.get('success'):
                            total_sent += result.get('sent_count', 0)
                            total_failed += result.get('failed_count', 0)

                            # sent_to_groups ga qo‘shish
                            homework.sent_to_groups.add(group)

                    log_audit(
                        request.user, 'send', homework,
                        f"Uyga vazifa {len(group_ids)} ta guruhga yuborildi"
                    )

                    messages.success(
                        request,
                        f"📤 Uyga vazifa yuborildi: "
                        f"{total_sent} ta talaba"
                    )

                    if total_failed:
                        messages.warning(
                            request,
                            f"⚠️ {total_failed} ta talabaga yuborilmadi"
                        )

                return redirect('admin_course_detail', pk=lesson.course.id)

        except Exception as e:
            messages.error(request, f"❌ Xatolik: {e}")
            return redirect('admin_course_detail', pk=lesson.course.id)


# ═══════════════════════════════════════════════════════════════
# ADMIN: UYGA VAZIFA BOSHQARUVI
# ═══════════════════════════════════════════════════════════════

class AdminHomeworkListView(AdminRequiredMixin, ListView):
    """Uyga vazifalar ro‘yxati."""

    model = Homework
    template_name = 'admin_user/courses/homework_list.html'
    context_object_name = 'homeworks'
    paginate_by = 20

    def get_queryset(self):
        queryset = Homework.objects.filter(
            is_deleted=False
        ).select_related('lesson__course', 'created_by')

        # Filterlar
        course_id = self.request.GET.get('course')
        if course_id:
            queryset = queryset.filter(lesson__course_id=course_id)

        status = self.request.GET.get('status', 'all')
        if status == 'pending':
            queryset = queryset.filter(is_approved=False)
        elif status == 'approved':
            queryset = queryset.filter(is_approved=True, is_sent=False)
        elif status == 'sent':
            queryset = queryset.filter(is_sent=True)

        return queryset.order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['courses'] = Course.objects.filter(is_deleted=False)
        context['current_course'] = self.request.GET.get('course', '')
        context['current_status'] = self.request.GET.get('status', 'all')

        # Statistika
        context['total'] = Homework.objects.filter(is_deleted=False).count()
        context['pending'] = Homework.objects.filter(
            is_approved=False, is_deleted=False
        ).count()
        context['sent'] = Homework.objects.filter(
            is_sent=True, is_deleted=False
        ).count()

        return context


class AdminHomeworkDetailView(AdminRequiredMixin, DetailView):
    """Uyga vazifa tafsiloti."""

    model = Homework
    template_name = 'admin_user/courses/homework_detail.html'
    context_object_name = 'homework'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        homework = self.get_object()

        # Topshiriqlar
        context['submissions'] = homework.submissions.filter(
            is_latest=True
        ).select_related('student__user', 'graded_by').order_by('-submitted_at')

        # Statistika
        context['total_students'] = homework.recipients.count()
        context['submitted_count'] = context['submissions'].count()
        context['graded_count'] = context['submissions'].filter(
            score__isnull=False
        ).count()
        context['pending_count'] = context['submissions'].filter(
            score__isnull=True
        ).count()
        context['late_count'] = context['submissions'].filter(
            is_late=True
        ).count()

        return context


class AdminHomeworkCreateView(AdminRequiredMixin, View):
    """Uyga vazifa yaratish."""

    template_name = 'admin_user/courses/homework_form.html'

    def get(self, request, lesson_id):
        lesson = get_object_or_404(Lesson, id=lesson_id)

        # Mavjud homework ni tekshirish
        existing = getattr(lesson, 'homework', None)

        context = {
            'lesson': lesson,
            'homework': existing,
            'quizzes': Quiz.objects.filter(is_active=True),
            'type_choices': Homework._meta.get_field('homework_type').choices,
        }
        return render(request, self.template_name, context)

    def post(self, request, lesson_id):
        lesson = get_object_or_404(Lesson, id=lesson_id)

        try:
            with transaction.atomic():
                homework, created = Homework.objects.update_or_create(
                    lesson=lesson,
                    defaults={
                        'title': request.POST.get('title', '').strip(),
                        'short_description': request.POST.get('short_description', '').strip(),
                        'description': request.POST.get('description', '').strip(),
                        'instructions': request.POST.get('instructions', '').strip(),
                        'homework_type': request.POST.get('homework_type', 'coding'),
                        'starter_code': request.POST.get('starter_code', '').strip(),
                        'solution_code': request.POST.get('solution_code', '').strip(),
                        'deadline_days': int(request.POST.get('deadline_days', 3)),
                        'max_score': int(request.POST.get('max_score', 100)),
                        'coins_reward': int(request.POST.get('coins_reward', 10)),
                        'xp_reward': int(request.POST.get('xp_reward', 50)),
                        'quiz_id': request.POST.get('quiz') or None,
                        'created_by': request.user,
                    }
                )

                # Fayl
                if 'task_file' in request.FILES:
                    homework.task_file = request.FILES['task_file']
                    homework.save()

                log_audit(
                    request.user,
                    'create' if created else 'update',
                    homework,
                    f"Uyga vazifa: {homework.title}"
                )

                messages.success(
                    request,
                    f"✅ Uyga vazifa {'yaratildi' if created else 'yangilandi'}!"
                )
                return redirect('admin_homework_detail', pk=homework.pk)

        except Exception as e:
            messages.error(request, f"❌ Xatolik: {e}")
            return redirect('admin_course_detail', pk=lesson.course.id)


class AdminHomeworkApproveView(AdminRequiredMixin, View):
    """Uyga vazifani tasdiqlash."""

    def post(self, request, pk):
        homework = get_object_or_404(Homework, pk=pk)

        homework.is_approved = True
        homework.approved_by = request.user
        homework.approved_at = timezone.now()
        homework.save()

        log_audit(
            request.user, 'approve', homework,
            f"Uyga vazifa tasdiqlandi: {homework.title}"
        )

        return JsonResponse({'success': True, 'message': 'Tasdiqlandi'})


class AdminHomeworkSendView(AdminRequiredMixin, View):
    """Uyga vazifani guruhlarga yuborish."""

    def post(self, request, pk):
        homework = get_object_or_404(Homework, pk=pk)

        if not homework.is_approved:
            return JsonResponse({
                'success': False,
                'error': 'Avval tasdiqlang!'
            }, status=400)

        group_ids = request.POST.getlist('group_ids')

        if not group_ids:
            return JsonResponse({
                'success': False,
                'error': 'Guruh tanlanmagan!'
            }, status=400)

        try:
            total_sent = 0
            total_failed = 0

            for group_id in group_ids:
                group = get_object_or_404(StudentGroup, id=group_id)

                result = send_homework_to_group(homework, group, request.user)

                if result.get('success'):
                    total_sent += result.get('sent_count', 0)
                    total_failed += result.get('failed_count', 0)
                    homework.sent_to_groups.add(group)

            # Yangilash
            homework.is_sent = True
            homework.sent_at = timezone.now()
            homework.save()

            log_audit(
                request.user, 'send', homework,
                f"{total_sent} ta talabaga yuborildi"
            )

            return JsonResponse({
                'success': True,
                'sent_count': total_sent,
                'failed_count': total_failed,
                'message': f'{total_sent} ta talabaga yuborildi'
            })

        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)


# ═══════════════════════════════════════════════════════════════
# ADMIN: TOPSHIRIQLARNI BAHOLASH
# ═══════════════════════════════════════════════════════════════

class AdminSubmissionListView(AdminRequiredMixin, ListView):
    """Barcha topshiriqlar."""

    model = HomeworkSubmission
    template_name = 'admin_user/courses/submission_list.html'
    context_object_name = 'submissions'
    paginate_by = 30

    def get_queryset(self):
        queryset = HomeworkSubmission.objects.filter(
            is_latest=True
        ).select_related(
            'student__user', 'homework', 'graded_by'
        )

        # Filterlar
        homework_id = self.request.GET.get('homework')
        if homework_id:
            queryset = queryset.filter(homework_id=homework_id)

        status = self.request.GET.get('status', 'all')
        if status != 'all':
            queryset = queryset.filter(status=status)

        if self.request.GET.get('late') == '1':
            queryset = queryset.filter(is_late=True)

        return queryset.order_by('-submitted_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['status_choices'] = HomeworkSubmission._meta.get_field('status').choices
        context['current_status'] = self.request.GET.get('status', 'all')
        context['show_late'] = self.request.GET.get('late') == '1'

        # Statistika
        context['total'] = HomeworkSubmission.objects.filter(
            is_latest=True
        ).count()
        context['pending'] = HomeworkSubmission.objects.filter(
            is_latest=True, score__isnull=True
        ).count()
        context['graded'] = HomeworkSubmission.objects.filter(
            is_latest=True, score__isnull=False
        ).count()
        context['late'] = HomeworkSubmission.objects.filter(
            is_latest=True, is_late=True
        ).count()

        return context


class AdminSubmissionGradeView(AdminRequiredMixin, View):
    """Topshiriqni baholash."""

    def get(self, request, pk):
        submission = get_object_or_404(HomeworkSubmission, pk=pk)

        context = {
            'submission': submission,
            'homework': submission.homework,
            'student': submission.student,
        }
        return render(request, 'admin_user/courses/grade_submission.html', context)

    def post(self, request, pk):
        submission = get_object_or_404(HomeworkSubmission, pk=pk)

        try:
            score = int(request.POST.get('score', 0))
            feedback = request.POST.get('feedback', '').strip()

            submission.grade(score, request.user, feedback)

            # Adminga xabar
            try:
                notify_admin_about_submission(submission)
            except Exception:
                pass

            log_audit(
                request.user, 'grade', submission,
                f"Baholandi: {score}/{submission.homework.max_score}"
            )

            messages.success(
                request,
                f"✅ {submission.student.user.get_full_name()} "
                f"baholandi: {score} ball"
            )

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'score': score,
                    'percent': submission.percent,
                    'grade': submission.grade_letter,
                })

            return redirect('admin_submission_detail', pk=submission.pk)

        except Exception as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': str(e)}, status=400)

            messages.error(request, f"❌ Xatolik: {e}")
            return redirect('admin_submission_detail', pk=submission.pk)


# ═══════════════════════════════════════════════════════════════
# TALABA: KURSLAR RO‘YXATI
# ═══════════════════════════════════════════════════════════════

class StudentCourseListView(LoginRequiredMixin, ListView):
    """Talaba uchun kurslar."""

    model = Course
    template_name = 'student/courses/list.html'
    context_object_name = 'courses'
    paginate_by = 12

    def get_queryset(self):
        user = self.request.user
        queryset = Course.objects.filter(
            is_active=True, is_deleted=False,
            status='published'
        ).select_related('category', 'teacher')

        # Talaba guruhlariga tegishli kurslar
        if hasattr(user, 'student_profile'):
            group_ids = user.student_profile.groups.values_list('id', flat=True)
            enrolled_ids = Enrollment.objects.filter(
                student=user.student_profile,
                status='active'
            ).values_list('course_id', flat=True)

            queryset = queryset.filter(
                Q(groups__id__in=group_ids) | Q(id__in=enrolled_ids)
            ).distinct()

        # Filterlar
        search = self.request.GET.get('search', '').strip()
        if search:
            queryset = queryset.filter(title__icontains=search)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Talabaning yozilishlari
        if hasattr(self.request.user, 'student_profile'):
            context['enrollments'] = {
                e.course_id: e
                for e in Enrollment.objects.filter(
                    student=self.request.user.student_profile
                )
            }

        return context


class StudentCourseDetailView(LoginRequiredMixin, DetailView):
    """Talaba uchun kurs tafsiloti."""

    model = Course
    template_name = 'student/courses/detail.html'
    context_object_name = 'course'

    def get_object(self, queryset=None):
        pk = self.kwargs.get('pk')
        course = get_object_or_404(Course, pk=pk, is_active=True, is_deleted=False)

        # Ruxsat tekshirish
        if self.request.user.role == 'student':
            student = getattr(self.request.user, 'student_profile', None)
            if student:
                group_ids = student.groups.values_list('id', flat=True)
                enrolled = Enrollment.objects.filter(
                    student=student, course=course, status='active'
                ).exists()

                if not enrolled and not course.groups.filter(id__in=group_ids).exists():
                    raise Http404("Ruxsat yo‘q!")

        return course

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        course = self.get_object()

        # Oylar
        context['months'] = course.months.prefetch_related('lessons').order_by('month_number')

        # Yozilish
        enrollment = None
        if hasattr(self.request.user, 'student_profile'):
            enrollment = Enrollment.objects.filter(
                student=self.request.user.student_profile,
                course=course
            ).first()
        context['enrollment'] = enrollment

        # Darslar
        if enrollment:
            completed_lessons = Attendance.objects.filter(
                student=enrollment.student,
                status__in=['present', 'online'],
                lesson__course=course,
            ).values_list('lesson_id', flat=True)
            context['completed_lesson_ids'] = set(completed_lessons)

        return context


# ═══════════════════════════════════════════════════════════════
# TALABA: DARS KO‘RISH
# ═══════════════════════════════════════════════════════════════

class StudentLessonView(StudentRequiredMixin, DetailView):
    """Talaba uchun dars."""

    model = Lesson
    template_name = 'student/courses/lesson.html'
    context_object_name = 'lesson'

    def get_object(self, queryset=None):
        pk = self.kwargs.get('pk')
        lesson = get_object_or_404(
            Lesson, pk=pk, is_published=True, is_deleted=False
        )

        # Ruxsat tekshirish
        student = getattr(self.request.user, 'student_profile', None)
        if student:
            group_ids = student.groups.values_list('id', flat=True)
            if not lesson.course.groups.filter(id__in=group_ids).exists():
                raise Http404("Ruxsat yo‘q!")

        # Ko‘rishlar sonini oshirish
        lesson.increment_view()

        return lesson

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        lesson = self.get_object()

        # Homework
        context['homework'] = getattr(lesson, 'homework', None)

        # Test
        context['quiz'] = getattr(lesson, 'test', None)

        # Talabaning topshirig‘i
        if hasattr(self.request.user, 'student_profile'):
            student = self.request.user.student_profile
            context['submission'] = HomeworkSubmission.objects.filter(
                homework__lesson=lesson,
                student=student,
                is_latest=True,
            ).first()

            # Test urinishi
            context['attempt'] = QuizAttempt.objects.filter(
                quiz__lesson=lesson,
                student=student,
            ).order_by('-started_at').first()

        # Keyingi va oldingi darslar
        context['prev_lesson'] = Lesson.objects.filter(
            course=lesson.course,
            order__lt=lesson.order,
            is_published=True,
        ).order_by('-order').first()

        context['next_lesson'] = Lesson.objects.filter(
            course=lesson.course,
            order__gt=lesson.order,
            is_published=True,
        ).order_by('order').first()

        return context


# ═══════════════════════════════════════════════════════════════
# TALABA: UYGA VAZIFALAR
# ═══════════════════════════════════════════════════════════════

class StudentHomeworkListView(StudentRequiredMixin, ListView):
    """Talabaning uyga vazifalari."""

    template_name = 'student/homework/list.html'
    context_object_name = 'homeworks'
    paginate_by = 10

    def get_queryset(self):
        student = self.request.user.student_profile
        group_ids = student.groups.values_list('id', flat=True)

        # Faqat guruhga yuborilgan vazifalar
        return Homework.objects.filter(
            is_approved=True,
            is_sent=True,
            sent_to_groups__id__in=group_ids,
        ).distinct().select_related(
            'lesson__course', 'lesson__month'
        ).order_by('-sent_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        student = self.request.user.student_profile

        # Topshirilgan vazifalar
        context['submitted_ids'] = set(
            HomeworkSubmission.objects.filter(
                student=student,
                is_latest=True,
            ).values_list('homework_id', flat=True)
        )

        # Statistika
        context['total'] = Homework.objects.filter(
            is_approved=True, is_sent=True
        ).count()
        context['completed'] = len(context['submitted_ids'])
        context['pending'] = context['total'] - context['completed']

        return context


class StudentHomeworkDetailView(StudentRequiredMixin, View):
    """Uyga vazifa tafsiloti va topshirish."""

    template_name = 'student/homework/detail.html'

    def get(self, request, homework_id):
        homework = get_object_or_404(
            Homework, id=homework_id,
            is_approved=True, is_sent=True
        )

        student = request.user.student_profile

        # Ruxsat tekshirish
        group_ids = student.groups.values_list('id', flat=True)
        if not homework.sent_to_groups.filter(id__in=group_ids).exists():
            raise Http404("Ruxsat yo‘q!")

        # Talabaning topshirig‘i
        submission = HomeworkSubmission.objects.filter(
            homework=homework,
            student=student,
            is_latest=True,
        ).first()

        # Deadline
        deadline = homework.get_deadline(student)

        context = {
            'homework': homework,
            'submission': submission,
            'deadline': deadline,
            'is_past_deadline': deadline and timezone.now() > deadline,
            'time_remaining': deadline - timezone.now() if deadline else None,
        }

        # Ko‘rishlar +1
        Homework.objects.filter(pk=homework.pk).update(
            views_count=F('views_count') + 1
        )

        return render(request, self.template_name, context)

    def post(self, request, homework_id):
        homework = get_object_or_404(Homework, id=homework_id)
        student = request.user.student_profile

        # Mavjud topshiriqni tekshirish
        existing = HomeworkSubmission.objects.filter(
            homework=homework,
            student=student,
            is_latest=True,
        ).first()

        if existing and existing.is_graded:
            messages.warning(request, "Siz allaqachon topshirgansiz va baholangan!")
            return redirect('student_homework_detail', homework_id=homework.id)

        try:
            with transaction.atomic():
                deadline = homework.get_deadline(student)
                is_late = deadline and timezone.now() > deadline

                # Resubmit
                if existing:
                    submission = existing.resubmit(
                        answer_text=request.POST.get('answer_text', ''),
                        answer_code=request.POST.get('answer_code', ''),
                    )
                    if 'answer_file' in request.FILES:
                        submission.answer_file = request.FILES['answer_file']
                        submission.save()
                else:
                    submission = HomeworkSubmission.objects.create(
                        homework=homework,
                        student=student,
                        answer_text=request.POST.get('answer_text', ''),
                        answer_code=request.POST.get('answer_code', ''),
                        deadline=deadline,
                        is_late=is_late,
                        status='late' if is_late else 'pending',
                        time_spent_minutes=int(request.POST.get('time_spent', 0)),
                    )

                    if 'answer_file' in request.FILES:
                        submission.answer_file = request.FILES['answer_file']
                        submission.save()

                # Adminga xabar
                try:
                    notify_admin_about_submission(submission)
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(f"Admin xabar: {e}")

                log_audit(
                    student.user, 'create', submission,
                    f"Topshiriq yuborildi: {homework.title}"
                )

                messages.success(
                    request,
                    "✅ Uyga vazifa topshirildi! "
                    "Ustoz tez orada baholaydi."
                )

                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': True,
                        'message': 'Topshiriq qabul qilindi',
                        'redirect': reverse('student_homework_list'),
                    })

                return redirect('student_homework_list')

        except Exception as e:
            messages.error(request, f"❌ Xatolik: {e}")

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': str(e)}, status=400)

            return redirect('student_homework_detail', homework_id=homework.id)


# ═══════════════════════════════════════════════════════════════
# TALABA: TEST TOPSHIRISH
# ═══════════════════════════════════════════════════════════════

class StudentQuizStartView(StudentRequiredMixin, View):
    """Testni boshlash."""

    def post(self, request, quiz_id):
        quiz = get_object_or_404(Quiz, id=quiz_id, is_active=True)
        student = request.user.student_profile

        # Urinishlar sonini tekshirish
        attempts_count = QuizAttempt.objects.filter(
            quiz=quiz, student=student
        ).count()

        if attempts_count >= quiz.max_attempts:
            return JsonResponse({
                'success': False,
                'error': f"Maksimal {quiz.max_attempts} marta topshirish mumkin!"
            }, status=400)

        # Yangi urinish
        attempt = QuizAttempt.objects.create(
            quiz=quiz,
            student=student,
            attempt_number=attempts_count + 1,
            max_score=quiz.total_points,
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
        )

        return JsonResponse({
            'success': True,
            'attempt_id': attempt.id,
            'redirect': reverse('student_quiz_take', kwargs={'attempt_id': attempt.id})
        })


class StudentQuizTakeView(StudentRequiredMixin, View):
    """Test jarayoni — savol-savol."""

    template_name = 'student/quiz/take.html'

    def get(self, request, attempt_id):
        attempt = get_object_or_404(
            QuizAttempt, id=attempt_id, student=request.user.student_profile
        )

        if attempt.status != 'in_progress':
            return redirect('student_quiz_result', attempt_id=attempt.id)

        # Vaqt tekshirish
        time_limit = attempt.started_at + timedelta(
            minutes=attempt.quiz.duration_minutes
        )
        time_remaining = (time_limit - timezone.now()).total_seconds()

        if time_remaining <= 0:
            attempt.status = 'expired'
            attempt.completed_at = timezone.now()
            attempt.save()
            return redirect('student_quiz_result', attempt_id=attempt.id)

        # Savollarni olish
        questions = list(attempt.quiz.questions.order_by('order'))

        if attempt.quiz.shuffle_questions:
            import random
            random.shuffle(questions)

        # Javob berilganlar
        answered_ids = set(
            attempt.answers.values_list('question_id', flat=True)
        )

        context = {
            'attempt': attempt,
            'quiz': attempt.quiz,
            'questions': questions,
            'answered_ids': answered_ids,
            'time_remaining': int(time_remaining),
            'total_questions': len(questions),
        }

        return render(request, self.template_name, context)

    def post(self, request, attempt_id):
        attempt = get_object_or_404(
            QuizAttempt, id=attempt_id, student=request.user.student_profile
        )

        if attempt.status != 'in_progress':
            return JsonResponse({'success': False, 'error': 'Test yakunlangan'})

        action = request.POST.get('action', '')

        # Testni yakunlash
        if action == 'finish':
            try:
                self._finalize_attempt(attempt)

                return JsonResponse({
                    'success': True,
                    'redirect': reverse('student_quiz_result', kwargs={'attempt_id': attempt.id})
                })
            except Exception as e:
                return JsonResponse({'success': False, 'error': str(e)}, status=400)

        # Savolga javob berish
        question_id = request.POST.get('question_id')
        question = get_object_or_404(Question, id=question_id, quiz=attempt.quiz)

        # Oldingi javobni o‘chirish
        attempt.answers.filter(question=question).delete()

        # Yangi javob
        answer = AttemptAnswer.objects.create(
            attempt=attempt,
            question=question,
            text_answer=request.POST.get('text_answer', ''),
            code_answer=request.POST.get('code_answer', ''),
            time_spent_seconds=int(request.POST.get('time_spent', 0)),
        )

        # Tanlangan variantlar
        option_ids = request.POST.getlist('options')
        if option_ids:
            answer.selected_options.set(option_ids)

        # To‘g‘rilikni tekshirish
        is_correct = self._check_answer(answer, question)
        answer.is_correct = is_correct

        if is_correct:
            answer.points_earned = question.points

        answer.save()

        # Progress
        total_questions = attempt.quiz.questions.count()
        answered = attempt.answers.count()
        progress = round((answered / total_questions) * 100)

        return JsonResponse({
            'success': True,
            'is_correct': is_correct if attempt.quiz.show_correct_answers else None,
            'correct_answer': self._get_correct_answer(question) if attempt.quiz.show_correct_answers else None,
            'explanation': question.explanation if attempt.quiz.show_correct_answers else None,
            'progress': progress,
            'answered': answered,
            'total': total_questions,
        })

    def _check_answer(self, answer, question):
        """Javobni tekshirish."""
        if question.question_type in ('single', 'multiple', 'true_false'):
            correct_ids = set(
                question.options.filter(is_correct=True).values_list('id', flat=True)
            )
            selected_ids = set(
                answer.selected_options.values_list('id', flat=True)
            )
            return correct_ids == selected_ids

        elif question.question_type == 'text':
            return answer.text_answer.strip().lower() == question.correct_text.strip().lower()

        elif question.question_type == 'number':
            if answer.number_answer is None or question.correct_number is None:
                return False
            diff = abs(answer.number_answer - question.correct_number)
            return diff <= question.number_tolerance

        return False

    def _get_correct_answer(self, question):
        """To‘g‘ri javobni ko‘rsatish."""
        if question.question_type in ('single', 'multiple', 'true_false'):
            return list(
                question.options.filter(is_correct=True).values_list('text', flat=True)
            )
        elif question.question_type == 'text':
            return question.correct_text
        elif question.question_type == 'number':
            return str(question.correct_number)
        return None

    def _finalize_attempt(self, attempt):
        """Urinishni yakunlash."""
        with transaction.atomic():
            # Ball hisoblash
            total_score = attempt.answers.aggregate(
                total=Coalesce(Sum('points_earned'), 0)
            )['total']

            correct_count = attempt.answers.filter(is_correct=True).count()
            wrong_count = attempt.answers.filter(is_correct=False, is_skipped=False).count()
            skipped_count = attempt.quiz.questions.count() - attempt.answers.count()

            # Vaqt
            time_spent = int(
                (timezone.now() - attempt.started_at).total_seconds()
            )

            attempt.score = total_score
            attempt.correct_count = correct_count
            attempt.wrong_count = wrong_count
            attempt.skipped_count = skipped_count
            attempt.time_spent_seconds = time_spent
            attempt.completed_at = timezone.now()

            # O‘tganligini tekshirish
            percent = (total_score / attempt.max_score * 100) if attempt.max_score else 0
            attempt.is_passed = percent >= attempt.quiz.passing_score

            # Mukofotlar
            if attempt.is_passed and attempt.quiz.coins_reward:
                attempt.coins_awarded = attempt.quiz.coins_reward

                # Talabaga coin qo‘shish
                StudentProfile.objects.filter(pk=attempt.student.pk).update(
                    coins=F('coins') + attempt.coins_reward
                )

            if attempt.is_passed and attempt.quiz.xp_reward:
                attempt.xp_awarded = attempt.quiz.xp_reward

            attempt.status = 'completed'
            attempt.save()

            # Statistika
            Quiz.objects.filter(pk=attempt.quiz.pk).update(
                attempts_count=F('attempts_count') + 1,
                passes_count=F('passes_count') + (1 if attempt.is_passed else 0),
            )

            log_audit(
                attempt.student.user, 'grade', attempt,
                f"Test yakunlandi: {attempt.score}/{attempt.max_score}"
            )


class StudentQuizResultView(StudentRequiredMixin, DetailView):
    """Test natijasi."""

    model = QuizAttempt
    template_name = 'student/quiz/result.html'
    context_object_name = 'attempt'

    def get_object(self, queryset=None):
        attempt_id = self.kwargs.get('attempt_id')
        return get_object_or_404(
            QuizAttempt, id=attempt_id,
            student=self.request.user.student_profile
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        attempt = self.get_object()

        context['quiz'] = attempt.quiz
        context['answers'] = attempt.answers.select_related('question').order_by(
            'question__order'
        )

        return context


# ═══════════════════════════════════════════════════════════════
# ADMIN: GURUHLAR BOSHQARUVI
# ═══════════════════════════════════════════════════════════════

class AdminGroupListView(AdminRequiredMixin, ListView):
    """Guruhlar ro‘yxati."""

    model = StudentGroup
    template_name = 'admin_user/groups/list.html'
    context_object_name = 'groups'
    paginate_by = 20

    def get_queryset(self):
        queryset = StudentGroup.objects.filter(
            is_deleted=False
        ).select_related('course', 'teacher').annotate(
            students_count=Count('students', distinct=True)
        )

        # Filterlar
        search = self.request.GET.get('search', '').strip()
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(code__icontains=search)
            )

        course_id = self.request.GET.get('course')
        if course_id:
            queryset = queryset.filter(course_id=course_id)

        status = self.request.GET.get('status', 'all')
        if status != 'all':
            queryset = queryset.filter(status=status)

        return queryset.order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['courses'] = Course.objects.filter(is_deleted=False)
        context['status_choices'] = StudentGroup._meta.get_field('status').choices
        context['current_status'] = self.request.GET.get('status', 'all')

        context['total_groups'] = StudentGroup.objects.filter(is_deleted=False).count()
        context['active_groups'] = StudentGroup.objects.filter(
            status='active', is_deleted=False
        ).count()
        context['total_students'] = StudentProfile.objects.filter(
            groups__isnull=False
        ).distinct().count()

        return context


class AdminGroupDetailView(AdminRequiredMixin, DetailView):
    """Guruh tafsiloti."""

    model = StudentGroup
    template_name = 'admin_user/groups/detail.html'
    context_object_name = 'group'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        group = self.get_object()

        context['students'] = group.students.select_related('user').all()
        context['lessons'] = group.lessons.order_by('-lesson_date')[:10]
        context['homework_sent'] = Homework.objects.filter(
            sent_to_groups=group
        ).order_by('-sent_at')[:10]

        # Statistika
        context['statistics'] = group.get_statistics()
        context['ranking'] = group.get_ranking(10)

        return context


class AdminGroupCreateView(AdminRequiredMixin, View):
    """Guruh yaratish."""

    template_name = 'admin_user/groups/form.html'

    def get(self, request):
        context = {
            'courses': Course.objects.filter(is_deleted=False),
            'teachers': CustomUser.objects.filter(role='teacher', is_active=True),
            'status_choices': StudentGroup._meta.get_field('status').choices,
        }
        return render(request, self.template_name, context)

    def post(self, request):
        try:
            with transaction.atomic():
                group = StudentGroup.objects.create(
                    name=request.POST.get('name', '').strip(),
                    code=request.POST.get('code', '').strip() or None,
                    description=request.POST.get('description', '').strip(),
                    course_id=request.POST.get('course') or None,
                    teacher_id=request.POST.get('teacher') or None,
                    max_students=int(request.POST.get('max_students', 20)),
                    status=request.POST.get('status', 'active'),
                    start_date=request.POST.get('start_date') or None,
                    end_date=request.POST.get('end_date') or None,
                    room=request.POST.get('room', '').strip(),
                    color=request.POST.get('color', '#6366f1'),
                )

                # Jadval
                schedule = {}
                for day in ['monday', 'tuesday', 'wednesday', 'thursday',
                            'friday', 'saturday', 'sunday']:
                    time = request.POST.get(f'schedule_{day}')
                    if time:
                        schedule[day] = time
                group.schedule = schedule
                group.save()

                log_audit(
                    request.user, 'create', group,
                    f"Guruh yaratildi: {group.name}"
                )

                messages.success(request, f"✅ '{group.name}' guruhi yaratildi!")
                return redirect('admin_group_detail', pk=group.pk)

        except Exception as e:
            messages.error(request, f"❌ Xatolik: {e}")
            return redirect('admin_group_list')


class AdminGroupAddStudentView(AdminRequiredMixin, View):
    """Guruhga talaba qo‘shish."""

    def post(self, request, pk):
        group = get_object_or_404(StudentGroup, pk=pk)
        student_ids = request.POST.getlist('student_ids')

        if not student_ids:
            return JsonResponse({
                'success': False,
                'error': 'Talaba tanlanmagan'
            }, status=400)

        try:
            added = 0
            for student_id in student_ids:
                student = get_object_or_404(StudentProfile, id=student_id)

                if group.students_count >= group.max_students:
                    return JsonResponse({
                        'success': False,
                        'error': 'Guruh to‘lgan!'
                    }, status=400)

                if not group.students.filter(id=student_id).exists():
                    group.students.add(student)
                    GroupMember.objects.get_or_create(
                        group=group,
                        student=student,
                        defaults={'role': 'student'}
                    )
                    added += 1

            messages.success(request, f"✅ {added} ta talaba qo‘shildi")

            return JsonResponse({
                'success': True,
                'added': added,
                'message': f'{added} ta talaba qo‘shildi'
            })

        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)


class AdminGroupRemoveStudentView(AdminRequiredMixin, View):
    """Guruhdan talabani chiqarish."""

    def post(self, request, pk, student_id):
        group = get_object_or_404(StudentGroup, pk=pk)
        student = get_object_or_404(StudentProfile, id=student_id)

        group.students.remove(student)
        GroupMember.objects.filter(group=group, student=student).update(
            is_active=False,
            left_at=timezone.now().date()
        )

        return JsonResponse({'success': True})


# ═══════════════════════════════════════════════════════════════
# ADMIN: STATISTIKA DASHBOARD
# ═══════════════════════════════════════════════════════════════

class AdminCoursesStatisticsView(AdminRequiredMixin, TemplateView):
    """Kurslar bo‘yicha statistika."""

    template_name = 'admin_user/courses/statistics.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Umumiy statistika
        context['total_courses'] = Course.objects.filter(is_deleted=False).count()
        context['published_courses'] = Course.objects.filter(
            status='published', is_deleted=False
        ).count()
        context['total_students'] = StudentProfile.objects.count()
        context['total_groups'] = StudentGroup.objects.filter(is_deleted=False).count()
        context['total_lessons'] = Lesson.objects.count()
        context['total_homework'] = Homework.objects.filter(is_deleted=False).count()
        context['total_submissions'] = HomeworkSubmission.objects.count()
        context['pending_grading'] = HomeworkSubmission.objects.filter(
            is_latest=True, score__isnull=True
        ).count()

        # Oylik statistika (oxirgi 12 oy)
        from django.db.models.functions import TruncMonth
        monthly_stats = Enrollment.objects.annotate(
            month=TruncMonth('enrolled_at')
        ).values('month').annotate(
            count=Count('id')
        ).order_by('month')

        context['monthly_labels'] = [
            s['month'].strftime('%Y-%m') for s in monthly_stats
        ]
        context['monthly_data'] = [s['count'] for s in monthly_stats]

        # Top kurslar
        context['top_courses'] = Course.objects.filter(
            is_deleted=False
        ).annotate(
            students_count=Count('enrollments', distinct=True),
            avg_rating=Avg('reviews__rating'),
        ).order_by('-students_count')[:10]

        # Top o‘qituvchilar
        context['top_teachers'] = CustomUser.objects.filter(
            role='teacher', is_active=True
        ).annotate(
            courses_count=Count('courses_teaching', distinct=True),
            students_count=Count('courses_teaching__enrollments', distinct=True),
        ).order_by('-students_count')[:10]

        # So‘nggi faoliyat
        context['recent_activities'] = AuditLog.objects.select_related('user').order_by(
            '-created_at'
        )[:20]

        # Reyting
        context['rating_distribution'] = Review.objects.values('rating').annotate(
            count=Count('id')
        ).order_by('rating')

        return context


# ═══════════════════════════════════════════════════════════════
# AJAX ENDPOINTS
# ═══════════════════════════════════════════════════════════════

class AjaxCourseSearchView(AdminRequiredMixin, View):
    """Kurs qidirish (autocomplete uchun)."""

    def get(self, request):
        query = request.GET.get('q', '').strip()

        if len(query) < 2:
            return JsonResponse({'results': []})

        courses = Course.objects.filter(
            Q(title__icontains=query) | Q(slug__icontains=query),
            is_deleted=False,
        ).values('id', 'title', 'slug')[:20]

        return JsonResponse({
            'results': [
                {
                    'id': c['id'],
                    'text': c['title'],
                    'url': reverse('admin_course_detail', kwargs={'pk': c['id']}),
                }
                for c in courses
            ]
        })


class AjaxStudentSearchView(AdminRequiredMixin, View):
    """Talaba qidirish."""

    def get(self, request):
        query = request.GET.get('q', '').strip()

        if len(query) < 2:
            return JsonResponse({'results': []})

        students = StudentProfile.objects.filter(
            Q(user__first_name__icontains=query) |
            Q(user__last_name__icontains=query) |
            Q(user__phone_number__icontains=query)
        ).select_related('user')[:20]

        return JsonResponse({
            'results': [
                {
                    'id': s.id,
                    'text': f"{s.user.get_full_name()} ({s.user.phone_number})",
                    'avatar': s.user.avatar_url if hasattr(s.user, 'avatar_url') else None,
                }
                for s in students
            ]
        })


class AjaxGroupStatsView(AdminRequiredMixin, View):
    """Guruh statistikasi (dashboard uchun)."""

    def get(self, request, pk):
        group = get_object_or_404(StudentGroup, pk=pk)

        return JsonResponse({
            'stats': group.get_statistics(),
            'ranking': [
                {
                    'name': s.user.get_full_name(),
                    'score': getattr(s, 'total_score', 0),
                    'coins': s.coins,
                }
                for s in group.get_ranking(10)
            ]
        })


class AjaxHomeworkStatsView(AdminRequiredMixin, View):
    """Uyga vazifa statistikasi."""

    def get(self, request, pk):
        homework = get_object_or_404(Homework, pk=pk)

        submissions = homework.submissions.filter(is_latest=True)

        return JsonResponse({
            'total_students': homework.total_students,
            'submitted': submissions.count(),
            'graded': submissions.filter(score__isnull=False).count(),
            'pending': submissions.filter(score__isnull=True).count(),
            'late': submissions.filter(is_late=True).count(),
            'avg_score': float(
                submissions.filter(score__isnull=False).aggregate(
                    avg=Avg('score')
                )['avg'] or 0
            ),
            'scores': [
                {
                    'student': s.student.user.get_full_name(),
                    'score': s.score,
                    'percent': s.percent,
                }
                for s in submissions.filter(score__isnull=False)[:50]
            ]
        })


class AjaxMarkAttendanceView(TeacherRequiredMixin, View):
    """Davomatni belgilash."""

    def post(self, request, lesson_id):
        lesson = get_object_or_404(Lesson, id=lesson_id)

        if request.content_type == 'application/json':
            data = json.loads(request.body)
        else:
            data = request.POST.dict()

        student_id = data.get('student_id')
        status = data.get('status', 'present')

        if not student_id:
            return JsonResponse({'success': False, 'error': 'Talaba kerak'}, status=400)

        student = get_object_or_404(StudentProfile, id=student_id)

        attendance, created = Attendance.objects.update_or_create(
            lesson=lesson,
            student=student,
            defaults={
                'status': status,
                'marked_by': request.user,
                'check_in_time': timezone.now().time(),
            }
        )

        return JsonResponse({
            'success': True,
            'created': created,
            'status': attendance.status,
        })


# ═══════════════════════════════════════════════════════════════
# EXPORT VIEWS
# ═══════════════════════════════════════════════════════════════

class AdminExportCourseCSVView(AdminRequiredMixin, View):
    """Kurslar CSV eksport."""

    def get(self, request):
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="courses.csv"'
        response.write('\ufeff')

        writer = csv.writer(response)
        writer.writerow([
            'ID', 'Nomi', 'Kategoriya', 'O‘qituvchi',
            'Daraja', 'Til', 'Narx', 'Status',
            'Talabalar', 'Reyting', 'Sana'
        ])

        for course in Course.objects.filter(is_deleted=False).select_related(
                'category', 'teacher'
        ):
            writer.writerow([
                course.id,
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


class AdminExportStudentsCSVView(AdminRequiredMixin, View):
    """Talabalar CSV eksport."""

    def get(self, request, group_id=None):
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        filename = f"students_{timezone.now().strftime('%Y%m%d')}.csv"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        response.write('\ufeff')

        writer = csv.writer(response)

        if group_id:
            group = get_object_or_404(StudentGroup, pk=group_id)
            students = group.students.select_related('user')
            writer.writerow(['Guruh', 'Ism', 'Telefon', 'Ball', 'Coinlar'])

            for s in students:
                writer.writerow([
                    group.name,
                    s.user.get_full_name(),
                    s.user.phone_number,
                    s.total_score,
                    s.coins,
                ])
        else:
            students = StudentProfile.objects.select_related('user')
            writer.writerow(['ID', 'Ism', 'Telefon', 'Status', 'Ball', 'Coinlar', 'Guruhlar'])

            for s in students:
                writer.writerow([
                    s.id,
                    s.user.get_full_name(),
                    s.user.phone_number,
                    s.get_status_display(),
                    s.total_score,
                    s.coins,
                    ', '.join(s.groups.values_list('name', flat=True)),
                ])

        return response


class AdminExportCertificatesCSVView(AdminRequiredMixin, View):
    """Sertifikatlar CSV eksport."""

    def get(self, request):
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="certificates.csv"'
        response.write('\ufeff')

        writer = csv.writer(response)
        writer.writerow([
            'Sertifikat №', 'Talaba', 'Telefon', 'Kurs',
            'Baho', 'Ball', 'Berilgan sana', 'Tekshirish kodi'
        ])

        for cert in Certificate.objects.select_related(
                'enrollment__student__user', 'enrollment__course'
        ):
            writer.writerow([
                cert.certificate_number,
                cert.enrollment.student.user.get_full_name(),
                cert.enrollment.student.user.phone_number,
                cert.enrollment.course.title,
                cert.grade,
                cert.score,
                cert.issued_date.strftime('%Y-%m-%d'),
                cert.verification_code,
            ])

        return response


# ═══════════════════════════════════════════════════════════════
# HELPER VIEWS
# ═══════════════════════════════════════════════════════════════

class CertificateVerifyView(View):
    """Sertifikatni tekshirish (public)."""

    def get(self, request, code):
        try:
            cert = Certificate.objects.select_related(
                'enrollment__student__user',
                'enrollment__course',
            ).get(verification_code=code)

            return render(request, 'public/certificate_verify.html', {
                'certificate': cert,
                'is_valid': cert.is_verified,
            })
        except Certificate.DoesNotExist:
            return render(request, 'public/certificate_verify.html', {
                'is_valid': False,
                'error': 'Sertifikat topilmadi',
            }, status=404)


class CoursePreviewView(View):
    """Kurs preview (public)."""

    def get(self, request, slug):
        course = get_object_or_404(
            Course,
            slug=slug,
            status='published',
            is_active=True,
            is_deleted=False,
        )

        # Ko‘rishlar +1
        course.increment_view()

        context = {
            'course': course,
            'months': course.months.prefetch_related('lessons').order_by('month_number'),
            'reviews': course.reviews.filter(is_approved=True)[:10],
            'faqs': course.faqs.filter(is_active=True),
        }

        return render(request, 'public/course_preview.html', context)