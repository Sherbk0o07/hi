"""
LearnCraft — URL Configuration
================================
Auth, dashboard, quiz, admin bo'limlari.

Barcha eski AdminSectionView URL lar → yangi kurslar paneliga yo'naltiriladi.
"""
from django.urls import path
from django.contrib.auth import views as auth_views
from django.views.generic import RedirectView

# ═══════════════════════════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════════════════════════
from apps.pages.views.auth import (
    LoginPageView,
    LoginOTPView,
    VerifyOTPView,
    LogoutView,
    TelegramSendCodeView,
    TelegramVerifyCodeView,
)

# ═══════════════════════════════════════════════════════════════
# HOME / DASHBOARDS
# ═══════════════════════════════════════════════════════════════
from apps.pages.views.home import (
    HomePageView,
    ParentDashboardView,
    ParentQuestionView,
    AdminDashboardView,
)

# ═══════════════════════════════════════════════════════════════
# QUIZ
# ═══════════════════════════════════════════════════════════════
from apps.pages.views.quiz import (
    QuizListView,
    QuizTakeView,
    QuizResultView,
    QuizHistoryView,
)

# ═══════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ═══════════════════════════════════════════════════════════════
from apps.pages.views.notifications import (
    AdminNotificationsView,
    AdminNotificationCreateView,
    AdminNotificationDetailView,
    AdminNotificationActionView,
    AdminSMSLogsView,
)

# ═══════════════════════════════════════════════════════════════
# STUDENTS / PARENTS
# ═══════════════════════════════════════════════════════════════
from apps.pages.views.students import (
    AdminStudentsView,
    AdminStudentDetailView,
    AdminStudentActionView,
    AdminStudentCreateView,
    AdminParentsView,
    AdminParentCreateView,
    AdminParentDetailView,
    AdminParentEditView,
    admin_send_sms,
)


# ═══════════════════════════════════════════════════════════════
# YORDAMCHI FUNKSIYA — NOMLANGAN URL GA REDIRECT
# ═══════════════════════════════════════════════════════════════
def _r(pattern_name):
    """
    Nomlangan URL ga 302 redirect qaytaradi.
    pattern_name dinamik hal qilinadi — circular import xavfi yo'q.
    Query string saqlanadi (filtrlar uchun).
    """
    return RedirectView.as_view(
        pattern_name=pattern_name,
        permanent=False,
        query_string=True,
    )


# ═══════════════════════════════════════════════════════════════
# URL PATTERNS
# ═══════════════════════════════════════════════════════════════

