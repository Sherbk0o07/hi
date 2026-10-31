"""
Test (Quiz) tizimi — talabalar uchun.
"""
from datetime import timedelta

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from apps.user.models import (
    Quiz, Question, AnswerOption, TestResult, TestResultAnswer,
    StudentProfile, StudentQuizAccess, GroupQuizAccess,
)


# ═══════════════════════════════════════════════════════════════
# TESTLAR RO‘YXATI
# ═══════════════════════════════════════════════════════════════

class QuizListView(LoginRequiredMixin, View):
    """Faol testlar ro‘yxati — rolga qarab ruxsatlar bilan."""

    def get(self, request):
        user = request.user
        quizzes = list(Quiz.objects.filter(is_active=True).select_related('category'))

        recent_threshold = timezone.now() - timedelta(hours=24)
        for quiz in quizzes:
            quiz.is_new = quiz.created_at >= recent_threshold

        if user.role == 'student':
            self._annotate_student_access(user, quizzes)
        else:
            for quiz in quizzes:
                quiz.user_can_take = True
                quiz.is_completed = False

        categories = (
            Quiz.objects
            .filter(is_active=True)
            .values_list('category__name', flat=True)
            .distinct()
            .order_by('category__name')
        )

        return render(request, "student/quiz/quiz_list.html", {
            "quizzes": quizzes,
            "categories": [c for c in categories if c],
        })

    def _annotate_student_access(self, user, quizzes):
        """Talaba uchun ruxsat va yakunlangan holatini belgilash."""
        student_profile = getattr(user, 'student_profile', None)

        if not student_profile:
            for quiz in quizzes:
                quiz.user_can_take = False
                quiz.is_completed = False
            return

        # Individual ruxsatlar
        individual = dict(
            StudentQuizAccess.objects
            .filter(student=student_profile)
            .values_list('quiz_id', 'is_allowed')
        )

        # Guruh ruxsatlari
        group_ids = list(student_profile.groups.values_list('id', flat=True))
        group_quiz_ids = set(
            GroupQuizAccess.objects
            .filter(group__in=group_ids, is_allowed=True)
            .values_list('quiz_id', flat=True)
        )

        # Yakunlangan testlar
        completed = set(
            TestResult.objects
            .filter(student=student_profile)
            .values_list('quiz_id', flat=True)
        )

        for quiz in quizzes:
            quiz.user_can_take = (
                individual.get(quiz.id, False) or quiz.id in group_quiz_ids
            )
            quiz.is_completed = quiz.id in completed


# ═══════════════════════════════════════════════════════════════
# TEST TOPSHIRISH
# ═══════════════════════════════════════════════════════════════

