from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import (
    Accrual,
    LoginCode,
    MAX_RECEIPT_FILE_SIZE,
    MeterReading,
    OnlinePaymentTransaction,
    Payment,
    PaymentReceipt,
    Plot,
    PlotMembership,
    UserProfile,
    validate_meter_photo,
    validate_payment_receipt_file,
)
from .online_payments import build_liqpay_checkout, encode_liqpay_data, liqpay_signature


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


class UploadValidationTests(TestCase):
    def test_meter_photo_allows_only_supported_image_extensions(self):
        for filename in ['meter.jpg', 'meter.jpeg', 'meter.png', 'meter.webp']:
            validate_meter_photo(SimpleUploadedFile(filename, b'file'))

        with self.assertRaises(ValidationError):
            validate_meter_photo(SimpleUploadedFile('meter.pdf', b'file'))
        with self.assertRaises(ValidationError):
            validate_meter_photo(SimpleUploadedFile('meter.gif', b'file'))

    def test_receipt_allows_images_and_pdf_up_to_20_mb(self):
        for filename in ['receipt.jpg', 'receipt.jpeg', 'receipt.png', 'receipt.webp', 'receipt.pdf']:
            validate_payment_receipt_file(SimpleUploadedFile(filename, b'file'))

        with self.assertRaises(ValidationError):
            validate_payment_receipt_file(SimpleUploadedFile('receipt.docx', b'file'))

        oversized = SimpleUploadedFile('receipt.pdf', b'0' * (MAX_RECEIPT_FILE_SIZE + 1))
        with self.assertRaises(ValidationError):
            validate_payment_receipt_file(oversized)

    def test_file_validators_are_attached_to_models(self):
        meter_validators = MeterReading._meta.get_field('photo').validators
        receipt_validators = PaymentReceipt._meta.get_field('photo').validators

        self.assertIn(validate_meter_photo, meter_validators)
        self.assertIn(validate_payment_receipt_file, receipt_validators)


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
        self.assertIn('/admin/core/onlinepaymenttransaction/', content)
        self.assertNotIn('/admin/core/payment/', content)
        self.assertNotIn('/admin/core/accrual/', content)
        self.assertNotIn('/admin/core/logincode/', content)


