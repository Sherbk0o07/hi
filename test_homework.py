# ═══════════════════════════════════════════════════════════════
# 🧪 AUTO-HOMEWORK-SENDING SYSTEM — TO'LIQ TEST
# ═══════════════════════════════════════════════════════════════
import os
import sys
from datetime import timedelta, datetime

from django.conf import settings
from django.utils import timezone
from django.db.models import Count


# Rangli chiqish uchun
class C:
    OK = '\033[92m'
    FAIL = '\033[91m'
    WARN = '\033[93m'
    INFO = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'


def ok(msg):   print(f"{C.OK}✅ {msg}{C.END}")


def fail(msg): print(f"{C.FAIL}❌ {msg}{C.END}")


def warn(msg): print(f"{C.WARN}⚠️  {msg}{C.END}")


def info(msg): print(f"{C.INFO}ℹ️  {msg}{C.END}")


def head(msg): print(f"\n{C.BOLD}{'═' * 60}\n{msg}\n{'═' * 60}{C.END}")


# ═══════════════════════════════════════════════════════════════
# 1. IMPORTLARNI TEKSHIRISH
# ═══════════════════════════════════════════════════════════════
head("1️⃣  IMPORTLARNI TEKSHIRISH")

try:
    from apps.courses.models import (
        Course, CourseMonth, Lesson, GroupLesson,
        Homework, HomeworkDeliveryLog, StudentGroup,
    )

    ok("Models import")
except Exception as e:
    fail(f"Models import: {e}")

try:
    from apps.courses.services.homework_scheduler import HomeworkScheduler

    ok("HomeworkScheduler import")
except Exception as e:
    fail(f"HomeworkScheduler: {e}")

try:
    from apps.courses.services.homework_sender import HomeworkSender

    ok("HomeworkSender import")
except Exception as e:
    fail(f"HomeworkSender: {e}")

try:
    from apps.courses import signals

    ok("Signals import")
    # Receiver tekshirish
    assert hasattr(signals, 'cancel_on_delete'), "cancel_on_delete yo'q"
    assert hasattr(signals, 'schedule_homework_on_create'), "schedule_homework_on_create yo'q"
    ok("Signals receiverlar mavjud")
except Exception as e:
    fail(f"Signals: {e}")

try:
    from apps.courses.tasks import send_homework_to_group_task

    ok("Celery task import")
except Exception as e:
    fail(f"Celery task: {e}")

try:
    from apps.user.models import (
        CustomUser, StudentProfile, TelegramLink,
    )

    ok("User models import")
except Exception as e:
    fail(f"User models: {e}")

# ═══════════════════════════════════════════════════════════════
# 2. MODEL MAYDONLARINI TEKSHIRISH
# ═══════════════════════════════════════════════════════════════
head("2️⃣  MODEL MAYDONLARINI TEKSHIRISH")

required_fields = {
    'scheduled_task_id': None,
    'homework_sent_at': None,
    'homework_status': None,
    'homework_recipients_count': None,
    'homework_failed_count': None,
}
missing = []
for field in required_fields:
    if hasattr(GroupLesson, field):
        ok(f"GroupLesson.{field}")
    else:
        fail(f"GroupLesson.{field} — MAVJUD EMAS!")
        missing.append(field)

if missing:
    warn(f"Migratsiya qilinmagan: {missing}")
    warn("→ python manage.py makemigrations courses && python manage.py migrate")

# HomeworkDeliveryLog modeli
try:
    from apps.courses.models import HomeworkDeliveryLog as HDL

    ok("HomeworkDeliveryLog modeli mavjud")
    for f in ['group_lesson', 'homework', 'student', 'status', 'sent_at', 'read_at']:
        if hasattr(HDL, f):
            ok(f"  HomeworkDeliveryLog.{f}")
        else:
            fail(f"  HomeworkDeliveryLog.{f} — YO'Q!")
except Exception as e:
    fail(f"HomeworkDeliveryLog: {e}")

