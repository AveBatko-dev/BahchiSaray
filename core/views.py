from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Sum
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .forms import LoginCodeForm, MeterReadingForm, PaymentReceiptForm, PhoneLoginForm
from .models import Accrual, Announcement, OnlinePaymentTransaction, Payment, Plot
from .online_payments import (
    OnlinePaymentError,
    build_liqpay_checkout,
    create_online_payment_transaction,
    handle_liqpay_callback,
)
from .otp import LoginCodeError, create_and_send_login_code, verify_login_code
from .sms import SmsSendError


def accessible_plots(user):
    if user.is_staff or user.is_superuser:
        return Plot.objects.all()
    return Plot.objects.filter(memberships__user=user).distinct()


def balance_for_plots(plots):
    confirmed_payments = Payment.objects.filter(
        plot__in=plots,
        status=Payment.Status.CONFIRMED,
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    active_accruals = Accrual.objects.filter(
        plot__in=plots,
        status=Accrual.Status.ACTIVE,
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    return confirmed_payments - active_accruals


def user_profile(user):
    try:
        return user.profile
    except ObjectDoesNotExist:
        return None


def display_name(user):
    if not user.is_authenticated:
        return ''
    profile = user_profile(user)
    if profile:
        return profile.full_name
    return user.get_full_name() or user.get_username()


def home_tasks(user, plots):
    if not user.is_authenticated:
        return []
    if not plots.exists():
        return []
    return [
        {
            'title': 'Передати показання лічильника',
            'text': 'Надішліть актуальні показання для своєї ділянки.',
            'url': reverse('submit_meter_reading'),
            'button': 'Передати',
        },
        {
            'title': 'Завантажити квитанцію',
            'text': 'Додайте фото квитанції після оплати.',
            'url': reverse('upload_receipt'),
            'button': 'Завантажити',
        },
        {
            'title': 'Перевірити заборгованість',
            'text': 'Подивіться баланс, нарахування та оплати.',
            'url': reverse('finance'),
            'button': 'Перевірити',
        },
    ]


def annotate_accruals_for_payment(accruals):
    accrual_list = list(accruals)
    accrual_ids = [accrual.id for accrual in accrual_list]
    paid_ids = set(
        OnlinePaymentTransaction.objects.filter(
            accrual_id__in=accrual_ids,
            status=OnlinePaymentTransaction.Status.SUCCESS,
        ).values_list('accrual_id', flat=True)
    )
    for accrual in accrual_list:
        accrual.is_online_paid = accrual.id in paid_ids
        accrual.can_pay_online = (
            accrual.status == Accrual.Status.ACTIVE and not accrual.is_online_paid
        )
    return accrual_list


def home(request):
    plots = accessible_plots(request.user) if request.user.is_authenticated else Plot.objects.none()
    critical_announcements = Announcement.objects.filter(
        is_published=True,
        kind=Announcement.Kind.CRITICAL,
    )[:3]
    village_news = Announcement.objects.filter(
        is_published=True,
        kind=Announcement.Kind.NEWS,
    )[:6]

    context = {
        'phone_form': PhoneLoginForm(),
        'plots': plots,
        'profile_name': display_name(request.user),
        'critical_announcements': critical_announcements,
        'village_news': village_news,
        'tasks': home_tasks(request.user, plots),
    }
    return render(request, 'core/home.html', context)


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = PhoneLoginForm(request.POST)
        if form.is_valid():
            try:
                login_code = create_and_send_login_code(form.cleaned_data['phone'])
            except (LoginCodeError, SmsSendError) as exc:
                form.add_error(None, str(exc))
            else:
                request.session['login_code_id'] = login_code.id
                request.session['login_phone'] = login_code.phone
                messages.success(request, 'Ми надіслали одноразовий код на ваш телефон.')
                return redirect('verify_login_code')
    else:
        form = PhoneLoginForm()

    return render(request, 'registration/login.html', {'form': form})


def verify_login_code_view(request):
    login_code_id = request.session.get('login_code_id')
    phone = request.session.get('login_phone')
    if not login_code_id:
        messages.error(request, 'Спочатку введіть номер телефону.')
        return redirect('login')

    if request.method == 'POST':
        form = LoginCodeForm(request.POST)
        if form.is_valid():
            try:
                user = verify_login_code(login_code_id, form.cleaned_data['code'])
            except LoginCodeError as exc:
                form.add_error(None, str(exc))
            else:
                request.session.pop('login_code_id', None)
                request.session.pop('login_phone', None)
                login(request, user)
                return redirect('dashboard')
    else:
        form = LoginCodeForm()

    return render(request, 'registration/verify_code.html', {'form': form, 'phone': phone})


def logout_view(request):
    logout(request)
    return redirect('home')


@login_required
def dashboard(request):
    plots = accessible_plots(request.user)
    context = {
        'plots': plots,
        'balance': balance_for_plots(plots),
        'latest_accruals': annotate_accruals_for_payment(Accrual.objects.filter(plot__in=plots)[:5]),
        'latest_payments': Payment.objects.filter(plot__in=plots)[:5],
        'profile_name': display_name(request.user),
    }
    return render(request, 'core/dashboard.html', context)


@login_required
def plot_detail(request, pk):
    plot = get_object_or_404(accessible_plots(request.user), pk=pk)
    context = {
        'plot': plot,
        'accruals': plot.accruals.all(),
        'payments': plot.payments.all(),
        'meters': plot.meters.all(),
    }
    return render(request, 'core/plot_detail.html', context)


@login_required
def finance(request):
    plots = accessible_plots(request.user)
    selected_plot = request.GET.get('plot')
    filtered_plots = plots
    if selected_plot:
        filtered_plots = plots.filter(pk=selected_plot)

    context = {
        'plots': plots,
        'selected_plot': selected_plot,
        'balance': balance_for_plots(plots),
        'accruals': annotate_accruals_for_payment(Accrual.objects.filter(plot__in=filtered_plots)),
        'payments': Payment.objects.filter(plot__in=filtered_plots),
    }
    return render(request, 'core/finance.html', context)


@login_required
@require_POST
def start_online_payment(request, accrual_id):
    accrual = get_object_or_404(Accrual.objects.select_related('plot'), pk=accrual_id)
    if not accessible_plots(request.user).filter(pk=accrual.plot_id).exists():
        return HttpResponseBadRequest('Нарахування недоступне.')
    try:
        transaction_obj = create_online_payment_transaction(request.user, accrual)
        checkout = build_liqpay_checkout(transaction_obj, request)
    except OnlinePaymentError as exc:
        messages.error(request, str(exc))
        return redirect('finance')
    return render(
        request,
        'core/online_payment_checkout.html',
        {'transaction': transaction_obj, 'checkout': checkout},
    )


@login_required
def online_payment_status(request, order_id):
    transaction_obj = get_object_or_404(
        OnlinePaymentTransaction.objects.select_related('plot', 'accrual'),
        order_id=order_id,
    )
    if transaction_obj.user_id != request.user.id and not request.user.is_staff:
        return HttpResponseBadRequest('Платіж недоступний.')
    return render(request, 'core/online_payment_status.html', {'transaction': transaction_obj})


@csrf_exempt
@require_POST
def liqpay_callback(request):
    data = request.POST.get('data', '')
    signature = request.POST.get('signature', '')
    if not data or not signature:
        return HttpResponseBadRequest('missing data')
    try:
        handle_liqpay_callback(data, signature)
    except (OnlinePaymentError, OnlinePaymentTransaction.DoesNotExist) as exc:
        return HttpResponseBadRequest(str(exc))
    return HttpResponse('ok')


@login_required
def submit_meter_reading(request):
    plots = accessible_plots(request.user)
    if request.method == 'POST':
        form = MeterReadingForm(request.POST, request.FILES, plots=plots)
        if form.is_valid():
            reading = form.save(commit=False)
            reading.user = request.user
            reading.save()
            messages.success(request, 'Показання надіслано на перевірку.')
            return redirect('dashboard')
    else:
        form = MeterReadingForm(plots=plots)
    return render(request, 'core/submit_meter_reading.html', {'form': form})


@login_required
def upload_receipt(request):
    plots = accessible_plots(request.user)
    if request.method == 'POST':
        form = PaymentReceiptForm(request.POST, request.FILES, plots=plots)
        if form.is_valid():
            receipt = form.save(commit=False)
            receipt.user = request.user
            receipt.save()
            messages.success(request, 'Квитанцію надіслано на перевірку.')
            return redirect('dashboard')
    else:
        form = PaymentReceiptForm(plots=plots)
    return render(request, 'core/upload_receipt.html', {'form': form})


def announcements(request):
    items = Announcement.objects.filter(
        is_published=True,
        kind__in=[Announcement.Kind.CRITICAL, Announcement.Kind.ANNOUNCEMENT],
    )
    return render(request, 'core/announcements.html', {'announcements': items})


def news(request):
    items = Announcement.objects.filter(is_published=True, kind=Announcement.Kind.NEWS)
    return render(request, 'core/news.html', {'news_items': items})
