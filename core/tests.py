from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Accrual, Payment, Plot, PlotMembership, UserProfile


class BalanceTests(TestCase):
    def test_plot_balance_uses_confirmed_payments_and_active_accruals(self):
        plot = Plot.objects.create(number='10', area=Decimal('6.00'), owner_name='Іваненко')
        Accrual.objects.create(plot=plot, title='Внесок', amount=Decimal('1000.00'))
        Accrual.objects.create(
            plot=plot,
            title='Скасований внесок',
            amount=Decimal('500.00'),
            status=Accrual.Status.CANCELED,
        )
        Payment.objects.create(
            plot=plot,
            amount=Decimal('700.00'),
            status=Payment.Status.CONFIRMED,
        )
        Payment.objects.create(
            plot=plot,
            amount=Decimal('300.00'),
            status=Payment.Status.PENDING,
        )

        self.assertEqual(plot.balance, Decimal('-300.00'))
        self.assertEqual(plot.balance_state, 'Заборгованість')


class AccessTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='owner@example.com', email='owner@example.com', password='pass12345')
        self.other = User.objects.create_user(username='other@example.com', email='other@example.com', password='pass12345')
        UserProfile.objects.create(user=self.user, full_name='Олена Петренко', phone='+380501111111')
        UserProfile.objects.create(user=self.other, full_name='Іван Сидоренко', phone='+380502222222')
        self.plot = Plot.objects.create(number='21', area=Decimal('8.50'), owner_name='Петренко')
        self.other_plot = Plot.objects.create(number='22', area=Decimal('7.00'), owner_name='Сидоренко')
        PlotMembership.objects.create(user=self.user, plot=self.plot)
        PlotMembership.objects.create(user=self.other, plot=self.other_plot)

    def test_public_pages_open(self):
        self.assertEqual(self.client.get(reverse('home')).status_code, 200)
        self.assertEqual(self.client.get(reverse('announcements')).status_code, 200)
        self.assertEqual(self.client.get(reverse('news')).status_code, 200)

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_user_can_open_only_own_plot(self):
        self.client.login(username='owner@example.com', password='pass12345')

        own_response = self.client.get(reverse('plot_detail', args=[self.plot.pk]))
        other_response = self.client.get(reverse('plot_detail', args=[self.other_plot.pk]))

        self.assertEqual(own_response.status_code, 200)
        self.assertEqual(other_response.status_code, 404)

    def test_home_login_accepts_email(self):
        response = self.client.post(
            reverse('home'),
            {'action': 'login', 'login': 'owner@example.com', 'password': 'pass12345'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('home'))
