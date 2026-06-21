import json
import urllib.error
import urllib.request

from django.conf import settings


class SmsSendError(Exception):
    pass


def send_sms(phone, message):
    backend = settings.SMS_BACKEND
    if backend == 'console':
        print(f'SMS to {phone}: {message}')
        return
    if backend != 'http':
        raise SmsSendError('SMS-сервіс налаштовано неправильно.')
    if not settings.SMS_PROVIDER_URL or not settings.SMS_API_KEY:
        raise SmsSendError('SMS-сервіс не налаштовано. Зверніться до адміністратора.')

    payload = json.dumps({
        'to': phone,
        'message': message,
        'sender': settings.SMS_SENDER,
    }).encode('utf-8')
    request = urllib.request.Request(
        settings.SMS_PROVIDER_URL,
        data=payload,
        headers={
            'Authorization': f'Bearer {settings.SMS_API_KEY}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )

    try:
        with urllib.request.urlopen(request, timeout=settings.SMS_TIMEOUT_SECONDS) as response:
            if response.status >= 400:
                raise SmsSendError('SMS не вдалося надіслати. Спробуйте пізніше.')
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SmsSendError('SMS не вдалося надіслати. Спробуйте пізніше.') from exc