@override_settings(
    LIQPAY_PUBLIC_KEY='public',
    LIQPAY_PRIVATE_KEY='private',
    SITE_URL='https://example.test',
)
class OnlinePaymentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='owner')
        self.user.set_unusable_password()
        self.user.save()
        UserProfile.objects.create(
            user=self.user,
            last_name='Петренко',
            first_name='Олена',
            phone='+380501111111',
        )
        self.plot = Plot.objects.create(number='21', area=Decimal('8.50'), owner_name='Петренко')
        PlotMembership.objects.create(user=self.user, plot=self.plot)
        self.accrual = Accrual.objects.create(
            plot=self.plot,
            title='Цільовий внесок',
            amount=Decimal('450.00'),
        )

    def liqpay_callback_payload(self, transaction_obj, **overrides):
        payload = {
            'order_id': transaction_obj.order_id,
            'amount': str(transaction_obj.amount),
            'currency': 'UAH',
            'status': 'success',
            'payment_id': 'liqpay-123',
        }
        payload.update(overrides)
        data = encode_liqpay_data(payload)
        return {'data': data, 'signature': liqpay_signature(data)}

    def test_unpaid_accrual_has_pay_button_in_dashboard_and_finance(self):
        self.client.force_login(self.user)
        pay_url = reverse('start_online_payment', args=[self.accrual.id])

        dashboard = self.client.get(reverse('dashboard'))
        finance = self.client.get(reverse('finance'))

        self.assertContains(dashboard, pay_url)
        self.assertContains(finance, pay_url)

    def test_start_online_payment_creates_transaction_and_checkout_form(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse('start_online_payment', args=[self.accrual.id]))

        self.assertEqual(response.status_code, 200)
        transaction_obj = OnlinePaymentTransaction.objects.get(accrual=self.accrual)
        self.assertEqual(transaction_obj.amount, self.accrual.amount)
        self.assertEqual(transaction_obj.provider, OnlinePaymentTransaction.Provider.LIQPAY)
        self.assertContains(response, 'www.liqpay.ua/api/3/checkout')
        checkout = build_liqpay_checkout(transaction_obj, response.wsgi_request)
        self.assertContains(response, checkout['data'])
        self.assertContains(response, checkout['signature'])

    def test_repeated_start_reuses_pending_transaction(self):
        self.client.force_login(self.user)

        self.client.post(reverse('start_online_payment', args=[self.accrual.id]))
        self.client.post(reverse('start_online_payment', args=[self.accrual.id]))

        self.assertEqual(OnlinePaymentTransaction.objects.filter(accrual=self.accrual).count(), 1)

    def test_successful_callback_creates_confirmed_payment_once(self):
        self.client.force_login(self.user)
        self.client.post(reverse('start_online_payment', args=[self.accrual.id]))
        transaction_obj = OnlinePaymentTransaction.objects.get(accrual=self.accrual)
        callback_payload = self.liqpay_callback_payload(transaction_obj)

        first_response = self.client.post(reverse('liqpay_callback'), callback_payload)
        second_response = self.client.post(reverse('liqpay_callback'), callback_payload)

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        transaction_obj.refresh_from_db()
        self.assertEqual(transaction_obj.status, OnlinePaymentTransaction.Status.SUCCESS)
        self.assertIsNotNone(transaction_obj.paid_at)
        self.assertEqual(Payment.objects.count(), 1)
        payment = Payment.objects.get()
        self.assertEqual(payment.status, Payment.Status.CONFIRMED)
        self.assertEqual(payment.method, Payment.Method.ONLINE)
        self.assertEqual(payment.amount, self.accrual.amount)

    def test_second_success_transaction_for_same_accrual_does_not_create_second_payment(self):
        first_transaction = OnlinePaymentTransaction.objects.create(
            user=self.user,
            plot=self.plot,
            accrual=self.accrual,
            amount=self.accrual.amount,
            provider=OnlinePaymentTransaction.Provider.LIQPAY,
            order_id='first-order',
            status=OnlinePaymentTransaction.Status.PENDING,
        )
        second_transaction = OnlinePaymentTransaction.objects.create(
            user=self.user,
            plot=self.plot,
            accrual=self.accrual,
            amount=self.accrual.amount,
            provider=OnlinePaymentTransaction.Provider.LIQPAY,
            order_id='second-order',
            status=OnlinePaymentTransaction.Status.PENDING,
        )

        first_response = self.client.post(
            reverse('liqpay_callback'),
            self.liqpay_callback_payload(first_transaction, payment_id='first-payment'),
        )
        second_response = self.client.post(
            reverse('liqpay_callback'),
            self.liqpay_callback_payload(second_transaction, payment_id='second-payment'),
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        first_transaction.refresh_from_db()
        second_transaction.refresh_from_db()
        self.assertEqual(first_transaction.status, OnlinePaymentTransaction.Status.SUCCESS)
        self.assertEqual(second_transaction.status, OnlinePaymentTransaction.Status.FAILED)
        self.assertEqual(Payment.objects.count(), 1)

    def test_failed_callback_does_not_create_payment(self):
        self.client.force_login(self.user)
        self.client.post(reverse('start_online_payment', args=[self.accrual.id]))
        transaction_obj = OnlinePaymentTransaction.objects.get(accrual=self.accrual)

        response = self.client.post(
            reverse('liqpay_callback'),
            self.liqpay_callback_payload(transaction_obj, status='failure'),
        )

        self.assertEqual(response.status_code, 200)
        transaction_obj.refresh_from_db()
        self.assertEqual(transaction_obj.status, OnlinePaymentTransaction.Status.FAILED)
        self.assertEqual(Payment.objects.count(), 0)

    def test_callback_rejects_wrong_signature_amount_and_currency(self):
        self.client.force_login(self.user)
        self.client.post(reverse('start_online_payment', args=[self.accrual.id]))
        transaction_obj = OnlinePaymentTransaction.objects.get(accrual=self.accrual)

        wrong_signature = self.liqpay_callback_payload(transaction_obj)
        wrong_signature['signature'] = 'bad'
        wrong_amount = self.liqpay_callback_payload(transaction_obj, amount='1.00')
        wrong_currency = self.liqpay_callback_payload(transaction_obj, currency='USD')

        self.assertEqual(self.client.post(reverse('liqpay_callback'), wrong_signature).status_code, 400)
        self.assertEqual(self.client.post(reverse('liqpay_callback'), wrong_amount).status_code, 400)
        self.assertEqual(self.client.post(reverse('liqpay_callback'), wrong_currency).status_code, 400)
        self.assertEqual(Payment.objects.count(), 0)

    def test_successful_online_payment_hides_pay_button(self):
        self.client.force_login(self.user)
        self.client.post(reverse('start_online_payment', args=[self.accrual.id]))
        transaction_obj = OnlinePaymentTransaction.objects.get(accrual=self.accrual)
        self.client.post(reverse('liqpay_callback'), self.liqpay_callback_payload(transaction_obj))

        response = self.client.get(reverse('finance'))

        self.assertNotContains(response, reverse('start_online_payment', args=[self.accrual.id]))
