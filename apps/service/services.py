import re
import requests
from django.conf import settings

def clean_phone_number(phone: str) -> str:
    """
    Telefon raqamini tozalaydi va xalqaro formatga keltiradi.
    Misol: +998901234567 -> 998901234567 (yoki 998901234567)
    """
    if not phone:
        return ''
    # Faqat raqamlarni qoldiring
    digits = re.sub(r'\D', '', phone)
    # Agar 998 bilan boshlansa, shunday qoldiring
    if digits.startswith('998'):
        return digits
    # Agar 9 bilan boshlansa (ichki format), oldiga 998 qo'shing
    if digits.startswith('9') and len(digits) == 9:
        return '998' + digits
    # Aks holda qanday bo'lsa shunday qaytaring
    return digits


def send_sms(phone: str, message: str) -> dict:
    """
    SMS yuborish funksiyasi (Eskiz.uz misolida).
    settings.py da quyidagilar bo'lishi kerak:
    SMS_PROVIDER = 'eskiz'
    SMS_API_URL = 'https://notify.eskiz.uz/api/message/sms/send'
    SMS_API_KEY = '...'  (yoki token)
    """
    phone = clean_phone_number(phone)
    if not phone:
        return {'success': False, 'error': 'Telefon raqami xato'}

    try:
        api_url = getattr(settings, 'SMS_API_URL', 'https://notify.eskiz.uz/api/message/sms/send')
        api_key = getattr(settings, 'SMS_API_KEY', '')
        headers = {'Authorization': f'Bearer {api_key}'}
        data = {
            'mobile_phone': phone,
            'message': message,
            'from': '4546',  # Eskiz.uz da tasdiqlangan sender
        }
        response = requests.post(api_url, json=data, headers=headers, timeout=10)
        result = response.json()
        if response.status_code == 200 and result.get('status') == 'success':
            return {'success': True, 'message_id': result.get('message_id')}
        else:
            return {'success': False, 'error': result.get('message', 'Xato')}
    except Exception as e:
        return {'success': False, 'error': str(e)}