class QuizTakeView(LoginRequiredMixin, View):
    """
    Bitta savolni ko‘rsatuvchi test jarayoni.
    Sessiyada holat saqlanadi.
    """

    def dispatch(self, request, *args, **kwargs):
        quiz = get_object_or_404(Quiz, id=kwargs['quiz_id'], is_active=True)
        user = request.user

        if user.role == 'student':
            student_profile = getattr(user, 'student_profile', None)

            if not student_profile:
                raise PermissionDenied("Talaba profili topilmadi.")

            has_individual = StudentQuizAccess.objects.filter(
                student=student_profile, quiz=quiz, is_allowed=True
            ).exists()

            has_group = GroupQuizAccess.objects.filter(
                group__in=student_profile.groups.all(),
                quiz=quiz,
                is_allowed=True,
            ).exists()

            if not (has_individual or has_group):
                return render(request, 'student/quiz/locked.html',
                              {'quiz': quiz}, status=403)

        return super().dispatch(request, *args, **kwargs)

    # ─────────── Session helpers ───────────
    def _session_key(self, quiz_id):
        return f"quiz_{quiz_id}_state"

    def _get_state(self, request, quiz_id):
        return request.session.get(
            self._session_key(quiz_id),
            {"current_index": 0, "answers": []},
        )

    def _save_state(self, request, quiz_id, state):
        request.session[self._session_key(quiz_id)] = state
        request.session.modified = True

    # ─────────── GET ───────────
    def get(self, request, quiz_id):
        quiz = get_object_or_404(Quiz, id=quiz_id, is_active=True)

        if request.GET.get("restart") == "1":
            request.session.pop(self._session_key(quiz_id), None)
            return redirect("quiz_take", quiz_id=quiz_id)

        questions = list(quiz.questions.order_by('order', 'id'))
        total_questions = len(questions)

        if total_questions == 0:
            return redirect("quiz_result", quiz_id=quiz_id)

        state = self._get_state(request, quiz_id)
        current_index = state.get("current_index", 0)

        if current_index >= total_questions:
            return redirect("quiz_result", quiz_id=quiz_id)

        question = questions[current_index]
        options = question.options.all()

        return render(request, "student/quiz/quiz.html", {
            "quiz": quiz,
            "question": question,
            "options": options,
            "current_question_num": current_index + 1,
            "total_questions": total_questions,
            "progress_percentage": int(((current_index + 1) / total_questions) * 100),
            "is_last_question": (current_index + 1 == total_questions),
        })

    # ─────────── POST ───────────
    def post(self, request, quiz_id):
        quiz = get_object_or_404(Quiz, id=quiz_id, is_active=True)
        questions = list(quiz.questions.order_by('order', 'id'))
        total_questions = len(questions)

        state = self._get_state(request, quiz_id)
        current_index = state.get("current_index", 0)

        if current_index >= total_questions:
            return redirect("quiz_result", quiz_id=quiz_id)

        question = questions[current_index]
        selected_option_id = request.POST.get("selected_option")
        selected_option = None
        is_correct = False

        if selected_option_id:
            try:
                selected_option = AnswerOption.objects.get(
                    id=selected_option_id, question=question
                )
                is_correct = selected_option.is_correct
            except AnswerOption.DoesNotExist:
                selected_option = None

        state["answers"].append({
            "question_id": question.id,
            "option_id": selected_option.id if selected_option else None,
            "is_correct": is_correct,
            "points": question.points if is_correct else 0,
        })
        state["current_index"] = current_index + 1
        self._save_state(request, quiz_id, state)

        if state["current_index"] >= total_questions:
            result = self._finalize_result(request, quiz, state)
            request.session.pop(self._session_key(quiz_id), None)
            request.session["just_awarded_coins"] = result.coins_awarded
            return redirect("quiz_result", quiz_id=quiz_id)

        return redirect("quiz_take", quiz_id=quiz_id)

    # ─────────── Natijani yakunlash ───────────
    def _get_student_profile(self, user):
        if user.role != 'student':
            raise PermissionDenied("Testni faqat talabalar topshirishi mumkin.")

        student_profile = getattr(user, 'student_profile', None)
        if not student_profile:
            raise PermissionDenied("Talaba profili topilmadi.")
        return student_profile

    @transaction.atomic
    def _finalize_result(self, request, quiz, state):
        student_profile = self._get_student_profile(request.user)

        correct_count = sum(1 for a in state["answers"] if a["is_correct"])
        total_score = sum(a["points"] for a in state["answers"])

        previous_attempt_exists = TestResult.objects.filter(
            student=student_profile, quiz=quiz
        ).exists()

        coins_awarded = 0 if previous_attempt_exists else (quiz.coins_reward or 0)

        result = TestResult.objects.create(
            student=student_profile,
            quiz=quiz,
            correct_answers=correct_count,
            total_score=total_score,
            coins_awarded=coins_awarded,
        )

        if coins_awarded:
            StudentProfile.objects.filter(pk=student_profile.pk).update(
                coins=F('coins') + coins_awarded
            )

        TestResultAnswer.objects.bulk_create([
            TestResultAnswer(
                result=result,
                question_id=a["question_id"],
                selected_option_id=a["option_id"],
                is_correct=a["is_correct"],
            )
            for a in state["answers"]
        ])

        return result


# ═══════════════════════════════════════════════════════════════
# NATIJA
# ═══════════════════════════════════════════════════════════════

class QuizResultView(LoginRequiredMixin, View):
    """Test natijasi sahifasi."""

    def get(self, request, quiz_id):
        quiz = get_object_or_404(Quiz, id=quiz_id)

        student_profile = getattr(request.user, 'student_profile', None)

        result = None
        if student_profile:
            result = (
                TestResult.objects
                .filter(student=student_profile, quiz=quiz)
                .order_by('-taken_at')
                .first()
            )

        answers = (
            result.answers.select_related("question", "selected_option")
            if result else []
        )

        pct = 0
        ring_offset = 389.6

        if result and quiz.max_score:
            pct = round((result.total_score / quiz.max_score) * 100)
            ring_offset = round(389.6 * (1 - pct / 100), 1)

        coins_awarded = request.session.pop('just_awarded_coins', None)

        return render(request, "student/quiz/result.html", {
            "quiz": quiz,
            "result": result,
            "answers": answers,
            "coins_awarded": coins_awarded,
            "pct": pct,
            "ring_offset": ring_offset,
        })


# ═══════════════════════════════════════════════════════════════
# TARIX
# ═══════════════════════════════════════════════════════════════

class QuizHistoryView(LoginRequiredMixin, View):
    """Talabaning test natijalari tarixi."""

    def get(self, request):
        student_profile = getattr(request.user, 'student_profile', None)

        results = []
        if student_profile:
            results = (
                TestResult.objects
                .filter(student=student_profile)
                .select_related('quiz')
                .order_by('-taken_at')
            )

        return render(request, "student/quiz/history.html", {"results": results})