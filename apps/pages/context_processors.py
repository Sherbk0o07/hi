from apps.user.models import MenuItem,MenuSection

# context_processors.py

def menu_processor(request):
    sections = MenuSection.objects.filter(is_active=True).prefetch_related('items')
    # Barcha aktiv item’larni bo‘limlari bilan olamiz
    return {'menu_sections': sections}
from django.utils import timezone
from datetime import timedelta
from apps.user.models import Quiz

def new_quizzes_count(request):
    """Barcha sahifalarda yangi testlar sonini ko'rsatish."""
    recent_threshold = timezone.now() - timedelta(hours=24)
    count = Quiz.objects.filter(is_active=True, created_at__gte=recent_threshold).count()
    return {'new_quizzes_count': count}

# apps/pages/context_processors.py
from apps.user.models import StudentProfile, ParentQuestionRequest

def parent_request_counts(request):
    if request.user.is_authenticated and request.user.role == 'parent':
        parent = request.user
        children = StudentProfile.objects.filter(parent_phone=parent.phone_number)
        child_ids = children.values_list('id', flat=True)

        pending_count = ParentQuestionRequest.objects.filter(
            parent=parent,
            student_id__in=child_ids,
            status='pending'
        ).count()
        approved_count = ParentQuestionRequest.objects.filter(
            parent=parent,
            student_id__in=child_ids,
            status='approved'
        ).count()
        return {
            'pending_request_count': pending_count,
            'approved_request_count': approved_count,
        }
    return {}