from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db import IntegrityError
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.views.generic import ListView, DetailView, CreateView
from django.db.models import Q
from django.core.paginator import Paginator
from django.utils import timezone
from django.urls import reverse_lazy
from apps.pages.views.home import AdminRequiredMixin
from apps.user.models import *
from django.views.generic import ListView, DetailView, View
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, View
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy
from django.contrib import messages
from django.db.models import Count, Sum, Avg, Q, F, Case, When, Value, IntegerField
class AdminStudentsView(AdminRequiredMixin, ListView):
    model = StudentProfile
    template_name = 'admin_user/students.html'
    context_object_name = 'students'
    paginate_by = 15

    def get_queryset(self):
        queryset = StudentProfile.objects.select_related('user').prefetch_related('groups').order_by('user__first_name')

        search = self.request.GET.get('search', '').strip()
        status = self.request.GET.get('status', 'all')
        group = self.request.GET.get('group', 'all')

        if search:
            queryset = queryset.filter(
                Q(user__first_name__icontains=search) |
                Q(user__last_name__icontains=search) |
                Q(user__phone_number__icontains=search)
            )
        if status != 'all':
            queryset = queryset.filter(status=status)
        if group != 'all':
            queryset = queryset.filter(groups__id=group)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search'] = self.request.GET.get('search', '')
        context['status'] = self.request.GET.get('status', 'all')
        context['selected_group'] = self.request.GET.get('group', 'all')
        context['groups'] = StudentGroup.objects.all()
        context['status_choices'] = StudentProfile.STATUS_CHOICES

        context['active_count'] = StudentProfile.objects.filter(status='active').count()
        context['frozen_count'] = StudentProfile.objects.filter(status='frozen').count()
        context['graduated_count'] = StudentProfile.objects.filter(status='graduated').count()
        return context


class AdminStudentDetailView(AdminRequiredMixin, DetailView):
    model = StudentProfile
    template_name = 'admin_user/student_detail.html'
    context_object_name = 'student'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['all_groups'] = StudentGroup.objects.all()
        context['status_choices'] = StudentProfile.STATUS_CHOICES
        return context


class AdminStudentActionView(AdminRequiredMixin, View):
    def post(self, request, pk):
        student = get_object_or_404(StudentProfile, pk=pk)
        action = request.POST.get('action')

        if action == 'change_status':
            new_status = request.POST.get('status')
            valid_statuses = dict(StudentProfile.STATUS_CHOICES).keys()
            if new_status in valid_statuses:
                student.status = new_status
                student.save()
        elif action == 'add_group':
            group_id = request.POST.get('group_id')
            group = get_object_or_404(StudentGroup, pk=group_id)
            student.groups.add(group)
        elif action == 'remove_group':
            group_id = request.POST.get('group_id')
            group = get_object_or_404(StudentGroup, pk=group_id)
            student.groups.remove(group)

        return redirect(request.META.get('HTTP_REFERER', 'admin_students'))

from django.views.generic import FormView
from django.urls import reverse_lazy
from apps.pages.forms import *

class AdminStudentCreateView(AdminRequiredMixin, FormView):
    template_name = 'admin_user/student_form.html'
    form_class = StudentCreateForm
    success_url = reverse_lazy('admin_students')
    from django.db import IntegrityError

    from django.contrib import messages
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
            student_profile = user.student_profile
            student_profile.birth_date = form.cleaned_data.get('birth_date')
            student_profile.parent_phone = form.cleaned_data.get('parent_phone')
            student_profile.balance = form.cleaned_data.get('balance') or 0
            student_profile.coins = form.cleaned_data.get('coins') or 0
            student_profile.save()

            # Muvaffaqiyat xabarida parolni ko'rsatish (yoki "standart parol" deb yozish)
            if form.cleaned_data.get('password'):
                messages.success(self.request, f"Yangi o‘quvchi qo‘shildi! Parol: {password}")
            else:
                messages.success(self.request, "Yangi o‘quvchi qo‘shildi! Standart parol: 123456")

            return super().form_valid(form)
        except IntegrityError:
            form.add_error('phone_number', "Bu telefon raqami allaqachon mavjud.")
            return self.form_invalid(form)
    def form_invalid(self, form):
        messages.error(self.request, "Xatolik yuz berdi. Iltimos, ma'lumotlarni tekshiring.")
        return super().form_invalid(form)

