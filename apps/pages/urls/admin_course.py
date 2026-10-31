"""
apps/courses/urls.py
================================================
DIGION LMS — Kurslar uchun URL lar.
"""

from django.urls import path
import apps.pages.views.home as views


app_name = 'courses'


urlpatterns = [
    # ═══════════════════════════════════════════════════════════
    # PUBLIC — Ochiq sahifalar
    # ═══════════════════════════════════════════════════════════
    path(
        'kurs/<slug:slug>/oldindan-korish/',
        views.CoursePreviewView.as_view(),
        name='course_preview'
    ),
    path(
        'sertifikat/tekshirish/<str:code>/',
        views.CertificateVerifyView.as_view(),
        name='certificate_verify'
    ),

    # ═══════════════════════════════════════════════════════════
    # ADMIN — KURSLAR
    # ═══════════════════════════════════════════════════════════
    path(
        'boshqaruv/kurslar/',
        views.AdminCourseListView.as_view(),
        name='admin_course_list'
    ),
    path(
        'boshqaruv/kurslar/yangi/',
        views.AdminCourseCreateView.as_view(),
        name='admin_course_create'
    ),
    path(
        'boshqaruv/kurslar/<int:pk>/',
        views.AdminCourseDetailView.as_view(),
        name='admin_course_detail'
    ),
    path(
        'boshqaruv/kurslar/<int:pk>/tahrirlash/',
        views.AdminCourseEditView.as_view(),
        name='admin_course_edit'
    ),
    path(
        'boshqaruv/kurslar/<int:pk>/ochirish/',
        views.AdminCourseDeleteView.as_view(),
        name='admin_course_delete'
    ),

    # ═══════════════════════════════════════════════════════════
    # ADMIN — OYLAR
    # ═══════════════════════════════════════════════════════════
    path(
        'boshqaruv/kurslar/<int:course_id>/oylar/yangi/',
        views.AdminCourseMonthCreateView.as_view(),
        name='admin_month_create'
    ),

    # ═══════════════════════════════════════════════════════════
    # ADMIN — DARSLAR
    # ═══════════════════════════════════════════════════════════
    path(
        'boshqaruv/kurslar/<int:course_id>/darslar/yangi/',
        views.AdminLessonCreateView.as_view(),
        name='admin_lesson_create'
    ),
    path(
        'boshqaruv/darslar/<int:pk>/',
        views.AdminLessonDetailView.as_view(),
        name='admin_lesson_detail'
    ),
    path(
        'boshqaruv/darslar/<int:topic_id>/tasdiqlash/',
        views.LessonDayApprovalView.as_view(),
        name='lesson_approve'
    ),

    # ═══════════════════════════════════════════════════════════
    # ADMIN — UYGA VAZIFALAR
    # ═══════════════════════════════════════════════════════════
    path(
        'boshqaruv/uyga-vazifalar/',
        views.AdminHomeworkListView.as_view(),
        name='admin_homework_list'
    ),
    path(
        'boshqaruv/uyga-vazifalar/<int:pk>/',
        views.AdminHomeworkDetailView.as_view(),
        name='admin_homework_detail'
    ),
    path(
        'boshqaruv/darslar/<int:lesson_id>/uyga-vazifa/',
        views.AdminHomeworkCreateView.as_view(),
        name='admin_homework_create'
    ),
    path(
        'boshqaruv/uyga-vazifalar/<int:pk>/tasdiqlash/',
        views.AdminHomeworkApproveView.as_view(),
        name='admin_homework_approve'
    ),
    path(
        'boshqaruv/uyga-vazifalar/<int:pk>/yuborish/',
        views.AdminHomeworkSendView.as_view(),
        name='admin_homework_send'
    ),

    # ═══════════════════════════════════════════════════════════
    # ADMIN — TOPSHIRIQLAR
    # ═══════════════════════════════════════════════════════════
    path(
        'boshqaruv/topshiriqlar/',
        views.AdminSubmissionListView.as_view(),
        name='admin_submission_list'
    ),
    path(
        'boshqaruv/topshiriqlar/<int:pk>/baholash/',
        views.AdminSubmissionGradeView.as_view(),
        name='admin_submission_grade'
    ),

    # ═══════════════════════════════════════════════════════════
    # ADMIN — GURUHLAR
    # ═══════════════════════════════════════════════════════════
    path(
        'boshqaruv/guruhlar/',
        views.AdminGroupListView.as_view(),
        name='admin_group_list'
    ),
    path(
        'boshqaruv/guruhlar/yangi/',
        views.AdminGroupCreateView.as_view(),
        name='admin_group_create'
    ),
    path(
        'boshqaruv/guruhlar/<int:pk>/',
        views.AdminGroupDetailView.as_view(),
        name='admin_group_detail'
    ),
    path(
        'boshqaruv/guruhlar/<int:pk>/talaba-qoshish/',
        views.AdminGroupAddStudentView.as_view(),
        name='admin_group_add_student'
    ),
    path(
        'boshqaruv/guruhlar/<int:pk>/talaba-ochirish/<int:student_id>/',
        views.AdminGroupRemoveStudentView.as_view(),
        name='admin_group_remove_student'
    ),

    # ═══════════════════════════════════════════════════════════
    # ADMIN — STATISTIKA
    # ═══════════════════════════════════════════════════════════
    path(
        'boshqaruv/statistika/',
        views.AdminCoursesStatisticsView.as_view(),
        name='admin_courses_statistics'
    ),

    # ═══════════════════════════════════════════════════════════
    # TALABA — KURSLAR
    # ═══════════════════════════════════════════════════════════
    path(
        'talaba/kurslar/',
        views.StudentCourseListView.as_view(),
        name='student_course_list'
    ),
    path(
        'talaba/kurslar/<int:pk>/',
        views.StudentCourseDetailView.as_view(),
        name='student_course_detail'
    ),
    path(
        'talaba/darslar/<int:pk>/',
        views.StudentLessonView.as_view(),
        name='student_lesson'
    ),

    # ═══════════════════════════════════════════════════════════
    # TALABA — UYGA VAZIFALAR
    # ═══════════════════════════════════════════════════════════
    path(
        'talaba/uyga-vazifalar/',
        views.StudentHomeworkListView.as_view(),
        name='student_homework_list'
    ),
    path(
        'talaba/uyga-vazifalar/<int:homework_id>/',
        views.StudentHomeworkDetailView.as_view(),
        name='student_homework_detail'
    ),

    # ═══════════════════════════════════════════════════════════
    # TALABA — TESTLAR
    # ═══════════════════════════════════════════════════════════
    path(
        'talaba/testlar/<int:quiz_id>/boshlash/',
        views.StudentQuizStartView.as_view(),
        name='student_quiz_start'
    ),
    path(
        'talaba/testlar/topshirish/<int:attempt_id>/',
        views.StudentQuizTakeView.as_view(),
        name='student_quiz_take'
    ),
    path(
        'talaba/testlar/natija/<int:attempt_id>/',
        views.StudentQuizResultView.as_view(),
        name='student_quiz_result'
    ),

    # ═══════════════════════════════════════════════════════════
    # AJAX — API endpoints
    # ═══════════════════════════════════════════════════════════
    path(
        'api/kurs-qidirish/',
        views.AjaxCourseSearchView.as_view(),
        name='ajax_course_search'
    ),
    path(
        'api/talaba-qidirish/',
        views.AjaxStudentSearchView.as_view(),
        name='ajax_student_search'
    ),
    path(
        'api/guruh/<int:pk>/statistika/',
        views.AjaxGroupStatsView.as_view(),
        name='ajax_group_stats'
    ),
    path(
        'api/uyga-vazifa/<int:pk>/statistika/',
        views.AjaxHomeworkStatsView.as_view(),
        name='ajax_homework_stats'
    ),
    path(
        'api/dars/<int:lesson_id>/davomat/',
        views.AjaxMarkAttendanceView.as_view(),
        name='ajax_mark_attendance'
    ),

    # ═══════════════════════════════════════════════════════════
    # EXPORT — CSV yuklab olish
    # ═══════════════════════════════════════════════════════════
    path(
        'export/kurslar/csv/',
        views.AdminExportCourseCSVView.as_view(),
        name='export_courses_csv'
    ),
    path(
        'export/talabalar/csv/',
        views.AdminExportStudentsCSVView.as_view(),
        name='export_students_csv'
    ),
    path(
        'export/guruh/<int:group_id>/talabalar/csv/',
        views.AdminExportStudentsCSVView.as_view(),
        name='export_group_students_csv'
    ),
    path(
        'export/sertifikatlar/csv/',
        views.AdminExportCertificatesCSVView.as_view(),
        name='export_certificates_csv'
    ),
]