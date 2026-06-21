import secrets
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import LoginCode, UserProfile, normalize_phone
from .sms import SmsSendError, send_sms


class LoginCodeError(Exception):
    pass


def generate_code():
    return f'{secrets.randbelow(1_000_000):06d}'


def find_login_profile(phone):
    normalized_phone = normalize_phone(phone)
    profile = (
        UserProfile.objects.select_related('user')
        .filter(phone=normalized_phone, user__is_active=True)
        .first()
    )
    if not profile or not profile.user_id:
        raise LoginCodeError('Профіль з таким номером телефону не знайдено.')
    if not profile.linked_plots.exists():
        raise LoginCodeError('До цього профілю ще не привʼязано жодної ділянки.')
    return profile


def assert_code_rate_limits(phone):
    now = timezone.now()
    cooldown_start = now - timedelta(seconds=settings.LOGIN_CODE_RESEND_COOLDOWN_SECONDS)
    day_start = now - timedelta(days=1)

    if LoginCode.objects.filter(phone=phone, created_at__gte=cooldown_start).exists():
        raise LoginCodeError('Код вже надіслано. Спробуйте трохи пізніше.')

    daily_count = LoginCode.objects.filter(phone=phone, created_at__gte=day_start).count()
    if daily_count >= settings.LOGIN_CODE_DAILY_LIMIT:
        raise LoginCodeError('На сьогодні ліміт SMS-кодів для цього номера вичерпано.')


def create_and_send_login_code(phone):
    profile = find_login_profile(phone)
    phone = normalize_phone(phone)
    assert_code_rate_limits(phone)

    code = generate_code()
    login_code = LoginCode(
        user=profile.user,
        phone=phone,
        expires_at=timezone.now() + timedelta(minutes=settings.LOGIN_CODE_TTL_MINUTES),
    )
    login_code.set_code(code)
    login_code.save()

    try:
        send_sms(phone, f'Ваш код для входу в СТ «Економіст»: {code}')
    except SmsSendError:
        login_code.delete()
        raise

    return login_code


def verify_login_code(login_code_id, code):
    try:
        login_code = LoginCode.objects.select_related('user').get(pk=login_code_id)
    except LoginCode.DoesNotExist as exc:
        raise LoginCodeError('Код не знайдено. Запитайте новий код.') from exc

    if login_code.used:
        raise LoginCodeError('Цей код вже використано.')
    if login_code.is_expired:
        raise LoginCodeError('Термін дії коду минув. Запитайте новий код.')
    if login_code.attempts >= settings.LOGIN_CODE_MAX_ATTEMPTS:
        raise LoginCodeError('Перевищено кількість спроб. Запитайте новий код.')

    login_code.attempts += 1
    login_code.save(update_fields=['attempts'])

    if not login_code.check_code(code):
        if login_code.attempts >= settings.LOGIN_CODE_MAX_ATTEMPTS:
            raise LoginCodeError('Перевищено кількість спроб. Запитайте новий код.')
        raise LoginCodeError('Код неправильний. Спробуйте ще раз.')

    login_code.mark_used()
    return login_code.user
