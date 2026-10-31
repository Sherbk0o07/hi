from http.client import responses
from django.db.models import Q
from django.views.generic import (
    ListView,
    TemplateView,
    CreateView,
    DeleteView,
)
from django.contrib import messages
from apps.service import LoginService
from django.urls import reverse_lazy
from django.shortcuts import render, redirect
import apps.core.models as models

class LoginImgView(ListView):
    model = models.LoginModel
    template_name = 's/login_img.html'
    context_object_name = 'login_img_obj'

    def get_queryset(self):
        queryset = super().get_queryset()
        status = self.request.GET.get('status')
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(
                    description__icontains=search
                )
            )
        if status == 'no_active':
            queryset = queryset.filter(is_active=False)
        if status == 'active':
            queryset = queryset.filter(is_active=True)

        return queryset



class CreateImgView(CreateView):
    model = models.LoginModel
    fields = ['cover_img','description','is_active']
    template_name = 's/create_img.html'
    success_url = reverse_lazy('login_img_view')

    def form_valid(self, form):

        response = super().form_valid(form)
        LoginService.activate(self.object)
        return response


def delete_login_img(request,pk):
    obj = models.LoginModel.objects.filter(id=pk)
    obj.delete()
    messages.success(request,"Rasm ochirib yuborildi ")
    return redirect('login_img_view')