# ═══════════════════════════════════════════════════════════════
# 3. SETTINGS TEKSHIRISH
# ═══════════════════════════════════════════════════════════════
head("3️⃣  SETTINGS TEKSHIRISH")

checks = {
    'TELEGRAM_BOT_TOKEN': getattr(settings, 'TELEGRAM_BOT_TOKEN', None),
    'ADMIN_TELEGRAM_CHAT_ID': getattr(settings, 'ADMIN_TELEGRAM_CHAT_ID', None),
    'SITE_URL': getattr(settings, 'SITE_URL', None),
    'CELERY_BROKER_URL': getattr(settings, 'CELERY_BROKER_URL', None),
    'HOMEWORK_GRACE_MINUTES': getattr(settings, 'HOMEWORK_GRACE_MINUTES', None),
}

for key, val in checks.items():
    if val:
        preview = str(val)[:25] + ('…' if len(str(val)) > 25 else '')
        ok(f"{key} = {preview}")
    else:
        warn(f"{key} — sozlanmagan!")

# ═══════════════════════════════════════════════════════════════
# 4. CELERY ULANISHINI TEKSHIRISH
# ═══════════════════════════════════════════════════════════════
head("4️⃣  CELERY ULANISHINI TEKSHIRISH")

try:
    from config.celery import app as celery_app

    ok("Celery app import")

    # Broker'ga ulanish
    try:
        inspect = celery_app.control.inspect(timeout=2)
        stats = inspect.stats()
        if stats:
            workers = list(stats.keys())
            ok(f"Faol workerlar: {workers}")
        else:
            warn("Worker topilmadi — celery worker ishga tushiring!")
            warn("→ celery -A config worker -l info")
    except Exception as e:
        warn(f"Broker javob bermadi: {e}")
except ImportError:
    try:
        from celery import current_app as celery_app

        ok("Celery app import (default)")
    except Exception as e:
        fail(f"Celery: {e}")

# ═══════════════════════════════════════════════════════════════
# 5. MAVJUD MA'LUMOTLARNI KO'RISH
# ═══════════════════════════════════════════════════════════════
head("5️⃣  MAVJUD MA'LUMOTLAR")

print(f"📚 Kurslar: {Course.objects.filter(is_deleted=False).count()}")
print(f"📝 Darslar: {Lesson.objects.filter(is_deleted=False).count()}")
print(f"📌 Uyga vazifalar: {Homework.objects.filter(is_deleted=False).count()}")
print(f"👥 Guruhlar: {StudentGroup.objects.filter(is_deleted=False).count()}")
print(f"🎯 GroupLesson (jami): {GroupLesson.objects.count()}")
print(f"⏰ Rejalashtirilgan: {GroupLesson.objects.filter(homework_status='scheduled').count()}")
print(f"✅ Yuborilgan: {GroupLesson.objects.filter(homework_status='sent').count()}")
print(f"❌ Xato: {GroupLesson.objects.filter(homework_status='failed').count()}")
print(f"📊 Delivery logs: {HomeworkDeliveryLog.objects.count()}")

# ═══════════════════════════════════════════════════════════════
# 6. TEST DATA YARATISH (agar yo'q bo'lsa)
# ═══════════════════════════════════════════════════════════════
head("6️⃣  TEST DATA YARATISH")

create_test = input(f"\n{C.WARN}Test ma'lumot yaratsinmi? (ha/yo'q): {C.END}").strip().lower()

