import base64
import hashlib
import json
import uuid
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import Accrual, OnlinePaymentTransaction, Payment


class OnlinePaymentError(Exception):
    pass


LIQPAY_SUCCESS_STATUSES = {'success', 'sandbox'}
LIQPAY_FAILED_STATUSES = {
    'failure',
    'error',
    'reversed',
    'subscribed',
    'unsubscribed',
    '3ds_verify',
    'captcha_verify',
    'cvv_verify',
    'ivr_verify',
    'otp_verify',
    'password_verify',
    'phone_verify',
    'pin_verify',
    'receiver_verify',
    'sender_verify',
    'senderapp_verify',
    'wait_qr',
    'wait_sender',
    'processing',
    'prepared',
    'wait_accept',
    'wait_card',
    'wait_compensation',
    'wait_lc',
    'wait_reserve',
    'wait_secure',
}


def liqpay_signature(data):
    if not settings.LIQPAY_PRIVATE_KEY:
        raise OnlinePaymentError('Платіжний сервіс не налаштовано.')
    digest = hashlib.sha1(
        f'{settings.LIQPAY_PRIVATE_KEY}{data}{settings.LIQPAY_PRIVATE_KEY}'.encode('utf-8')
    ).digest()
    return base64.b64encode(digest).decode('ascii')


def encode_liqpay_data(payload):
    raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return base64.b64encode(raw).decode('ascii')


def decode_liqpay_data(data):
    try:
        raw = base64.b64decode(data).decode('utf-8')
        return json.loads(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        raise OnlinePaymentError('Некоректні дані платіжного провайдера.') from exc


def build_absolute_url(request, view_name, *args):
    if settings.SITE_URL:
        return f"{settings.SITE_URL.rstrip('/')}{reverse(view_name, args=args)}"
    return request.build_absolute_uri(reverse(view_name, args=args))


def create_online_payment_transaction(user, accrual):
    if not settings.LIQPAY_PUBLIC_KEY or not settings.LIQPAY_PRIVATE_KEY:
        raise OnlinePaymentError('Платіжний сервіс поки не налаштовано.')
    if accrual.status != Accrual.Status.ACTIVE:
        raise OnlinePaymentError('Це нарахування неактивне.')
    if OnlinePaymentTransaction.objects.filter(
        accrual=accrual,
        status=OnlinePaymentTransaction.Status.SUCCESS,
    ).exists():
        raise OnlinePaymentError('Це нарахування вже оплачено онлайн.')

    existing_transaction = OnlinePaymentTransaction.objects.filter(
        user=user,
        accrual=accrual,
        status__in=[
            OnlinePaymentTransaction.Status.CREATED,
            OnlinePaymentTransaction.Status.PENDING,
        ],
    ).order_by('-created_at').first()
    if existing_transaction:
        return existing_transaction

    return OnlinePaymentTransaction.objects.create(
        user=user,
        plot=accrual.plot,
        accrual=accrual,
        amount=accrual.amount,
        provider=OnlinePaymentTransaction.Provider.LIQPAY,
        order_id=f'ACC-{accrual.pk}-{uuid.uuid4().hex[:18]}',
        status=OnlinePaymentTransaction.Status.PENDING,
    )


def build_liqpay_checkout(transaction_obj, request):
    payload = {
        'public_key': settings.LIQPAY_PUBLIC_KEY,
        'version': '3',
        'action': 'pay',
        'amount': str(transaction_obj.amount),
        'currency': 'UAH',
        'description': f'Оплата нарахування #{transaction_obj.accrual_id}, ділянка {transaction_obj.plot.number}',
        'order_id': transaction_obj.order_id,
        'result_url': build_absolute_url(request, 'online_payment_status', transaction_obj.order_id),
        'server_url': build_absolute_url(request, 'liqpay_callback'),
    }
    data = encode_liqpay_data(payload)
    return {
        'checkout_url': settings.LIQPAY_CHECKOUT_URL,
        'data': data,
        'signature': liqpay_signature(data),
        'payload': payload,
    }


def normalize_amount(value):
    try:
        return Decimal(str(value)).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError) as exc:
        raise OnlinePaymentError('Сума платежу некоректна.') from exc


def handle_liqpay_callback(data, signature):
    expected_signature = liqpay_signature(data)
    if signature != expected_signature:
        raise OnlinePaymentError('Підпис платежу неправильний.')

    payload = decode_liqpay_data(data)
    order_id = payload.get('order_id')
    if not order_id:
        raise OnlinePaymentError('Платіж без номера замовлення.')

    with transaction.atomic():
        try:
            transaction_obj = OnlinePaymentTransaction.objects.select_for_update().get(order_id=order_id)
        except OnlinePaymentTransaction.DoesNotExist as exc:
            raise OnlinePaymentError('Замовлення не знайдено.') from exc
        if transaction_obj.status == OnlinePaymentTransaction.Status.SUCCESS:
            return transaction_obj

        provider_status = payload.get('status', '')
        transaction_obj.provider_payment_id = str(payload.get('payment_id') or payload.get('transaction_id') or '')
        transaction_obj.provider_status = provider_status
        transaction_obj.provider_payload = payload

        if provider_status not in LIQPAY_SUCCESS_STATUSES:
            transaction_obj.status = OnlinePaymentTransaction.Status.FAILED
            transaction_obj.save(update_fields=[
                'provider_payment_id',
                'provider_status',
                'provider_payload',
                'status',
            ])
            return transaction_obj

        callback_amount = normalize_amount(payload.get('amount'))
        callback_currency = payload.get('currency')
        if callback_amount != normalize_amount(transaction_obj.amount):
            raise OnlinePaymentError('Сума платежу не збігається з нарахуванням.')
        if callback_currency != 'UAH':
            raise OnlinePaymentError('Валюта платежу має бути UAH.')
        if OnlinePaymentTransaction.objects.filter(
            accrual=transaction_obj.accrual,
            status=OnlinePaymentTransaction.Status.SUCCESS,
        ).exclude(pk=transaction_obj.pk).exists():
            transaction_obj.status = OnlinePaymentTransaction.Status.FAILED
            transaction_obj.save(update_fields=[
                'provider_payment_id',
                'provider_status',
                'provider_payload',
                'status',
            ])
            return transaction_obj

        payment = Payment.objects.create(
            plot=transaction_obj.plot,
            user=transaction_obj.user,
            amount=transaction_obj.amount,
            paid_at=timezone.localdate(),
            method=Payment.Method.ONLINE,
            status=Payment.Status.CONFIRMED,
            comment=f'Онлайн-оплата LiqPay, замовлення {transaction_obj.order_id}',
        )
        transaction_obj.payment = payment
        transaction_obj.status = OnlinePaymentTransaction.Status.SUCCESS
        transaction_obj.paid_at = timezone.now()
        transaction_obj.save(update_fields=[
            'payment',
            'provider_payment_id',
            'provider_status',
            'provider_payload',
            'status',
            'paid_at',
        ])
        return transaction_obj
