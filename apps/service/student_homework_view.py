# apps/service/student_homework_view.py
"""
Student uyga vazifa sahifasi.
URL: /homework/<pk>/?gl=<group_lesson_pk>
"""
import logging

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views import View

from apps.courses.models import (
    Homework,
    HomeworkSubmission,
    GroupLesson,
    SubmissionStatus,
)
from apps.user.models import StudentProfile

from apps.service.telegram_webapp_auth import auto_login_from_request

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# KONSTANTALAR
# ═══════════════════════════════════════════════════════════════

MIN_FILE_SIZE_KB = 5
MAX_FILE_SIZE_MB = 100
MIN_TEXT_LENGTH = 20


# ═══════════════════════════════════════════════════════════════
# ASOSIY VIEW
# ═══════════════════════════════════════════════════════════════

class StudentHomeworkView(View):
    """Talaba uyga vazifa sahifasi."""

    template_name = 'student/homework_detail.html'

    # ═══════════════════════════════════════════════════════════
    # GET
    # ═══════════════════════════════════════════════════════════

    def get(self, request, pk):
        # ─── 1. Auto-login ───
        user = auto_login_from_request(request)
        if not user:
            return render(request, 'student/need_login.html', status=401)

        # ─── 2. Student ───
        student = StudentProfile.objects.filter(user=user).select_related('user').first()
        if not student:
            return render(
                request,
                'student/no_profile.html',
                {'user': user, 'debug': settings.DEBUG},
                status=403,
            )

        # ─── 3. Homework ───
        homework = get_object_or_404(
            Homework.objects
            .filter(is_deleted=False, is_approved=True)
            .select_related('lesson', 'lesson__course'),
            pk=pk,
        )

        # ─── 4. GroupLesson ───
        gl_id = request.GET.get('gl')
        group_lesson = None
        if gl_id:
            try:
                group_lesson = GroupLesson.objects.filter(
                    pk=int(gl_id),
                    lesson=homework.lesson,
                ).select_related('group').first()
            except (ValueError, TypeError):
                pass

        # ─── 5. Oldingi submission ───
        submission = HomeworkSubmission.objects.filter(
            homework=homework,
            student=student,
            is_latest=True,
        ).first()

        # ─── 6. Deadline ───
        deadline = homework.get_deadline(student)
        is_late = bool(deadline and timezone.now() > deadline)

        # ─── 7. Can submit ───
        can_submit = True
        submit_block_reason = ''

        if submission and submission.status == SubmissionStatus.GRADED:
            can_submit = False
            submit_block_reason = "Siz allaqachon topshirgansiz va baholangansiz"
        elif submission and submission.status == SubmissionStatus.PENDING:
            can_submit = False
            submit_block_reason = "Siz topshirgansiz — tekshirilmoqda"
        elif is_late and not homework.allow_late_submission:
            can_submit = False
            submit_block_reason = "Muddat o'tgan — kech topshirish mumkin emas"

        # ─── 8. Context ───
        ctx = {
            'homework': homework,
            'lesson': homework.lesson,
            'course': homework.lesson.course,
            'student': student,
            'user': user,
            'group_lesson': group_lesson,
            'submission': submission,
            'deadline': deadline,
            'is_late': is_late,
            'can_submit': can_submit,
            'submit_block_reason': submit_block_reason,
            'min_file_size_kb': MIN_FILE_SIZE_KB,
            'max_file_size_mb': MAX_FILE_SIZE_MB,
            'min_text_length': MIN_TEXT_LENGTH,
            'debug': settings.DEBUG,
        }
        return render(request, self.template_name, ctx)

    # ═══════════════════════════════════════════════════════════
    # POST — topshirish
    # ═══════════════════════════════════════════════════════════

    def post(self, request, pk):
        # ─── 1. Auth ───
        user = auto_login_from_request(request)
        if not user:
            return JsonResponse(
                {'ok': False, 'error': "Avtorizatsiya xatosi"},
                status=401,
            )

        # ─── 2. Student ───
        student = StudentProfile.objects.filter(user=user).first()
        if not student:
            return JsonResponse(
                {'ok': False, 'error': "Talaba profili topilmadi"},
                status=403,
            )

        # ─── 3. Homework ───
        homework = get_object_or_404(
            Homework,
            pk=pk,
            is_deleted=False,
            is_approved=True,
        )

        # ─── 4. Ma'lumotlar ───
        answer_text = (request.POST.get('answer_text') or '').strip()
        answer_code = (request.POST.get('answer_code') or '').strip()
        answer_file = request.FILES.get('answer_file')

        # ─── 5. Validatsiya ───
        if not (answer_text or answer_code or answer_file):
            return JsonResponse(
                {'ok': False, 'error': "Javob bo'sh — matn, kod yoki fayl kiriting"},
                status=400,
            )

        if answer_text and len(answer_text) < MIN_TEXT_LENGTH and not answer_file and not answer_code:
            return JsonResponse(
                {
                    'ok': False,
                    'error': f"Matn kamida {MIN_TEXT_LENGTH} belgi bo'lishi kerak",
                },
                status=400,
            )

        if answer_file:
            size_kb = answer_file.size / 1024
            size_mb = answer_file.size / (1024 * 1024)
            if size_kb < MIN_FILE_SIZE_KB:
                return JsonResponse(
                    {
                        'ok': False,
                        'error': f"Fayl juda kichik ({size_kb:.1f} KB). Minimal: {MIN_FILE_SIZE_KB} KB",
                    },
                    status=400,
                )
            if size_mb > MAX_FILE_SIZE_MB:
                return JsonResponse(
                    {
                        'ok': False,
                        'error': f"Fayl juda katta ({size_mb:.1f} MB). Maksimal: {MAX_FILE_SIZE_MB} MB",
                    },
                    status=400,
                )

        # ─── 6. Eski submission ───
        old_submission = HomeworkSubmission.objects.filter(
            homework=homework,
            student=student,
            is_latest=True,
        ).first()

        if old_submission:
            if old_submission.status == SubmissionStatus.GRADED:
                return JsonResponse(
                    {'ok': False, 'error': "Siz allaqachon baholangansiz"},
                    status=400,
                )
            old_submission.is_latest = False
            old_submission.save(update_fields=['is_latest'])

        # ─── 7. Deadline ───
        deadline = homework.get_deadline(student)
        is_late = bool(deadline and timezone.now() > deadline)

        if is_late and not homework.allow_late_submission:
            return JsonResponse(
                {'ok': False, 'error': "Muddat o'tgan"},
                status=400,
            )

        # ─── 8. Yangi submission ───
        try:
            submission = HomeworkSubmission.objects.create(
                homework=homework,
                student=student,
                answer_text=answer_text,
                answer_code=answer_code,
                answer_file=answer_file,
                deadline=deadline,
                is_late=is_late,
                is_latest=True,
                resubmit_count=(
                    (old_submission.resubmit_count + 1)
                    if old_submission else 0
                ),
                status=(
                    SubmissionStatus.LATE
                    if is_late
                    else SubmissionStatus.PENDING
                ),
            )
        except Exception as e:
            logger.exception(f"Submission create xatosi: {e}")
            return JsonResponse(
                {'ok': False, 'error': f"Saqlash xatosi: {e}"},
                status=500,
            )

        logger.info(
            f"✅ Submission: student={student.pk}, hw={homework.pk}, "
            f"sub={submission.pk}, late={is_late}"
        )

        # ─── 9. Adminga xabar ───
        try:
            from apps.service.homework_sender import HomeworkSender
            HomeworkSender.notify_admin_for_approval(
                submission,
                notification_type='homework_submitted',
            )
        except Exception as e:
            logger.exception(f"Admin notify xatosi: {e}")

        # ─── 10. Javob ───
        return JsonResponse({
            'ok': True,
            'submission_id': submission.pk,
            'message': "✅ Vazifa topshirildi!",
            'is_late': is_late,
        })

