from django.urls import path

from . import views


urlpatterns = [
    path('', views.home, name='home'),
    path('cabinet/', views.dashboard, name='dashboard'),
    path('plots/<int:pk>/', views.plot_detail, name='plot_detail'),
    path('finance/', views.finance, name='finance'),
    path('meters/submit/', views.submit_meter_reading, name='submit_meter_reading'),
    path('receipts/upload/', views.upload_receipt, name='upload_receipt'),
    path('announcements/', views.announcements, name='announcements'),
    path('news/', views.news, name='news'),
]
