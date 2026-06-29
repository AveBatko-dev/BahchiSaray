from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import Group, User
from django.core.exceptions import ObjectDoesNotExist

from .models import OnlinePaymentTransaction, Plot, PlotMembership, UserProfile


admin.site.site_header = 'Адмінка СТ «Економіст»'
admin.site.site_title = 'СТ «Економіст»'
admin.site.index_title = 'Основні дані'

User._meta.verbose_name = 'користувач'
User._meta.verbose_name_plural = 'користувачі'

try:
    admin.site.unregister(Group)
except admin.sites.NotRegistered:
    pass

try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    extra = 0
    fields = ('last_name', 'first_name', 'middle_name', 'phone')


class PlotMembershipInline(admin.TabularInline):
    model = PlotMembership
    extra = 1


def profile_for(user):
    try:
        return user.profile
    except ObjectDoesNotExist:
        return None


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    inlines = (UserProfileInline, PlotMembershipInline)
    list_display = (
        'profile_last_name',
        'profile_first_name',
        'profile_middle_name',
        'profile_phone',
        'linked_plots',
        'is_staff',
    )
    search_fields = (
        'profile__last_name',
        'profile__first_name',
        'profile__middle_name',
        'profile__phone',
        'username',
    )

    @admin.display(description='прізвище', ordering='profile__last_name')
    def profile_last_name(self, obj):
        profile = profile_for(obj)
        return profile.last_name if profile else ''

    @admin.display(description='імʼя', ordering='profile__first_name')
    def profile_first_name(self, obj):
        profile = profile_for(obj)
        return profile.first_name if profile else ''

    @admin.display(description='по батькові', ordering='profile__middle_name')
    def profile_middle_name(self, obj):
        profile = profile_for(obj)
        return profile.middle_name if profile else ''

    @admin.display(description='номер телефону', ordering='profile__phone')
    def profile_phone(self, obj):
        profile = profile_for(obj)
        return profile.phone if profile else ''

    @admin.display(description='привʼязані ділянки')
    def linked_plots(self, obj):
        plots = Plot.objects.filter(memberships__user=obj).order_by('number')
        return ', '.join(plot.number for plot in plots) or '-'


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    fields = ('last_name', 'first_name', 'middle_name', 'phone')
    list_display = ('last_name', 'first_name', 'middle_name', 'phone', 'linked_plots')
    search_fields = ('last_name', 'first_name', 'middle_name', 'phone')

    @admin.display(description='привʼязані ділянки')
    def linked_plots(self, obj):
        return ', '.join(plot.number for plot in obj.linked_plots.order_by('number')) or '-'


@admin.register(Plot)
class PlotAdmin(admin.ModelAdmin):
    list_display = ('number', 'area', 'owner_name')
    search_fields = ('number', 'owner_name', 'address')


@admin.register(PlotMembership)
class PlotMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'plot', 'role', 'created_at')
    list_filter = ('role',)
    search_fields = (
        'user__profile__last_name',
        'user__profile__first_name',
        'user__profile__middle_name',
        'user__profile__phone',
        'plot__number',
    )


@admin.register(OnlinePaymentTransaction)
class OnlinePaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ('user', 'plot', 'amount', 'status', 'provider', 'created_at')
    list_filter = ('status', 'provider', 'created_at')
    search_fields = (
        'order_id',
        'provider_payment_id',
        'user__profile__last_name',
        'user__profile__first_name',
        'user__profile__phone',
        'plot__number',
    )
    readonly_fields = (
        'user',
        'plot',
        'accrual',
        'payment',
        'amount',
        'provider',
        'order_id',
        'provider_payment_id',
        'status',
        'created_at',
        'paid_at',
        'provider_status',
        'provider_payload',
    )
