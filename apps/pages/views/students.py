"""
O‘quvchilar va ota-onalar boshqaruvi.
"""
import json

from django.contrib import messages
from django.db import IntegrityError
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.decorators.http import require_POST
from django.views.generic import (
    ListView, DetailView, FormView, UpdateView,
)

from apps.pages.views.home import AdminRequiredMixin
from apps.pages.forms import StudentCreateForm, ParentCreateForm
from apps.user.models import (
    StudentProfile, StudentGroup, CustomUser,
    ParentQuestionRequest, SMSLog, Notification,
)


# ═══════════════════════════════════════════════════════════════
# O‘QUVCHILAR
# ═══════════════════════════════════════════════════════════════

class AdminStudentsView(AdminRequiredMixin, ListView):
    model = StudentProfile
    template_name = 'admin_user/students.html'
    context_object_name = 'students'
    paginate_by = 15

    def get_queryset(self):
        queryset = (
            StudentProfile.objects
            .select_related('user')
            .prefetch_related('groups')
            .order_by('user__first_name', 'user__last_name')
        )

        search = self.request.GET.get('search', '').strip()
        status = self.request.GET.get('status', 'all')
        group = self.request.GET.get('group', 'all')

        if search:
            queryset = queryset.filter(
                Q(user__first_name__icontains=search)
                | Q(user__last_name__icontains=search)
                | Q(user__phone_number__icontains=search)
            )
        if status and status != 'all':
            queryset = queryset.filter(status=status)
        if group and group != 'all':
            queryset = queryset.filter(groups__id=group)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'search': self.request.GET.get('search', ''),
            'status': self.request.GET.get('status', 'all'),
            'selected_group': self.request.GET.get('group', 'all'),
            'groups': StudentGroup.objects.all(),
            'status_choices': StudentProfile.STATUS_CHOICES,
            'active_count': StudentProfile.objects.filter(status='active').count(),
            'frozen_count': StudentProfile.objects.filter(status='frozen').count(),
            'graduated_count': StudentProfile.objects.filter(status='graduated').count(),
        })
        return context


class AdminStudentDetailView(AdminRequiredMixin, DetailView):
    model = StudentProfile
    template_name = 'admin_user/student_detail.html'
    context_object_name = 'student'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'all_groups': StudentGroup.objects.all(),
            'status_choices': StudentProfile.STATUS_CHOICES,
        })
        return context


class AdminStudentActionView(AdminRequiredMixin, View):
    """O‘quvchi ustida amallar: status, group qo‘shish/olib tashlash."""

    def post(self, request, pk):
        student = get_object_or_404(StudentProfile, pk=pk)
        action = request.POST.get('action')

        if action == 'change_status':
            new_status = request.POST.get('status')
            if new_status in dict(StudentProfile.STATUS_CHOICES):
                student.status = new_status
                student.save(update_fields=['status'])
                messages.success(request, "Holat o‘zgartirildi.")

        elif action == 'add_group':
            group_id = request.POST.get('group_id')
            group = get_object_or_404(StudentGroup, pk=group_id)
            student.groups.add(group)
            messages.success(request, f"{group.name} guruhiga qo‘shildi.")

        elif action == 'remove_group':
            group_id = request.POST.get('group_id')
            group = get_object_or_404(StudentGroup, pk=group_id)
            student.groups.remove(group)
            messages.success(request, f"{group.name} guruhidan olib tashlandi.")

        return redirect(request.META.get('HTTP_REFERER', 'admin_students'))


class AdminStudentCreateView(AdminRequiredMixin, FormView):
    template_name = 'admin_user/student_form.html'
    form_class = StudentCreateForm
    success_url = reverse_lazy('admin_students')

    def form_valid(self, form):
        try:
            password = form.cleaned_data.get('password') or '123456'
            user = CustomUser.objects.create_user(
                phone_number=form.cleaned_data['phone_number'],
                password=password,
                first_name=form.cleaned_data['first_name'],
                last_name=form.cleaned_data['last_name'],
                role='student',
            )

            # Signal avtomatik StudentProfile yaratadi
            student_profile = user.student_profile
            student_profile.birth_date = form.cleaned_data.get('birth_date')
            student_profile.parent_phone = form.cleaned_data.get('parent_phone')
            student_profile.balance = form.cleaned_data.get('balance') or 0
            student_profile.coins = form.cleaned_data.get('coins') or 0
            student_profile.save()

            messages.success(
                self.request,
                f"Yangi o‘quvchi qo‘shildi! Parol: {password}"
            )
            return super().form_valid(form)

        except IntegrityError:
            form.add_error('phone_number', "Bu telefon raqami allaqachon mavjud.")
            return self.form_invalid(form)

    def form_invalid(self, form):
        messages.error(self.request, "Xatolik. Iltimos, ma’lumotlarni tekshiring.")
        return super().form_invalid(form)


