from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.utils import timezone


class UserProfile(models.Model):
    class AccessStatus(models.TextChoices):
        PENDING = 'pending', 'Очікує підтвердження'
        APPROVED = 'approved', 'Підтверджено'
        REJECTED = 'rejected', 'Відхилено'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
        verbose_name='користувач',
    )
    full_name = models.CharField('ПІБ', max_length=255)
    phone = models.CharField('телефон', max_length=30, blank=True)
    avatar = models.FileField('аватар', upload_to='avatars/', blank=True)
    access_status = models.CharField(
        'статус доступу',
        max_length=20,
        choices=AccessStatus.choices,
        default=AccessStatus.PENDING,
    )
    created_at = models.DateTimeField('створено', auto_now_add=True)

    class Meta:
        verbose_name = 'профіль користувача'
        verbose_name_plural = 'профілі користувачів'

    def __str__(self):
        return self.full_name or self.user.get_username()


class Plot(models.Model):
    number = models.CharField('номер ділянки', max_length=30, unique=True)
    area = models.DecimalField('площа, соток', max_digits=8, decimal_places=2)
    owner_name = models.CharField('власник', max_length=255, blank=True)
    address = models.CharField('адреса або орієнтир', max_length=255, blank=True)
    note = models.TextField('примітка', blank=True)

    class Meta:
        ordering = ['number']
        verbose_name = 'ділянка'
        verbose_name_plural = 'ділянки'

    def __str__(self):
        return f'Ділянка {self.number}'

    @property
    def active_accruals_total(self):
        total = self.accruals.filter(status=Accrual.Status.ACTIVE).aggregate(
            total=Sum('amount')
        )['total']
        return total or Decimal('0.00')

    @property
    def confirmed_payments_total(self):
        total = self.payments.filter(status=Payment.Status.CONFIRMED).aggregate(
            total=Sum('amount')
        )['total']
        return total or Decimal('0.00')

    @property
    def balance(self):
        return self.confirmed_payments_total - self.active_accruals_total

    @property
    def balance_state(self):
        if self.balance < 0:
            return 'Заборгованість'
        if self.balance > 0:
            return 'Переплата'
        return 'Усе сплачено'

    @property
    def debt_amount(self):
        return abs(self.balance) if self.balance < 0 else Decimal('0.00')

    @property
    def overpayment_amount(self):
        return self.balance if self.balance > 0 else Decimal('0.00')


class PlotMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = 'owner', 'Власник'
        FAMILY = 'family', 'Член родини'
        MANAGER = 'manager', 'Представник'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='plot_memberships',
        verbose_name='користувач',
    )
    plot = models.ForeignKey(
        Plot,
        on_delete=models.CASCADE,
        related_name='memberships',
        verbose_name='ділянка',
    )
    role = models.CharField('роль', max_length=20, choices=Role.choices, default=Role.OWNER)
    created_at = models.DateTimeField('додано', auto_now_add=True)

    class Meta:
        unique_together = ('user', 'plot')
        verbose_name = 'звʼязок користувача з ділянкою'
        verbose_name_plural = 'звʼязки користувачів з ділянками'

    def __str__(self):
        return f'{self.user} - {self.plot}'


