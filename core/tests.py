from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Accrual, LoginCode, Payment, Plot, PlotMembership, UserProfile


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


@override_settings(
    LOGIN_CODE_RESEND_COOLDOWN_SECONDS=0,
    LOGIN_CODE_DAILY_LIMIT=10,
    LOGIN_CODE_MAX_ATTEMPTS=3,
    LOGIN_CODE_TTL_MINUTES=5,
)
class AccessAndLoginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='owner')
        self.user.set_unusable_password()
        self.user.save()
        self.other = User.objects.create_user(username='other')
        self.other.set_unusable_password()
        self.other.save()
        UserProfile.objects.create(
            user=self.user,
            last_name='Петренко',
            first_name='Олена',
            middle_name='Іванівна',
            phone='+380501111111',
        )
        UserProfile.objects.create(
            user=self.other,
            last_name='Сидоренко',
            first_name='Іван',
            middle_name='Петрович',
            phone='+380502222222',
        )
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

    def test_phone_login_sends_sms_code(self):
        sent_messages = []

        def fake_send_sms(phone, message):
            sent_messages.append((phone, message))

        with patch('core.otp.send_sms', side_effect=fake_send_sms):
            response = self.client.post(reverse('login'), {'phone': '+38 (050) 111-11-11'})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('verify_login_code'))
        self.assertEqual(sent_messages[0][0], '+380501111111')
        login_code = LoginCode.objects.get(phone='+380501111111')
        self.assertNotIn(sent_messages[0][1].split()[-1], login_code.code_hash)
        self.assertFalse(login_code.used)

    def test_code_verification_logs_user_into_dashboard_and_logout_works(self):
        captured = {}

        def fake_send_sms(phone, message):
            captured['code'] = message.split()[-1]

        with patch('core.otp.send_sms', side_effect=fake_send_sms):
            self.client.post(reverse('login'), {'phone': '+380501111111'})

        response = self.client.post(reverse('verify_login_code'), {'code': captured['code']})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('dashboard'))
        self.assertTrue(LoginCode.objects.get(phone='+380501111111').used)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)

        logout_response = self.client.post(reverse('logout'))
        self.assertEqual(logout_response.status_code, 302)
        self.assertEqual(logout_response.url, reverse('home'))
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 302)

    def test_code_attempt_limit_blocks_repeated_wrong_codes(self):
        with patch('core.otp.send_sms'):
            self.client.post(reverse('login'), {'phone': '+380501111111'})

        for _ in range(3):
            self.client.post(reverse('verify_login_code'), {'code': '000000'})

        login_code = LoginCode.objects.get(phone='+380501111111')
        self.assertEqual(login_code.attempts, 3)
        self.assertFalse(login_code.used)

    def test_user_can_open_only_own_plot(self):
        self.client.force_login(self.user)

        own_response = self.client.get(reverse('plot_detail', args=[self.plot.pk]))
        other_response = self.client.get(reverse('plot_detail', args=[self.other_plot.pk]))

        self.assertEqual(own_response.status_code, 200)
        self.assertEqual(other_response.status_code, 404)

    def test_admin_created_profile_creates_user_and_can_be_linked_to_plot(self):
        profile = UserProfile.objects.create(
            last_name='Коваленко',
            first_name='Марія',
            middle_name='Олександрівна',
            phone='+380503333333',
        )
        plot = Plot.objects.create(number='31', area=Decimal('6.20'), owner_name='Коваленко')
        PlotMembership.objects.create(user=profile.user, plot=plot)

        self.assertIsNotNone(profile.user)
        self.assertTrue(profile.linked_plots.filter(pk=plot.pk).exists())

    def test_admin_index_shows_only_simplified_models(self):
        admin_user = User.objects.create_superuser(username='admin', password='admin12345')
        self.client.force_login(admin_user)

        response = self.client.get(reverse('admin:index'))
        content = response.content.decode('utf-8')

        self.assertEqual(response.status_code, 200)
        self.assertIn('/admin/auth/user/', content)
        self.assertIn('/admin/core/userprofile/', content)
        self.assertIn('/admin/core/plot/', content)
        self.assertIn('/admin/core/plotmembership/', content)
        self.assertNotIn('/admin/core/payment/', content)
        self.assertNotIn('/admin/core/accrual/', content)
        self.assertNotIn('/admin/core/logincode/', content)