# ═══════════════════════════════════════════════════════════════
# OTA-ONALAR
# ═══════════════════════════════════════════════════════════════

class AdminParentsView(AdminRequiredMixin, ListView):
    template_name = 'admin_user/parents.html'
    context_object_name = 'parents'
    paginate_by = 15

    def get_queryset(self):
        queryset = (
            CustomUser.objects
            .filter(role='parent')
            .order_by('first_name', 'last_name')
        )

        search = self.request.GET.get('search', '').strip()
        sort = self.request.GET.get('sort', 'name')

        if search:
            queryset = queryset.filter(
                Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(phone_number__icontains=search)
            )

        if sort == 'newest':
            queryset = queryset.order_by('-date_joined')

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search'] = self.request.GET.get('search', '')
        context['sort'] = self.request.GET.get('sort', 'name')

        for parent in context['parents']:
            parent.children = StudentProfile.objects.filter(
                parent_phone=parent.phone_number
            ).select_related('user')[:5]
            parent.children_count = StudentProfile.objects.filter(
                parent_phone=parent.phone_number
            ).count()
            parent.last_sms = SMSLog.objects.filter(
                notification__user=parent
            ).order_by('-sent_at').first()

        context.update({
            'total_parents': CustomUser.objects.filter(role='parent').count(),
            'pending_requests_count': ParentQuestionRequest.objects.filter(status='pending').count(),
            'sms_sent_count': SMSLog.objects.filter(status='sent').count(),
        })
        return context


class AdminParentCreateView(AdminRequiredMixin, FormView):
    template_name = 'admin_user/parent_form.html'
    form_class = ParentCreateForm
    success_url = reverse_lazy('admin_parents')

    def form_valid(self, form):
        phone = form.cleaned_data['phone_number']
        if CustomUser.objects.filter(phone_number=phone).exists():
            form.add_error('phone_number', "Bu telefon raqami allaqachon mavjud.")
            return self.form_invalid(form)

        password = form.cleaned_data.get('password') or '123456'
        CustomUser.objects.create_user(
            phone_number=phone,
            password=password,
            first_name=form.cleaned_data['first_name'],
            last_name=form.cleaned_data['last_name'],
            role='parent',
        )
        messages.success(self.request, "Yangi ota-ona qo‘shildi!")
        return super().form_valid(form)


class AdminParentDetailView(AdminRequiredMixin, DetailView):
    model = CustomUser
    template_name = 'admin_user/parent_detail.html'
    context_object_name = 'parent'

    def get_queryset(self):
        return CustomUser.objects.filter(role='parent')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        parent = self.get_object()
        context.update({
            'children': StudentProfile.objects.filter(
                parent_phone=parent.phone_number
            ).select_related('user'),
            'requests': ParentQuestionRequest.objects.filter(
                parent=parent
            ).select_related('student', 'lesson'),
            'sms_logs': SMSLog.objects.filter(
                notification__user=parent
            ).order_by('-sent_at')[:10],
        })
        return context


class AdminParentEditView(AdminRequiredMixin, UpdateView):
    model = CustomUser
    template_name = 'admin_user/parent_form.html'
    fields = ['first_name', 'last_name', 'phone_number']
    success_url = reverse_lazy('admin_parents')

    def get_queryset(self):
        return CustomUser.objects.filter(role='parent')


# ═══════════════════════════════════════════════════════════════
# SMS YUBORISH (AJAX)
# ═══════════════════════════════════════════════════════════════

@require_POST
def admin_send_sms(request):
    """SMS yuborish endpoint (AJAX uchun)."""
    # Faqat admin
    if not (request.user.is_authenticated and
            (request.user.is_superuser or request.user.role == 'admin')):
        return JsonResponse({'success': False, 'error': 'Ruxsat yo‘q'}, status=403)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Noto‘g‘ri format'}, status=400)

    phone = (data.get('phone') or '').strip()
    message = (data.get('message') or '').strip()

    if not phone or not message:
        return JsonResponse(
            {'success': False, 'error': 'Telefon va xabar kerak'},
            status=400
        )

    try:
        parent = CustomUser.objects.get(phone_number=phone, role='parent')
    except CustomUser.DoesNotExist:
        return JsonResponse(
            {'success': False, 'error': 'Ota-ona topilmadi'},
            status=404
        )

    notification = Notification.objects.create(
        user=parent,
        notification_type='custom',
        message=message,
        is_approved=True,
        sent=True,
        approved_by=request.user,
        approved_at=timezone.now(),
    )

    SMSLog.objects.create(
        notification=notification,
        phone_number=phone,
        status='sent',
        sent_at=timezone.now(),
    )

    return JsonResponse({'success': True})