class Accrual(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Активне'
        CANCELED = 'canceled', 'Скасоване'

    plot = models.ForeignKey(
        Plot,
        on_delete=models.CASCADE,
        related_name='accruals',
        verbose_name='ділянка',
    )
    title = models.CharField('призначення', max_length=255)
    amount = models.DecimalField('сума', max_digits=12, decimal_places=2)
    period = models.CharField('період', max_length=100, blank=True)
    charged_at = models.DateField('дата нарахування', default=timezone.localdate)
    status = models.CharField('статус', max_length=20, choices=Status.choices, default=Status.ACTIVE)
    comment = models.TextField('коментар', blank=True)
    created_at = models.DateTimeField('створено', auto_now_add=True)

    class Meta:
        ordering = ['-charged_at', '-id']
        verbose_name = 'нарахування'
        verbose_name_plural = 'нарахування'

    def __str__(self):
        return f'{self.plot}: {self.title} - {self.amount}'


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'На перевірці'
        CONFIRMED = 'confirmed', 'Підтверджено'
        REJECTED = 'rejected', 'Відхилено'

    class Method(models.TextChoices):
        CASH = 'cash', 'Готівка'
        CARD = 'card', 'Картка'
        BANK = 'bank', 'Банк'
        OTHER = 'other', 'Інше'

    plot = models.ForeignKey(
        Plot,
        on_delete=models.CASCADE,
        related_name='payments',
        verbose_name='ділянка',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='payments',
        verbose_name='користувач',
        null=True,
        blank=True,
    )
    amount = models.DecimalField('сума', max_digits=12, decimal_places=2)
    paid_at = models.DateField('дата оплати', default=timezone.localdate)
    method = models.CharField('спосіб оплати', max_length=20, choices=Method.choices, default=Method.BANK)
    status = models.CharField('статус', max_length=20, choices=Status.choices, default=Status.PENDING)
    comment = models.TextField('коментар', blank=True)
    created_at = models.DateTimeField('створено', auto_now_add=True)

    class Meta:
        ordering = ['-paid_at', '-id']
        verbose_name = 'оплата'
        verbose_name_plural = 'оплати'

    def __str__(self):
        return f'{self.plot}: {self.amount} ({self.get_status_display()})'


class Meter(models.Model):
    class Kind(models.TextChoices):
        ELECTRICITY = 'electricity', 'Електрика'
        WATER = 'water', 'Вода'
        GAS = 'gas', 'Газ'
        OTHER = 'other', 'Інше'

    plot = models.ForeignKey(
        Plot,
        on_delete=models.CASCADE,
        related_name='meters',
        verbose_name='ділянка',
    )
    kind = models.CharField('тип', max_length=30, choices=Kind.choices, default=Kind.ELECTRICITY)
    number = models.CharField('номер лічильника', max_length=100)
    unit = models.CharField('одиниця вимірювання', max_length=30, default='кВт*год')
    is_active = models.BooleanField('активний', default=True)

    class Meta:
        ordering = ['plot__number', 'kind', 'number']
        verbose_name = 'лічильник'
        verbose_name_plural = 'лічильники'

    def __str__(self):
        return f'{self.get_kind_display()} {self.number} ({self.plot})'


class MeterReading(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'На перевірці'
        APPROVED = 'approved', 'Підтверджено'
        REJECTED = 'rejected', 'Відхилено'

    meter = models.ForeignKey(
        Meter,
        on_delete=models.CASCADE,
        related_name='readings',
        verbose_name='лічильник',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='meter_readings',
        verbose_name='користувач',
        null=True,
        blank=True,
    )
    value = models.DecimalField('поточне показання', max_digits=12, decimal_places=2)
    photo = models.FileField('фото лічильника', upload_to='meter_readings/', blank=True)
    submitted_at = models.DateTimeField('передано', auto_now_add=True)
    status = models.CharField('статус', max_length=20, choices=Status.choices, default=Status.PENDING)
    comment = models.TextField('коментар адміністратора', blank=True)

    class Meta:
        ordering = ['-submitted_at']
        verbose_name = 'показання лічильника'
        verbose_name_plural = 'показання лічильників'

    def __str__(self):
        return f'{self.meter}: {self.value}'


class PaymentReceipt(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'На перевірці'
        CONFIRMED = 'confirmed', 'Підтверджено'
        REJECTED = 'rejected', 'Відхилено'

    plot = models.ForeignKey(
        Plot,
        on_delete=models.CASCADE,
        related_name='receipts',
        verbose_name='ділянка',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='payment_receipts',
        verbose_name='користувач',
        null=True,
        blank=True,
    )
    amount = models.DecimalField('сума оплати', max_digits=12, decimal_places=2)
    paid_at = models.DateField('дата оплати', default=timezone.localdate)
    method = models.CharField('спосіб оплати', max_length=20, choices=Payment.Method.choices, default=Payment.Method.BANK)
    photo = models.FileField('фото квитанції', upload_to='payment_receipts/', blank=True)
    comment = models.TextField('коментар', blank=True)
    status = models.CharField('статус', max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField('завантажено', auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'квитанція оплати'
        verbose_name_plural = 'квитанції оплат'

    def __str__(self):
        return f'{self.plot}: квитанція {self.amount}'


class Announcement(models.Model):
    class Kind(models.TextChoices):
        CRITICAL = 'critical', 'Важливе оголошення'
        ANNOUNCEMENT = 'announcement', 'Оголошення'
        NEWS = 'news', 'Новина селища'

    class Topic(models.TextChoices):
        INFRASTRUCTURE = 'infrastructure', 'Інфраструктура'
        SHOPS = 'shops', 'Магазини'
        POST = 'post', 'Пошта'
        ROADS = 'roads', 'Дороги'
        WATER = 'water', 'Вода'
        ELECTRICITY = 'electricity', 'Електрика'
        EVENTS = 'events', 'Події селища'
        GENERAL = 'general', 'Загальні повідомлення'

    title = models.CharField('заголовок', max_length=255)
    text = models.TextField('текст')
    kind = models.CharField('тип', max_length=30, choices=Kind.choices, default=Kind.ANNOUNCEMENT)
    topic = models.CharField('тема новини', max_length=30, choices=Topic.choices, default=Topic.GENERAL)
    published_at = models.DateField('дата публікації', default=timezone.localdate)
    is_published = models.BooleanField('опубліковано', default=True)
    created_at = models.DateTimeField('створено', auto_now_add=True)

    class Meta:
        ordering = ['-published_at', '-id']
        verbose_name = 'оголошення або новина'
        verbose_name_plural = 'оголошення та новини'

    def __str__(self):
        return self.title
