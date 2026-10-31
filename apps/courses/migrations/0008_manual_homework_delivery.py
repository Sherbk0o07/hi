from django.db import migrations, models


def move_scheduled_homework_to_manual(apps, schema_editor):
    GroupLesson = apps.get_model('courses', 'GroupLesson')
    GroupLesson.objects.filter(homework_status='scheduled').update(
        homework_status='pending',
        scheduled_task_id=None,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('courses', '0007_homeworkdeliverylog'),
    ]

    operations = [
        migrations.RunPython(
            move_scheduled_homework_to_manual,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name='grouplesson',
            name='homework_status',
            field=models.CharField(
                choices=[
                    ('pending', 'Qo‘lda yuborish kutilmoqda'),
                    ('scheduled', 'Rejalashtirilgan'),
                    ('sending', 'Yuborilmoqda'),
                    ('sent', 'Yuborildi'),
                    ('failed', 'Xatolik'),
                    ('partial', 'Qismiy'),
                    ('cancelled', 'Bekor qilindi'),
                ],
                db_index=True,
                default='pending',
                max_length=20,
            ),
        ),
    ]
