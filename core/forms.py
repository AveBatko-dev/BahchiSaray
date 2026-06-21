from django import forms

from .models import Meter, MeterReading, PaymentReceipt, Plot, normalize_phone


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


class PhoneLoginForm(BootstrapFormMixin, forms.Form):
    phone = forms.CharField(label='Номер телефону', max_length=30)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['phone'].widget.attrs.update({
            'autocomplete': 'tel',
            'placeholder': '+380...',
        })
        self.apply_bootstrap()

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data['phone'])
        if not phone:
            raise forms.ValidationError('Вкажіть номер телефону.')
        return phone


class LoginCodeForm(BootstrapFormMixin, forms.Form):
    code = forms.CharField(label='Одноразовий код', max_length=12)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['code'].widget.attrs.update({
            'autocomplete': 'one-time-code',
            'inputmode': 'numeric',
        })
        self.apply_bootstrap()

    def clean_code(self):
        return self.cleaned_data['code'].strip()


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