if create_test in ('ha', 'h', 'yes', 'y'):

    # 6.1. Teacher
    teacher, _ = CustomUser.objects.get_or_create(
        phone_number='+998900000001',
        defaults={
            'first_name': 'Test',
            'last_name': 'Teacher',
            'role': 'teacher',
            'is_active': True,
        }
    )
    ok(f"Teacher: {teacher}")

    # 6.2. Admin
    admin = CustomUser.objects.filter(role='admin', is_active=True).first()
    if admin:
        ok(f"Admin: {admin}")
    else:
        warn("Admin topilmadi — ba'zi testlar o'tkazib yuboriladi")

    # 6.3. Course
    course, _ = Course.objects.get_or_create(
        title='[TEST] Python asoslari',
        defaults={
            'short_description': 'Test kursi',
            'duration_months': 1,
            'status': 'published',
            'is_active': True,
            'teacher': teacher,
            'created_by': admin or teacher,
        }
    )
    ok(f"Course: {course.title} (pk={course.pk})")

    # 6.4. Month
    month, _ = CourseMonth.objects.get_or_create(
        course=course,
        month_number=1,
        defaults={'title': '1-oy', 'description': 'Test oyi'},
    )
    ok(f"Month: {month}")

    # 6.5. Lesson
    lesson, _ = Lesson.objects.get_or_create(
        course=course,
        lesson_number=1,
        defaults={
            'title': 'String methods',
            'short_description': 'Test dars',
            'lesson_type': 'theory',
            'status': 'planned',
            'month': month,
        }
    )
    ok(f"Lesson: {lesson}")

    # 6.6. Homework
    homework, _ = Homework.objects.get_or_create(
        lesson=lesson,
        defaults={
            'title': '5 ta masala',
            'description': 'String methods bo\'yicha 5 ta masala',
            'homework_type': 'coding',
            'deadline_days': 3,
            'max_score': 100,
            'is_approved': True,  # ⭐ MUHIM
            'created_by': admin or teacher,
        }
    )
    # Agar mavjud bo'lsa ham approved qilish
    if not homework.is_approved:
        homework.is_approved = True
        homework.save()
    ok(f"Homework: {homework.title} (approved={homework.is_approved})")

    # 6.7. Student
    student_user, _ = CustomUser.objects.get_or_create(
        phone_number='+998900000002',
        defaults={
            'first_name': 'Test',
            'last_name': 'Student',
            'role': 'student',
            'is_active': True,
        }
    )
    student, _ = StudentProfile.objects.get_or_create(
        user=student_user,
        defaults={},
    )
    ok(f"Student: {student.user.get_full_name()}")

    # 6.8. TelegramLink
    link, _ = TelegramLink.objects.get_or_create(
        user=student_user,
        defaults={
            'chat_id': 123456789,  # Test chat_id
            'is_active': True,
        }
    )
    ok(f"TelegramLink: chat_id={link.chat_id}, active={link.is_active}")

    # 6.9. Group
    today = timezone.now().date()
    group, created = StudentGroup.objects.get_or_create(
        name='[TEST] B6',
        defaults={
            'course': course,
            'teacher': teacher,
            'schedule_type': 'odd',
            'schedule': {
                'monday': '16:00',
                'wednesday': '16:00',
                'friday': '16:00',
            },
            'max_students': 20,
            'status': 'active',
            'start_date': today,
            'lessons_start_date': today,
        }
    )
    ok(f"Group: {group.name} (created={created})")

    # Studentni guruhga qo'shish
    group.students.add(student)
    ok(f"Student guruhga qo'shildi. Jami: {group.students_count}")

    # ═══ MUHIM: GroupLesson ni QO'LDA yaratish (signal ishlamasligi mumkin) ═══
    gl, gl_created = GroupLesson.objects.get_or_create(
        group=group,
        lesson=lesson,
        defaults={
            'lesson_date': today,
            'order_in_group': 1,
        }
    )
    ok(f"GroupLesson: {gl} (created={gl_created}, status={gl.homework_status})")

    print(f"\n{C.OK}{'─' * 60}{C.END}")
    print(f"{C.BOLD}📋 TEST DATA TAYYOR:{C.END}")
    print(f"  Group PK: {group.pk}")
    print(f"  GroupLesson PK: {gl.pk}")
    print(f"  Homework PK: {homework.pk}")
    print(f"{C.OK}{'─' * 60}{C.END}")