# apps/service/student_homework_view.py — oxiriga qo'shing

class StudentHomeworkListView(View):
    """
    Student — bugungi uyga vazifalar ro'yxati.
    Faqat BUGUNGI kunga tegishli darslar.
    """
    template_name = 'student/homework_list.html'

    def get(self, request):
        # ─── 1. Auto-login ───
        user = auto_login_from_request(request)
        if not user:
            return render(request, 'student/need_login.html', status=401)

        # ─── 2. Student ───
        student = StudentProfile.objects.filter(user=user).select_related('user').first()
        if not student:
            return render(
                request,
                'student/no_profile.html',
                {'user': user, 'debug': settings.DEBUG},
                status=403,
            )

        # ─── 3. BUGUNGI SANA ───
        today = timezone.now().date()

        # ─── 4. Bugungi GroupLesson lar ───
        # Talaba a'zo bo'lgan guruhlar
        student_groups = student.course_groups.all() if hasattr(student, 'course_groups') else []

        today_lessons = GroupLesson.objects.filter(
            group__students=student,
            lesson_date=today,
            is_deleted=False,
        ).select_related(
            'lesson',
            'lesson__homework',
            'lesson__course',
            'group',
        ).order_by('lesson__lesson_number')

        # ─── 5. Har bir GL uchun submission ───
        homework_items = []
        for gl in today_lessons:
            homework = getattr(gl.lesson, 'homework', None)

            # Submission
            submission = None
            if homework:
                submission = HomeworkSubmission.objects.filter(
                    homework=homework,
                    student=student,
                    is_latest=True,
                ).first()

            # Status
            if submission:
                if submission.status == SubmissionStatus.GRADED:
                    status = 'graded'
                    status_text = 'Baholangan'
                    status_icon = '✅'
                    status_color = 'success'
                elif submission.status == SubmissionStatus.PENDING:
                    status = 'pending'
                    status_text = 'Tekshirilmoqda'
                    status_icon = '⏳'
                    status_color = 'warm'
                elif submission.status == SubmissionStatus.LATE:
                    status = 'late'
                    status_text = 'Kechikkan'
                    status_icon = '⚠️'
                    status_color = 'rose'
                else:
                    status = 'submitted'
                    status_text = 'Topshirilgan'
                    status_icon = '📤'
                    status_color = 'primary'
            else:
                # Topshirilmagan
                deadline = homework.get_deadline(student) if homework else None
                is_late = bool(deadline and timezone.now() > deadline)
                if is_late:
                    status = 'missed'
                    status_text = 'Bajarilmagan'
                    status_icon = '❌'
                    status_color = 'rose'
                else:
                    status = 'new'
                    status_text = 'Yangi'
                    status_icon = '🆕'
                    status_color = 'primary'

            homework_items.append({
                'gl': gl,
                'homework': homework,
                'lesson': gl.lesson,
                'course': gl.lesson.course,
                'group': gl.group,
                'submission': submission,
                'status': status,
                'status_text': status_text,
                'status_icon': status_icon,
                'status_color': status_color,
                'has_homework': bool(homework),
                'has_test': hasattr(gl.lesson, 'test'),
                'deadline': homework.get_deadline(student) if homework else None,
            })

        # ─── 6. Statistika ───
        total = len(homework_items)
        completed = sum(1 for i in homework_items if i['status'] in ('graded', 'pending', 'submitted'))
        pending = sum(1 for i in homework_items if i['status'] == 'new')
        missed = sum(1 for i in homework_items if i['status'] == 'missed')
        graded = sum(1 for i in homework_items if i['status'] == 'graded')

        # ─── 7. Context ───
        ctx = {
            'user': user,
            'student': student,
            'today': today,
            'homework_items': homework_items,
            'stats': {
                'total': total,
                'completed': completed,
                'pending': pending,
                'missed': missed,
                'graded': graded,
                'progress': round((completed / total * 100) if total else 0, 1),
            },
            'debug': settings.DEBUG,
        }
        return render(request, self.template_name, ctx)