urlpatterns = [

    # ───────────────────────────────────────────────────────────
    # 1. AUTENTIFIKATSIYA
    # ───────────────────────────────────────────────────────────
    path('login/',         LoginPageView.as_view(),  name='login_page_view'),
    path('login/otp/',     LoginOTPView.as_view(),   name='login_otp'),
    path('login/verify/',  VerifyOTPView.as_view(),  name='login_otp_verify'),
    path('logout/',        LogoutView.as_view(),     name='logout'),
    path('login/telegram/send/',   TelegramSendCodeView.as_view(),   name='login_telegram_send'),
    path('login/telegram/verify/', TelegramVerifyCodeView.as_view(), name='login_telegram_verify'),

    # ───────────────────────────────────────────────────────────
    # 1.1. PAROLNI TIKLASH
    # ───────────────────────────────────────────────────────────
    path(
        'parolni-tiklash/',
        auth_views.PasswordResetView.as_view(
            template_name='auth/password_reset_form.html',
            email_template_name='auth/password_reset_email.html',
            subject_template_name='auth/password_reset_subject.txt',
            success_url='/parolni-tiklash/yuborildi/',
        ),
        name='password_reset',
    ),
    path(
        'parolni-tiklash/yuborildi/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='auth/password_reset_done.html',
        ),
        name='password_reset_done',
    ),
    path(
        'parolni-tiklash/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='auth/password_reset_confirm.html',
            success_url='/parolni-tiklash/yakunlandi/',
        ),
        name='password_reset_confirm',
    ),
    path(
        'parolni-tiklash/yakunlandi/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='auth/password_reset_complete.html',
        ),
        name='password_reset_complete',
    ),

    # ───────────────────────────────────────────────────────────
    # 2. ASOSIY SAHIFALAR
    # ───────────────────────────────────────────────────────────
    path('', HomePageView.as_view(), name='home_page_view'),

    # Ota-ona
    path('parent/dashboard/',   ParentDashboardView.as_view(), name='parent_dashboard'),
    path('parent/savol-javob/', ParentQuestionView.as_view(),  name='parent_questions'),

    # ═══════════════════════════════════════════════════════════
    # ⚠️ ADMIN DASHBOARD — HAQIQIY VIEW
    # ═══════════════════════════════════════════════════════════
    path('boshqaruv/', AdminDashboardView.as_view(), name='admin_dashboard'),

    # ───────────────────────────────────────────────────────────
    # 3. QUIZ (TALABALAR UCHUN)
    # ───────────────────────────────────────────────────────────
    path('testlar/',                      QuizListView.as_view(),   name='quiz_list'),
    path('testlar/tarix/',                QuizHistoryView.as_view(), name='quiz_history'),
    path('testlar/<int:quiz_id>/',        QuizTakeView.as_view(),   name='quiz_take'),
    path('testlar/<int:quiz_id>/natija/', QuizResultView.as_view(), name='quiz_result'),

    # ───────────────────────────────────────────────────────────
    # 4. ADMIN — O'QUVCHILAR (REAL VIEW)
    # ───────────────────────────────────────────────────────────
    path('admin/oquvchilar/',               AdminStudentsView.as_view(),       name='admin_students'),
    path('admin/oquvchilar/yangi/',         AdminStudentCreateView.as_view(),  name='admin_student_create'),
    path('admin/oquvchilar/<int:pk>/',      AdminStudentDetailView.as_view(),  name='admin_student_detail'),
    path('admin/oquvchilar/<int:pk>/amal/', AdminStudentActionView.as_view(),  name='admin_student_action'),

    # ───────────────────────────────────────────────────────────
    # 5. ADMIN — OTA-ONALAR (REAL VIEW)
    # ───────────────────────────────────────────────────────────
    path('admin/ota-onalar/',                     AdminParentsView.as_view(),       name='admin_parents'),
    path('admin/ota-onalar/yangi/',               AdminParentCreateView.as_view(),  name='admin_parent_create'),
    path('admin/ota-onalar/<int:pk>/',            AdminParentDetailView.as_view(),  name='admin_parent_detail'),
    path('admin/ota-onalar/<int:pk>/tahrirlash/', AdminParentEditView.as_view(),    name='admin_parent_edit'),

    # SMS yuborish (AJAX)
    path('admin/sms-yuborish/', admin_send_sms, name='admin_send_sms'),

    # ───────────────────────────────────────────────────────────
    # 6. ADMIN — BILDIRISHNOMALAR VA SMS (REAL VIEW)
    # ───────────────────────────────────────────────────────────
    path('admin/bildirishnomalar/',               AdminNotificationsView.as_view(),      name='admin_notifications'),
    path('admin/bildirishnomalar/yangi/',         AdminNotificationCreateView.as_view(), name='admin_notification_create'),
    path('admin/bildirishnomalar/<int:pk>/',      AdminNotificationDetailView.as_view(), name='admin_notification_detail'),
    path('admin/bildirishnomalar/<int:pk>/amal/', AdminNotificationActionView.as_view(), name='admin_notification_action'),
    path('admin/sms-tarixi/',                     AdminSMSLogsView.as_view(),            name='admin_sms_history'),

    # ═══════════════════════════════════════════════════════════
    # 7. ESKI BO'LIMLAR → YANGI KURSLAR PANELIGA YO'NALTIRISH
    # ═══════════════════════════════════════════════════════════

    # ─── O'QUV JARAYONI ───
    path('admin/kurslar/',      _r('courses_admin:list'),        name='admin_courses'),
    path('admin/darslar/',      _r('courses_admin:list'),        name='admin_lessons'),
    path('admin/topshiriqlar/', _r('courses_admin:list'),        name='admin_tasks'),
    path('admin/quizzes/',      _r('courses_admin:list'),        name='admin_quizzes'),
    path('admin/guruhlar/',     _r('courses_admin:group_list'),  name='admin_groups'),
    path('admin/kalendar/',     _r('admin_dashboard'),           name='admin_calendar'),
    path('admin/kod/',          _r('admin_dashboard'),           name='admin_code_editor'),

    # ─── FOYDALANUVCHILAR ───
    path('admin/oqituvchilar/', _r('admin_dashboard'),           name='admin_teachers'),
    path('admin/managerlar/',   _r('admin_dashboard'),           name='admin_managers'),

    # ─── RIVOJLANISH ───
    path('admin/baholar/',       _r('admin_dashboard'),          name='admin_grades'),
    path('admin/davomat/',       _r('admin_dashboard'),          name='admin_attendance'),
    path('admin/statistika/',    _r('courses_admin:list'),       name='admin_statistics'),
    path('admin/streak/',        _r('admin_dashboard'),          name='admin_streaks'),
    path('admin/ligalar/',       _r('admin_dashboard'),          name='admin_leagues'),
    path('admin/yutuqlar/',      _r('admin_dashboard'),          name='admin_achievements'),
    path('admin/daraja/',        _r('admin_dashboard'),          name='admin_levels'),
    path('admin/sertifikatlar/', _r('admin_dashboard'),          name='admin_certificates'),

    # ─── MULOQOT ───
    path('admin/guruh-chati/',   _r('courses_admin:group_list'), name='admin_group_chat'),
    path('admin/ommaviy-chat/',  _r('admin_dashboard'),          name='admin_public_chat'),
    path('admin/mentor-chat/',   _r('admin_dashboard'),          name='admin_mentor_chat'),
    path('admin/sorovnomalar/',  _r('admin_dashboard'),          name='admin_surveys'),
    path('admin/reyting/',       _r('admin_dashboard'),          name='admin_ranking'),

    # ─── DO'KON VA IQTISOD ───
    path('admin/dokon/',          _r('admin_dashboard'),         name='admin_shop'),
    path('admin/ayriboshlash/',   _r('admin_dashboard'),         name='admin_exchange'),
    path('admin/inventar/',       _r('admin_dashboard'),         name='admin_inventory'),
    path('admin/bozor/',          _r('admin_dashboard'),         name='admin_market'),
    path('admin/omad-gildiragi/', _r('admin_dashboard'),         name='admin_lucky_wheel'),

    # ─── SO'ROVLAR VA TIZIM ───
    path('admin/ota-ona-sorovlari/', _r('admin_dashboard'),      name='admin_parent_requests'),
    path('admin/menyular/',          _r('admin_dashboard'),      name='admin_menu_sections'),
    path('admin/sozlamalar/',        _r('admin_dashboard'),      name='admin_settings'),
]