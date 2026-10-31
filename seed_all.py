# test_sherbek_send.py
"""
Sherbekka HAQIQIY test yuborish.
Test script O'ZI scheduler ishga tushiradi.
"""
import os
import django
import sys
import time

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.utils import timezone
from datetime import timedelta
from apps.user.models import CustomUser, StudentGroup
from apps.courses.models import GroupLesson
from apps.service.homework_scheduler import HomeworkScheduler


def main():
    print("\n" + "=" * 55)
    print("  SHERBEK UCHUN HAQIQIY TEST")
    print("=" * 55)

    # ═══ 1. SCHEDULER ISHGA TUSHIRISH ═══
    print("\n1️⃣ Scheduler ishga tushirilmoqda...")
    from config import scheduler as sched_module

    if sched_module._scheduler is None:
        sched_module.start()
        time.sleep(2)

    scheduler = sched_module._scheduler
    if not scheduler or not scheduler.running:
        print("❌ Scheduler ishga tushmadi!")
        return

    print(f"✅ Scheduler ishlayapti")
    print(f"   Jami joblar: {len(scheduler.get_jobs())}")

    # ═══ 2. SHERBEK ═══
    user = CustomUser.objects.filter(phone_number__contains='888085088').first()
    if not user:
        print("❌ Sherbek topilmadi")
        return

    student = user.student_profile
    link = user.telegram_link
    print(f"\n2️⃣ 👤 {user.get_full_name()}")
    print(f"   📱 Chat ID: {link.chat_id}")

    # ═══ 3. GURUH ═══
    group = StudentGroup.objects.filter(students=student).first()
    if not group:
        print("❌ Guruh yo'q")
        return

    print(f"\n3️⃣ 👥 Guruh: {group.name}")

    # Schedule — 2 daqiqadan keyin
    now = timezone.localtime()
    test_time = now + timedelta(minutes=2)
    today_name = ['monday','tuesday','wednesday','thursday',
                  'friday','saturday','sunday'][now.weekday()]

    group.schedule = {today_name: test_time.strftime('%H:%M')}
    group.save()
    print(f"   📅 Schedule: {today_name} {test_time.strftime('%H:%M')}")
    print(f"   ⏰ Hozir: {now.strftime('%H:%M:%S')}")

    # ═══ 4. GL TOPISH ═══
    gl = GroupLesson.objects.filter(
        group=group,
        lesson__homework__is_approved=True,
    ).first()

    if not gl:
        print("\n❌ Approved homework bilan GL topilmadi")
        print("   Sabablari:")
        print("   - Bu guruhda homework tasdiqlanmagan")
        print("   - Yoki GL yaratilmagan")
        print("\n💡 Barcha GL larni ko'rish:")
        all_gls = GroupLesson.objects.filter(group=group)
        print(f"   Jami: {all_gls.count()} ta GL")
        for g in all_gls[:5]:
            hw = getattr(g.lesson, 'homework', None)
            print(f"   • GL#{g.pk}: approved={hw.is_approved if hw else 'no hw'}")
        return

    print(f"\n4️⃣ 📝 GL#{gl.pk}")
    print(f"   Dars: {gl.lesson.title[:50]}")
    print(f"   Homework: {gl.lesson.homework.title}")

    # ═══ 5. RESET VA QAYTA REJALASHTIRISH ═══
    gl.homework_status = 'pending'
    gl.scheduled_task_id = None
    gl.lesson_date = now.date()
    gl.save()

    result = HomeworkScheduler.schedule_homework(gl, force=True)
    print(f"\n5️⃣ 📊 Natija: {result}")

    if not result.get('scheduled'):
        print(f"❌ Xato: {result.get('reason')}")
        return

    print(f"\n✅ REJALASHTIRILDI!")
    print(f"   🆔 Job: {result.get('job_id')}")
    print(f"   ⏰ ETA: {result.get('eta')}")

    # ═══ 6. KUTISH ═══
    eta = result.get('eta')
    wait = int((eta - timezone.now()).total_seconds()) + 5
    if wait < 5:
        wait = 5

    print(f"\n⏳ Kutish: {wait} sekund...")
    print("📱 Telegram'ni kuzatib turing!\n")

    for i in range(wait, 0, -1):
        sys.stdout.write(f"\r   ⏰ {i} sekund...  ")
        sys.stdout.flush()
        time.sleep(1)

    print("\n\n✅ VAQT KELDI!\n")

    # ═══ 7. NATIJA ═══
    time.sleep(5)
    gl.refresh_from_db()

    print("=" * 55)
    print("  NATIJA")
    print("=" * 55)
    print(f"📅 Status: {gl.homework_status}")
    print(f"📤 Yuborildi: {gl.homework_recipients_count}")
    print(f"❌ Xato: {gl.homework_failed_count}")

    if gl.homework_status == 'sent':
        print(f"\n🎉 MUVAFFAQIYATLI!")
    else:
        print(f"\n⚠️  Status: {gl.homework_status}")

    # Scheduler to'xtatish
    try:
        scheduler.shutdown(wait=False)
    except:
        pass


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️  To'xtatildi")