else:
    info("Test data o'tkazib yuborildi")
    # Mavjud GroupLesson'ni olish
    gl = GroupLesson.objects.filter(homework_status='scheduled').first()
    if not gl:
        gl = GroupLesson.objects.first()

# ═══════════════════════════════════════════════════════════════
# 7. ETA HISOBLASHNI TEKSHIRISH
# ═══════════════════════════════════════════════════════════════
head("7️⃣  ETA HISOBLASH")

if gl:
    print(f"GroupLesson: GL#{gl.pk} ({gl.group.name})")
    print(f"  lesson_date: {gl.lesson_date}")
    print(f"  schedule: {gl.group.schedule}")

    day_name = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'][gl.lesson_date.weekday()]
    print(f"  Kun: {day_name}")

    try:
        eta = HomeworkScheduler.calculate_eta(gl)
        if eta:
            ok(f"ETA: {eta}")
            now = timezone.now()
            if eta > now:
                diff = eta - now
                info(f"Yuborilishiga: {diff}")
            else:
                warn(f"ETA o'tib ketgan (hozir {now})")
        else:
            fail("ETA hisoblanmadi — schedule'da bu kun yo'q!")
    except Exception as e:
        fail(f"calculate_eta xatosi: {e}")
else:
    warn("GroupLesson yo'q — 6-qadamni bajaring")

# ═══════════════════════════════════════════════════════════════
# 8. TASKNI QO'LDA REJALASHTIRISH
# ═══════════════════════════════════════════════════════════════
head("8️⃣  TASKNI REJALASHTIRISH")

if gl:
    answer = input(f"{C.WARN}Taskni rejalashtirsinmi (Celery'ga)? (ha/yo'q): {C.END}").strip().lower()
    if answer in ('ha', 'h', 'yes', 'y'):
        try:
            # Eski taskni bekor qilish
            if gl.scheduled_task_id:
                HomeworkScheduler.cancel_scheduled(gl)
                info(f"Eski task bekor qilindi: {gl.scheduled_task_id}")

            result = HomeworkScheduler.schedule_homework(gl, force=True)

            if result.get('scheduled'):
                ok(f"Task rejalashtirildi!")
                print(f"   ETA: {result['eta']}")
                print(f"   Task ID: {result['task_id']}")

                gl.refresh_from_db()
                print(f"   homework_status: {gl.homework_status}")
                print(f"   scheduled_task_id: {gl.scheduled_task_id}")
            else:
                fail(f"Rejalashtirilmadi: {result.get('reason')}")
        except Exception as e:
            import traceback

            traceback.print_exc()
            fail(f"Schedule xatosi: {e}")
    else:
        info("O'tkazib yuborildi")

# ═══════════════════════════════════════════════════════════════
# 9. TASKNI DARHOL ISHGA TUSHIRISH (SINOV)
# ═══════════════════════════════════════════════════════════════
head("9️⃣  TASKNI DARHOL BAJARISH")

if gl:
    answer = input(f"{C.WARN}Taskni DARHOL bajarsinmi (Telegram yuboradi)? (ha/yo'q): {C.END}").strip().lower()
    if answer in ('ha', 'h', 'yes', 'y'):
        try:
            from apps.courses.tasks import send_homework_to_group_task

            info(f"Task bajarilmoqda: GL#{gl.pk}")
            result = send_homework_to_group_task(gl.pk)

            print(f"\n{C.BOLD}Natija:{C.END}")
            for k, v in result.items():
                if k == 'details':
                    print(f"  details:")
                    for d in v:
                        icon = {'sent': '✅', 'failed': '❌', 'skipped': '⏭'}.get(d['status'], '❓')
                        print(f"    {icon} {d['name']} — {d['status']}")
                        if d.get('error'):
                            print(f"        └─ {d['error'][:60]}")
                else:
                    print(f"  {k}: {v}")

            gl.refresh_from_db()
            print(f"\n{C.BOLD}GroupLesson yangilangan:{C.END}")
            print(f"  homework_status: {gl.homework_status}")
            print(f"  homework_sent_at: {gl.homework_sent_at}")
            print(f"  sent: {gl.homework_recipients_count}")
            print(f"  failed: {gl.homework_failed_count}")

            if result.get('ok'):
                ok("Task muvaffaqiyatli bajarildi!")
            else:
                warn(f"Task bajarildi, lekin holat: {result.get('reason')}")
        except Exception as e:
            import traceback

            traceback.print_exc()
            fail(f"Task xatosi: {e}")
    else:
        info("O'tkazib yuborildi")

