from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .forms import LoginCodeForm, MeterReadingForm, PaymentReceiptForm, PhoneLoginForm
from .models import Accrual, Announcement, Payment, Plot
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
        'latest_accruals': Accrual.objects.filter(plot__in=plots)[:5],
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
        'accruals': Accrual.objects.filter(plot__in=filtered_plots),
        'payments': Payment.objects.filter(plot__in=filtered_plots),
    }
    return render(request, 'core/finance.html', context)


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
