from django.contrib.auth import logout
from django.shortcuts import render,redirect



def logout_view(request):
    logout(request)
    return redirect('home_page_view')