# ═══════════════════════════════════════════════════════════════
# 10. DELIVERY LOG'LARNI KO'RISH
# ═══════════════════════════════════════════════════════════════
head("🔟  DELIVERY LOG'LAR")

if gl:
    logs = HomeworkDeliveryLog.objects.filter(group_lesson=gl)
    print(f"GL#{gl.pk} uchun loglar: {logs.count()}")
    for log in logs:
        icon = {'sent': '✅', 'failed': '❌', 'skipped': '⏭', 'read': '👀'}.get(log.status, '❓')
        print(f"  {icon} {log.student.user.get_full_name()} — {log.status}")
        if log.error:
            print(f"      └─ {log.error}")
        print(f"      sent_at: {log.sent_at}")

# ═══════════════════════════════════════════════════════════════
# 11. TELEGRAM API TEKSHIRISH
# ═══════════════════════════════════════════════════════════════
head("1️⃣1️⃣  TELEGRAM API ULANISH")

try:
    from apps.service.telegram_bot import get_bot

    bot = get_bot()
    me = bot.get_me()
    ok(f"Bot: @{me.username} (ID: {me.id})")
    info(f"Bot nomi: {me.first_name}")
except Exception as e:
    fail(f"Telegram xatosi: {e}")
    warn("TELEGRAM_BOT_TOKEN ni tekshiring!")

# ═══════════════════════════════════════════════════════════════
# 12. YAKUNIY STATISTIKA
# ═══════════════════════════════════════════════════════════════
head("1️⃣2️⃣  YAKUNIY STATISTIKA")

statuses = GroupLesson.objects.values('homework_status').annotate(c=Count('id'))
print(f"\n{C.BOLD}GroupLesson holatlari:{C.END}")
for s in statuses:
    icon = {
        'scheduled': '⏰', 'sending': '📤', 'sent': '✅',
        'failed': '❌', 'partial': '⚠️', 'cancelled': '🚫', 'pending': '⏳',
    }.get(s['homework_status'], '❓')
    print(f"  {icon} {s['homework_status']}: {s['c']}")

print(f"\n{C.BOLD}Delivery log holatlari:{C.END}")
logs_statuses = HomeworkDeliveryLog.objects.values('status').annotate(c=Count('id'))
for s in logs_statuses:
    icon = {'sent': '✅', 'failed': '❌', 'skipped': '⏭', 'read': '👀', 'pending': '⏳'}.get(s['status'], '❓')
    print(f"  {icon} {s['status']}: {s['c']}")

# ═══════════════════════════════════════════════════════════════
# YAKUN
# ═══════════════════════════════════════════════════════════════
head("🎉 TEST YAKUNLANDI")
print(f"""
{C.BOLD}Keyingi qadamlar:{C.END}
  1. Celery worker ishga tushiring:
     $ celery -A config worker -l info

  2. Admin panelda tekshiring:
     /admin/courses/scheduled-homework/

  3. Telegram botni tekshiring:
     /start — bot javob beryaptimi?

{C.BOLD}Foydali buyruqlar:{C.END}
  >>> GroupLesson.objects.filter(homework_status='scheduled').count()
  >>> GroupLesson.objects.filter(homework_status='failed')[:5]
  >>> HomeworkDeliveryLog.objects.filter(status='sent')[:10]
""")