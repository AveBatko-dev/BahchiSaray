from django.contrib import admin

from .models import (
    Accrual,
    Announcement,
    Meter,
    MeterReading,
    Payment,
    PaymentReceipt,
    Plot,
    PlotMembership,
    UserProfile,
)


admin.site.site_header = 'Адмінка Бахча'
admin.site.site_title = 'Бахча'
admin.site.index_title = 'Керування даними'


class PlotMembershipInline(admin.TabularInline):
    model = PlotMembership
    extra = 1


class MeterInline(admin.TabularInline):
    model = Meter
    extra = 1


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'phone', 'user', 'access_status', 'created_at')
    list_filter = ('access_status',)
    search_fields = ('full_name', 'phone', 'user__email', 'user__username')


@admin.register(Plot)
class PlotAdmin(admin.ModelAdmin):
    list_display = ('number', 'area', 'owner_name', 'balance', 'balance_state')
    search_fields = ('number', 'owner_name', 'address')
    inlines = (PlotMembershipInline, MeterInline)


@admin.register(PlotMembership)
class PlotMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'plot', 'role', 'created_at')
    list_filter = ('role',)
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'plot__number')


@admin.register(Accrual)
class AccrualAdmin(admin.ModelAdmin):
    list_display = ('plot', 'title', 'amount', 'charged_at', 'status')
    list_filter = ('status', 'charged_at')
    search_fields = ('plot__number', 'title', 'period')


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('plot', 'user', 'amount', 'paid_at', 'method', 'status')
    list_filter = ('status', 'method', 'paid_at')
    search_fields = ('plot__number', 'user__username', 'comment')


@admin.register(Meter)
class MeterAdmin(admin.ModelAdmin):
    list_display = ('plot', 'kind', 'number', 'unit', 'is_active')
    list_filter = ('kind', 'is_active')
    search_fields = ('plot__number', 'number')


@admin.register(MeterReading)
class MeterReadingAdmin(admin.ModelAdmin):
    list_display = ('meter', 'user', 'value', 'submitted_at', 'status')
    list_filter = ('status', 'submitted_at')
    search_fields = ('meter__number', 'meter__plot__number', 'user__username')


@admin.register(PaymentReceipt)
class PaymentReceiptAdmin(admin.ModelAdmin):
    list_display = ('plot', 'user', 'amount', 'paid_at', 'method', 'status', 'created_at')
    list_filter = ('status', 'method', 'paid_at')
    search_fields = ('plot__number', 'user__username', 'comment')


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ('title', 'kind', 'topic', 'published_at', 'is_published')
    list_filter = ('kind', 'topic', 'is_published', 'published_at')
    search_fields = ('title', 'text')
