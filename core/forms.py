from django import forms
from django.contrib.auth import get_user_model

from .models import Meter, MeterReading, PaymentReceipt, Plot


class BootstrapFormMixin:
    def apply_bootstrap(self):
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault('class', 'form-check-input')
            elif isinstance(widget, forms.FileInput):
                widget.attrs.setdefault('class', 'form-control')
            else:
                widget.attrs.setdefault('class', 'form-control')


class UserLoginForm(BootstrapFormMixin, forms.Form):
    login = forms.CharField(label='Телефон або email', max_length=255)
    password = forms.CharField(label='Пароль', widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['login'].widget.attrs.update({'autocomplete': 'username'})
        self.fields['password'].widget.attrs.update({'autocomplete': 'current-password'})
        self.apply_bootstrap()


class UserRegistrationForm(BootstrapFormMixin, forms.Form):
    full_name = forms.CharField(label='ПІБ', max_length=255)
    phone = forms.CharField(label='Телефон', max_length=30)
    email = forms.EmailField(label='Email')
    password = forms.CharField(label='Пароль', widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['full_name'].widget.attrs.update({'autocomplete': 'name'})
        self.fields['phone'].widget.attrs.update({'autocomplete': 'tel'})
        self.fields['email'].widget.attrs.update({'autocomplete': 'email'})
        self.fields['password'].widget.attrs.update({'autocomplete': 'new-password'})
        self.apply_bootstrap()

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        User = get_user_model()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Користувач з таким email вже існує.')
        return email

    def clean_phone(self):
        phone = self.cleaned_data['phone'].strip()
        if not phone:
            raise forms.ValidationError('Вкажіть телефон.')
        return phone


class MeterReadingForm(BootstrapFormMixin, forms.ModelForm):
    plot = forms.ModelChoiceField(label='Ділянка', queryset=Plot.objects.none())

    class Meta:
        model = MeterReading
        fields = ['plot', 'meter', 'value', 'photo']
        labels = {
            'meter': 'Лічильник',
            'value': 'Поточне показання',
            'photo': 'Фото лічильника',
        }

    def __init__(self, *args, plots=None, **kwargs):
        super().__init__(*args, **kwargs)
        plots = plots or Plot.objects.none()
        self.fields['plot'].queryset = plots
        self.fields['meter'].queryset = Meter.objects.filter(plot__in=plots, is_active=True)
        self.apply_bootstrap()

    def clean(self):
        cleaned_data = super().clean()
        plot = cleaned_data.get('plot')
        meter = cleaned_data.get('meter')
        if plot and meter and meter.plot_id != plot.id:
            self.add_error('meter', 'Обраний лічильник не належить цій ділянці.')
        return cleaned_data


class PaymentReceiptForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = PaymentReceipt
        fields = ['plot', 'amount', 'paid_at', 'method', 'photo', 'comment']
        widgets = {
            'paid_at': forms.DateInput(attrs={'type': 'date'}),
            'comment': forms.Textarea(attrs={'rows': 4}),
        }
        labels = {
            'plot': 'Ділянка',
            'amount': 'Сума оплати',
            'paid_at': 'Дата оплати',
            'method': 'Спосіб оплати',
            'photo': 'Фото квитанції',
            'comment': 'Коментар',
        }

    def __init__(self, *args, plots=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['plot'].queryset = plots or Plot.objects.none()
        self.apply_bootstrap()
