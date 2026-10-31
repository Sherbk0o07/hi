"""
Bildirishnomalar va SMS loglari boshqaruvi.
"""
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView, DetailView, ListView, CreateView

from apps.pages.views.home import AdminRequiredMixin
from apps.user.models import Notification, SMSLog, CustomUser


# ═══════════════════════════════════════════════════════════════
# BILDIRISHNOMALAR RO‘YXATI
# ═══════════════════════════════════════════════════════════════

class AdminNotificationsView(AdminRequiredMixin, TemplateView):
    template_name = 'admin_user/notifications.html'
    paginate_by = 15

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        queryset = (
            Notification.objects
            .select_related('user', 'approved_by')
            .order_by('-created_at')
        )

        # Qidiruv
        search = self.request.GET.get('search', '').strip()
        if search:
            queryset = queryset.filter(
                Q(message__icontains=search)
                | Q(user__phone_number__icontains=search)
                | Q(user__first_name__icontains=search)
                | Q(user__last_name__icontains=search)
            )

        # Tur filter
        notif_type = self.request.GET.get('type', 'all')
        if notif_type and notif_type != 'all':
            queryset = queryset.filter(notification_type=notif_type)

        # Holat filter
        status = self.request.GET.get('status', 'all')
        status_filter_map = {
            'pending':  {'is_approved': False},
            'approved': {'is_approved': True},
            'sent':     {'sent': True},
            'unsent':   {'sent': False},
            'unread':   {'is_read': False},
        }
        if status in status_filter_map:
            queryset = queryset.filter(**status_filter_map[status])

        # Statistika
        context.update({
            'total_notifications': Notification.objects.count(),
            'pending_notifications': Notification.objects.filter(is_approved=False).count(),
            'approved_count': Notification.objects.filter(is_approved=True).count(),
            'sent_count': Notification.objects.filter(sent=True).count(),
            'unread_count': Notification.objects.filter(is_read=False).count(),
        })

        # Pagination
        paginator = Paginator(queryset, self.paginate_by)
        page_obj = paginator.get_page(self.request.GET.get('page', 1))
        context['page_obj'] = page_obj
        context['notifications'] = page_obj
        context['search'] = search
        context['notif_type'] = notif_type
        context['status'] = status
        context['notification_types'] = Notification.NOTIFICATION_TYPES

        return context


# ═══════════════════════════════════════════════════════════════
# YANGI BILDIRISHNOMA YARATISH
# ═══════════════════════════════════════════════════════════════

class AdminNotificationCreateView(AdminRequiredMixin, CreateView):
    model = Notification
    template_name = 'admin_user/notification_form.html'
    fields = ['user', 'notification_type', 'title', 'priority', 'message']
    success_url = reverse_lazy('admin_notifications')

    def form_valid(self, form):
        # created_at — auto_now_add, qo‘lda o‘rnatilmaydi
        messages.success(self.request, "Yangi bildirishnoma yaratildi.")
        return super().form_valid(form)


# ═══════════════════════════════════════════════════════════════
# AMALLAR (approve / reject / send_sms / mark_read / delete)
# ═══════════════════════════════════════════════════════════════

class AdminNotificationActionView(AdminRequiredMixin, View):
    """POST orqali bildirishnoma amallarini bajarish."""

    def post(self, request, pk):
        notification = get_object_or_404(Notification, pk=pk)
        action = request.POST.get('action')

        if action == 'approve':
            notification.is_approved = True
            notification.approved_by = request.user
            notification.approved_at = timezone.now()
            notification.save(update_fields=['is_approved', 'approved_by', 'approved_at'])
            messages.success(request, "Bildirishnoma tasdiqlandi.")

        elif action == 'reject':
            notification.is_approved = False
            notification.approved_by = None
            notification.approved_at = None
            notification.save(update_fields=['is_approved', 'approved_by', 'approved_at'])
            messages.warning(request, "Bildirishnoma rad etildi.")

        elif action == 'send_sms':
            if not notification.is_approved:
                messages.error(request, "Avval tasdiqlang!")
            elif notification.sent:
                messages.info(request, "SMS allaqachon yuborilgan.")
            else:
                # SMS yuborish logikasi (mock)
                # Haqiqiy loyihada: apps.services.sms.send(phone, message)
                notification.sent = True
                notification.save(update_fields=['sent'])
                SMSLog.objects.create(
                    notification=notification,
                    phone_number=notification.user.phone_number,
                    status='sent',
                    sent_at=timezone.now(),
                )
                messages.success(request, "SMS yuborildi.")

        elif action == 'mark_read':
            notification.is_read = True
            notification.read_at = timezone.now()
            notification.save(update_fields=['is_read', 'read_at'])

        elif action == 'delete':
            notification.delete()
            messages.success(request, "Bildirishnoma o‘chirildi.")
            return redirect('admin_notifications')

        return redirect(request.META.get('HTTP_REFERER', 'admin_notifications'))


# ═══════════════════════════════════════════════════════════════
# SMS LOGLAR
# ═══════════════════════════════════════════════════════════════

class AdminSMSLogsView(AdminRequiredMixin, ListView):
    model = SMSLog
    template_name = 'admin_user/sms_logs.html'
    context_object_name = 'sms_logs'
    paginate_by = 20

    def get_queryset(self):
        queryset = (
            SMSLog.objects
            .select_related('notification', 'notification__user')
            .order_by('-sent_at')
        )

        search = self.request.GET.get('search', '').strip()
        status = self.request.GET.get('status', 'all')

        if search:
            queryset = queryset.filter(
                Q(phone_number__icontains=search)
                | Q(notification__message__icontains=search)
            )
        if status and status != 'all':
            queryset = queryset.filter(status=status)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search'] = self.request.GET.get('search', '')
        context['status'] = self.request.GET.get('status', 'all')
        return context


# ═══════════════════════════════════════════════════════════════
# BILDIRISHNOMA TAFSILOTI
# ═══════════════════════════════════════════════════════════════

class AdminNotificationDetailView(AdminRequiredMixin, DetailView):
    model = Notification
    template_name = 'admin_user/notification_detail.html'
    context_object_name = 'notification'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['sms_logs'] = self.get_object().sms_logs.order_by('-sent_at')
        return context