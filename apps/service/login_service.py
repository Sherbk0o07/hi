from  django.db import  transaction
from django.conf import  settings
from  apps.core.models import  LoginModel

MAX_ACTIVE = getattr(settings,'LOGIN_MAX_ACTIVE',2)



class LoginService:

    @staticmethod
    @transaction.atomic
    def activate(instance: LoginModel):
        if not instance.pk:
            instance.save()


        instance.is_active = True
        instance.save(update_fields=['is_active'])
        active_qs = (
            LoginModel.objects
            .filter(is_active=True)
            .exclude(pk=instance.pk)
            .order_by("-id")
        )
        ids_to_deactivate = list(active_qs.values_list('id', flat=True)[MAX_ACTIVE - 1:])
        if ids_to_deactivate:
            LoginModel.objects.filter(id__in=ids_to_deactivate).update(is_active=False)

        return instance
#
# class Banner:
#     pass
#
# MAX_ACTIVE = 3
# class BannerService:
#
#     @staticmethod
#     @transaction.atomic
#     def active(instance: Banner):
#         if not instance.pk:
#             instance.save()
#         if instance.is_active == True:
#             return instance
#
#         instance.is_active = True
#         instance.save(update_fields=['is_active'])
#
#         (
#             Banner.objects
#             .filter(is_active=True)
#             .exclude(pk=instance.pk)
#             .order_by('-id')[MAX_ACTIVE - 1:]
#             .update(is_active=False)
#         )