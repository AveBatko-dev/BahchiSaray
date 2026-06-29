from django.urls import path

from . import views


urlpatterns = [
    path('', views.home, name='home'),
    path('cabinet/', views.dashboard, name='dashboard'),
    path('plots/<int:pk>/', views.plot_detail, name='plot_detail'),
    path('finance/', views.finance, name='finance'),
    path('payments/accruals/<int:accrual_id>/start/', views.start_online_payment, name='start_online_payment'),
    path('payments/<str:order_id>/', views.online_payment_status, name='online_payment_status'),
    path('payments/liqpay/callback/', views.liqpay_callback, name='liqpay_callback'),
    path('meters/submit/', views.submit_meter_reading, name='submit_meter_reading'),
    path('receipts/upload/', views.upload_receipt, name='upload_receipt'),
    path('announcements/', views.announcements, name='announcements'),
    path('news/', views.news, name='news'),
]