from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.generic import FormView, DetailView, UpdateView
from django.urls import reverse_lazy
import json

class AdminParentsView(AdminRequiredMixin, ListView):
    template_name = 'admin_user/parents.html'
    context_object_name = 'parents'
    paginate_by = 15

    def get_queryset(self):
        queryset = CustomUser.objects.filter(role='parent').order_by('first_name', 'last_name')

        search = self.request.GET.get('search', '').strip()
        sort = self.request.GET.get('sort', 'name')

        if search:
            queryset = queryset.filter(
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(phone_number__icontains=search)
            )

        # Saralash
        if sort == 'children':
            queryset = queryset.annotate(num_children=Count('student_profiles')).order_by('-num_children')
        elif sort == 'requests':
            queryset = queryset.annotate(num_requests=Count('question_requests')).order_by('-num_requests')
        elif sort == 'newest':
            queryset = queryset.order_by('-date_joined')
        # else: already ordered by name

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search'] = self.request.GET.get('search', '')
        context['sort'] = self.request.GET.get('sort', 'name')

        parents = context['parents']
        for parent in parents:
            parent.children = StudentProfile.objects.filter(parent_phone=parent.phone_number).select_related('user')[:5]
            parent.children_count = StudentProfile.objects.filter(parent_phone=parent.phone_number).count()
            parent.last_sms = SMSLog.objects.filter(notification__user=parent).order_by('-sent_at').first()

        context['total_parents'] = CustomUser.objects.filter(role='parent').count()
        context['pending_requests_count'] = ParentQuestionRequest.objects.filter(status='pending').count()
        context['sms_sent_count'] = SMSLog.objects.filter(status='sent').count()
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
            role='parent'
        )
        messages.success(self.request, "Yangi ota-ona muvaffaqiyatli qo'shildi!")
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
        context['children'] = StudentProfile.objects.filter(parent_phone=parent.phone_number).select_related('user')
        context['requests'] = ParentQuestionRequest.objects.filter(parent=parent).select_related('student', 'lesson')
        context['sms_logs'] = SMSLog.objects.filter(notification__user=parent).order_by('-sent_at')[:10]
        return context


class AdminParentEditView(AdminRequiredMixin, UpdateView):
    model = CustomUser
    template_name = 'admin_user/parent_form.html'
    fields = ['first_name', 'last_name', 'phone_number']
    success_url = reverse_lazy('admin_parents')

    def get_queryset(self):
        return CustomUser.objects.filter(role='parent')


@require_POST
def admin_send_sms(request):
    """SMS yuborish endpoint (AJAX uchun)"""
    data = json.loads(request.body)
    phone = data.get('phone')
    message = data.get('message')

    if not phone or not message:
        return JsonResponse({'success': False, 'error': 'Telefon va xabar matni kerak'}, status=400)

    # Ota-onani topamiz
    try:
        parent = CustomUser.objects.get(phone_number=phone, role='parent')
    except CustomUser.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Ota-ona topilmadi'}, status=404)

    # Notification yaratamiz va SMS yuborilgan deb belgilaymiz
    notification = Notification.objects.create(
        user=parent,
        notification_type='custom',
        message=message,
        is_approved=True,
        sent=True,
        created_at=timezone.now()
    )
    SMSLog.objects.create(
        notification=notification,
        phone_number=phone,
        status='sent',
        sent_at=timezone.now()
    )

    return JsonResponse({'success': True})