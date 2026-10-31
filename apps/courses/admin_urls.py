# apps/courses/urls_admin.py
from django.urls import path
from . import admin_views as v

app_name = 'courses_admin'

urlpatterns = [
    # ═══ KURSLAR ═══
    path('', v.CourseListView.as_view(), name='list'),
    path('create/', v.CourseCreateView.as_view(), name='create'),
    path('<int:pk>/', v.CourseDetailView.as_view(), name='detail'),
    path('<int:pk>/edit/', v.CourseUpdateView.as_view(), name='edit'),
    path('<int:pk>/delete/', v.CourseDeleteView.as_view(), name='delete'),
    path('<int:pk>/duplicate/', v.CourseDuplicateView.as_view(), name='duplicate'),

    # ═══ OYLAR ═══
    path('month/<int:pk>/stats/',v.MonthQuickStatsView.as_view(), name='month_stats'),
    path('course/<int:course_pk>/month/create/',v.MonthCreateView.as_view(), name='month_create'),
    path('month/<int:pk>/edit/',v.MonthUpdateView.as_view(), name='month_edit'),
    path('month/<int:pk>/delete/',v.MonthDeleteView.as_view(), name='month_delete'),

    # ═══ DARSLAR ═══
    path('lessons/', v.LessonListView.as_view(), name='lesson_list'),   # ⭐ YANGI
    path('month/<int:month_pk>/lesson/create/',v.LessonCreateView.as_view(), name='lesson_create'),
    path('lesson/<int:pk>/',v.LessonDetailView.as_view(), name='lesson_detail'),
    path('lesson/<int:pk>/edit/',v.LessonUpdateView.as_view(), name='lesson_edit'),
    path('lesson/<int:pk>/delete/',v.LessonDeleteView.as_view(), name='lesson_delete'),
    path('lesson/<int:pk>/complete/',v.LessonMarkCompleteView.as_view(), name='lesson_mark_complete'),

    # ═══ HOMEWORK ═══
    # ═══ HOMEWORK ═══
    path('lesson/<int:lesson_pk>/homework/', v.HomeworkFormView.as_view(), name='homework_form'),
    path('homeworks/', v.HomeworkListView.as_view(), name='homework_list'),  # ⭐ YANGI
    # ═══ QUIZ ═══
# ═══ QUIZ BULK IMPORT ═══
    # ═══ QUIZ ═══
    path('quiz/<int:pk>/', v.QuizDetailView.as_view(), name='quiz_detail'),
    path('quiz/<int:pk>/edit/', v.QuizUpdateView.as_view(), name='quiz_edit'),
    path('quiz/<int:pk>/delete/', v.QuizDeleteView.as_view(), name='quiz_delete'),
    path('quiz/<int:pk>/toggle/', v.QuizToggleActiveView.as_view(), name='quiz_toggle'),
    path('quiz/<int:pk>/duplicate/', v.QuizDuplicateView.as_view(), name='quiz_duplicate'),
    path('quiz/<int:pk>/export/', v.QuizExportView.as_view(), name='quiz_export'),
    # ═══ QUIZ BULK IMPORT ═══
    path('quiz/<int:quiz_pk>/bulk-import/', v.QuizBulkImportView.as_view(), name='quiz_bulk_import'),    path('lesson/<int:lesson_pk>/quiz/', v.QuizFormView.as_view(), name='quiz_form'),
    path('quiz/<int:quiz_pk>/question/create/', v.QuestionCreateView.as_view(), name='question_create'),
    path('question/<int:pk>/delete/', v.QuestionDeleteView.as_view(), name='question_delete'),
    path('question/<int:question_pk>/choice/create/', v.ChoiceCreateView.as_view(), name='choice_create'),
    path('choice/<int:pk>/delete/', v.ChoiceDeleteView.as_view(), name='choice_delete'),
    # ═══ GURUHLAR ═══
    path('groups/', v.GroupListView.as_view(), name='group_list'),
    path('groups/create/', v.GroupCreateView.as_view(), name='group_create'),
    path('groups/<int:pk>/', v.GroupDetailView.as_view(), name='group_detail'),
    path('groups/<int:pk>/edit/', v.GroupUpdateView.as_view(), name='group_edit'),
    path('groups/<int:pk>/delete/', v.GroupDeleteView.as_view(), name='group_delete'),  # ⭐ YANGI
    path('groups/<int:pk>/schedule/', v.GroupScheduleUpdateView.as_view(), name='group_schedule_update'),
    path('groups/<int:pk>/generate-lessons/', v.GroupGenerateLessonsView.as_view(), name='group_generate_lessons'),
    path('groups/<int:group_pk>/lessons/<int:gl_pk>/send-homework/',
         v.GroupLessonHomeworkSendView.as_view(), name='group_lesson_send_homework'),
    path('groups/<int:pk>/add-student/', v.GroupAddStudentView.as_view(), name='group_add_student'),
    path('groups/<int:pk>/remove-student/<int:student_id>/', v.GroupRemoveStudentView.as_view(),
         name='group_remove_student'),
    # ═══ BULK ═══
    path('bulk/', v.CoursesBulkView.as_view(), name='bulk'),   # ⭐ MUHIM
    path('<int:pk>/toggle-publish/',v.CourseTogglePublishView.as_view(), name='toggle_publish'),
    path('scheduled-homework/',v.ScheduledHomeworkListView.as_view(),name='scheduled_homework'),

]