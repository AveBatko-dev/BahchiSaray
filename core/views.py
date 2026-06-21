from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .forms import (
    MeterReadingForm,
    PaymentReceiptForm,
    UserLoginForm,
    UserRegistrationForm,
)
from .models import Accrual, Announcement, Payment, Plot, UserProfile


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


def display_name(user):
    if not user.is_authenticated:
        return ''
    profile = user_profile(user)
    if profile and profile.full_name:
        return profile.full_name
    return user.get_full_name() or user.get_username()


def user_profile(user):
    try:
        return user.profile
    except ObjectDoesNotExist:
        return None


def authenticate_by_contact(identifier, password):
    User = get_user_model()
    identifier = identifier.strip()
    user = (
        User.objects.filter(email__iexact=identifier).first()
        or User.objects.filter(profile__phone=identifier).first()
        or User.objects.filter(username__iexact=identifier).first()
    )
    if user and user.check_password(password):
        return user
    return None


def register_user(form):
    User = get_user_model()
    email = form.cleaned_data['email']
    full_name = form.cleaned_data['full_name']
    user = User.objects.create_user(
        username=email,
        email=email,
        password=form.cleaned_data['password'],
        first_name=full_name[:150],
    )
    UserProfile.objects.create(
        user=user,
        full_name=full_name,
        phone=form.cleaned_data['phone'],
    )
    return user


def home_tasks(user, plots, balance):
    if not user.is_authenticated:
        return []
    if not plots.exists():
        return [
            {
                'title': 'Очікуйте підтвердження доступу',
                'text': 'Адміністратор має привʼязати ваш акаунт до ділянки.',
                'url': reverse('announcements'),
                'button': 'Переглянути оголошення',
            }
        ]

    tasks = [
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
    if balance >= 0:
        return tasks
    return tasks


def handle_home_auth(request):
    login_form = UserLoginForm()
    registration_form = UserRegistrationForm()

    if request.method != 'POST':
        return login_form, registration_form

    action = request.POST.get('action')
    if action == 'login':
        login_form = UserLoginForm(request.POST)
        if login_form.is_valid():
            user = authenticate_by_contact(
                login_form.cleaned_data['login'],
                login_form.cleaned_data['password'],
            )
            if user:
                login(request, user)
                messages.success(request, 'Ви увійшли до акаунта.')
                return None, None
            login_form.add_error(None, 'Перевірте телефон, email або пароль.')

    if action == 'register':
        registration_form = UserRegistrationForm(request.POST)
        if registration_form.is_valid():
            user = register_user(registration_form)
            login(request, user)
            messages.success(
                request,
                'Акаунт створено. Доступ до ділянок зʼявиться після підтвердження адміністратором.',
            )
            return None, None

    return login_form, registration_form


def home(request):
    auth_forms = handle_home_auth(request)
    if auth_forms == (None, None):
        return redirect('home')

    plots = accessible_plots(request.user) if request.user.is_authenticated else Plot.objects.none()
    balance = balance_for_plots(plots) if request.user.is_authenticated else Decimal('0.00')
    critical_announcements = Announcement.objects.filter(
        is_published=True,
        kind=Announcement.Kind.CRITICAL,
    )[:3]
    village_news = Announcement.objects.filter(
        is_published=True,
        kind=Announcement.Kind.NEWS,
    )[:6]

    context = {
        'login_form': auth_forms[0],
        'registration_form': auth_forms[1],
        'plots': plots,
        'balance': balance,
        'profile_name': display_name(request.user),
        'profile': user_profile(request.user) if request.user.is_authenticated else None,
        'critical_announcements': critical_announcements,
        'village_news': village_news,
        'tasks': home_tasks(request.user, plots, balance),
    }
    return render(request, 'core/home.html', context)


def login_view(request):
    if request.method == 'POST':
        form = UserLoginForm(request.POST)
        if form.is_valid():
            user = authenticate_by_contact(form.cleaned_data['login'], form.cleaned_data['password'])
            if user:
                login(request, user)
                return redirect(request.GET.get('next') or 'dashboard')
            form.add_error(None, 'Перевірте телефон, email або пароль.')
    else:
        form = UserLoginForm()
    return render(request, 'registration/login.html', {'form': form})


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
