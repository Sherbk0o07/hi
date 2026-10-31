from django import forms
from django.core.validators import RegexValidator

from apps.user.models import CustomUser, StudentProfile
from django import forms
from django.core.validators import RegexValidator


class ParentCreateForm(forms.Form):
    first_name = forms.CharField(max_length=150, label="Ism")
    last_name = forms.CharField(max_length=150, label="Familiya")
    phone_number = forms.CharField(max_length=17, label="Telefon raqam", validators=[
        RegexValidator(regex=r"^\+?998\d{9}$", message="+998901234567 formatida kiriting")
    ])
    password = forms.CharField(widget=forms.PasswordInput, required=True, label="Parol")
class StudentCreateForm(forms.Form):
    first_name = forms.CharField(max_length=150, label="Ism")
    last_name = forms.CharField(max_length=150, label="Familiya")
    phone_number = forms.CharField(max_length=17, label="Telefon raqam", validators=[
        RegexValidator(regex=r"^\+?998\d{9}$", message="+998901234567 formatida kiriting")
    ])
    password = forms.CharField(widget=forms.PasswordInput, required=False, label="Parol (ixtiyoriy)")
    birth_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}), label="Tug'ilgan sana")
    parent_phone = forms.CharField(max_length=17, required=False, label="Ota-ona telefon raqami")
    balance = forms.DecimalField(max_digits=12, decimal_places=2, initial=0.00, required=False, label="Balans")
    coins = forms.IntegerField(min_value=0, initial=0, required=False, label="Coinlar")

    def clean_phone_number(self):
        phone = self.cleaned_data.get('phone_number')
        if phone and CustomUser.objects.filter(phone_number=phone).exists():
            raise forms.ValidationError("Bu telefon raqami allaqachon ro'yxatdan o'tgan.")
        return phone