from django.db import models


class LoginModel(models.Model):
   cover_img = models.ImageField(upload_to='img/login/')
   description = models.CharField(max_length=50)
   is_active = models.BooleanField(default=False)

   def __str__(self):
       return 'cover_img'

