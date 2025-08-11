import datetime

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.validators import RegexValidator
from .models import ServiceUser, CareHome, CustomUser, ABCForm, IncidentReport, LogEntry, Mapping
# forms.py
from django import forms
from .models import CareHome
import datetime

# AM time choices: 12:00 AM to 11:00 AM
AM_TIMES = [
    (datetime.time(hour=h), f"{(h % 12 or 12)}:00 AM")
    for h in range(0, 12)
]


def coerce_to_time(val):
    if isinstance(val, datetime.time):
        return val
    if isinstance(val, str):
        h, m = map(int, val.split(":"))
        return datetime.time(h, m)
    return None


class CareHomeForm(forms.ModelForm):
    class Meta:
        model = CareHome
        fields = ['name', 'postcode', 'details', 'picture', 'morning_shift_start', 'night_shift_start']
        widgets = {
            'morning_shift_start': forms.TimeInput(format='%H:%M', attrs={'type': 'time'}),
            'night_shift_start': forms.TimeInput(format='%H:%M', attrs={'type': 'time'}),
        }

class LoginForm(AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={'class': 'form-control'}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control'}))


class ServiceUserForm(forms.ModelForm):
    class Meta:
        model = ServiceUser
        fields = '__all__'
        widgets = {
            'carehome': forms.Select(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '+44 7123 456789 or 07123 456789'
            }),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'emergency_contact': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class StaffCreationForm(UserCreationForm):
    role = forms.ChoiceField(
        choices=CustomUser.ROLE_CHOICES,
        widget=forms.RadioSelect
    )
    carehome = forms.ModelChoiceField(
        queryset=CareHome.objects.none(),  # Start with empty queryset
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    class Meta:
        model = CustomUser
        fields = (
            'image', 'first_name', 'last_name', 'email',
            'phone', 'address', 'role', 'carehome', 'additional_info',
            'password1', 'password2'
        )
        widgets = {
            'image': forms.FileInput(attrs={'class': 'form-control-file'}),
            'address': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'additional_info': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'custom-file-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Populate carehome dropdown safely at runtime
        self.fields['carehome'].queryset = CareHome.objects.all()

        # Optional: add Bootstrap classes to role choices for consistency
        self.fields['role'].widget.attrs.update({'class': 'form-check-input'})

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get('role')
        carehome = cleaned_data.get('carehome')

        if role == CustomUser.TEAM_LEAD and not carehome:
            self.add_error('carehome', "Care Home is required for Team Leads.")

        return cleaned_data


class IncidentReportForm(forms.ModelForm):
    class Meta:
        model = IncidentReport
        fields = '__all__'
        exclude = ['staff', 'carehome', 'pdf_file', 'created_at']
        widgets = {
            'incident_datetime': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'manager_contact_date': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'police_contact_date': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'paramedics_contact_date': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'other_contact_date': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'image1': forms.ClearableFileInput(attrs={'accept': 'image/*'}),
            'image2': forms.ClearableFileInput(attrs={'accept': 'image/*'}),
            'image3': forms.ClearableFileInput(attrs={'accept': 'image/*'}),
        }


class LogEntryForm(forms.ModelForm):
    class Meta:
        model = LogEntry
        fields = ['content']
        widgets = {
            'content': forms.Textarea(attrs={'rows': 2}),
        }


class MappingForm(forms.ModelForm):
    class Meta:
        model = Mapping
        fields = ['staff', 'carehomes', 'service_users']
        widgets = {
            'carehomes': forms.SelectMultiple(attrs={'class': 'form-control'}),
            'service_users': forms.SelectMultiple(attrs={'class': 'form-control'}),
            'staff': forms.Select(attrs={'class': 'form-control'}),
        }


def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)

    # Only show users with staff role
    self.fields['staff'].queryset = CustomUser.objects.filter(role='staff')

    self.fields['carehomes'].queryset = CareHome.objects.all()
    self.fields['service_users'].queryset = ServiceUser.objects.none()

    self.fields['carehomes'].widget.attrs.update({'id': 'id_carehomes'})
    self.fields['service_users'].widget.attrs.update({'id': 'id_service_users'})

    if 'carehomes' in self.data:
        try:
            carehome_ids = self.data.getlist('carehomes')
            self.fields['service_users'].queryset = ServiceUser.objects.filter(carehome_id__in=carehome_ids)
        except (ValueError, TypeError):
            pass
    elif self.instance.pk:
        self.fields['service_users'].queryset = self.instance.service_users.all()


class ABCFormForm(forms.ModelForm):
    TARGET_BEHAVIOUR_CHOICES = [
        ('physical_aggression', 'Physical aggressive behaviour towards other people'),
        ('property_destruction', 'Property destruction e.g., ripping clothes'),
        ('self_injury', 'Self-injurious behaviours e.g., hitting the wall'),
        ('verbal_aggression', 'Verbal aggression'),
        ('other', 'Other / stereotyped behaviours e.g., screaming'),
    ]

    # Target behaviours field
    target_behaviours = forms.MultipleChoiceField(
        choices=TARGET_BEHAVIOUR_CHOICES,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'checkbox-list'}),
        required=False,
        label='Target Behaviours (select all that apply)'
    )

    # Setting fields
    setting_location = forms.CharField(
        label="Where did the behavior occur?",
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        required=True
    )
    setting_present = forms.CharField(
        label="Who was present?",
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        required=True
    )
    setting_activity = forms.CharField(
        label="What was happening?",
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        required=True
    )
    setting_environment = forms.CharField(
        label="Describe the environment (noise, temperature, etc.)",
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        required=False
    )

    # Antecedent fields
    antecedent_description = forms.CharField(
        label="What happened just before the behaviour started?",
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        required=True
    )
    antecedent_change = forms.ChoiceField(
        label="Was there a change in routine?",
        choices=[('yes', 'Yes'), ('no', 'No')],
        widget=forms.Select(attrs={'class': 'form-control'}),
        initial='no'
    )
    antecedent_noise = forms.ChoiceField(
        label="Was there unexpected noise?",
        choices=[('yes', 'Yes'), ('no', 'No')],
        widget=forms.Select(attrs={'class': 'form-control'}),
        initial='no'
    )
    antecedent_waiting = forms.CharField(
        label="Was the client waiting for something?",
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        required=False
    )

    # Behaviour field
    behaviour_description = forms.CharField(
        label="Describe exactly what the client did",
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 5}),
        required=True
    )

    # Consequences field
    consequence_immediate = forms.CharField(
        label="What happened after the behaviour took place? What did you do?",
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        required=True
    )

    # Reflection field
    reflection_learnings = forms.CharField(
        label="What can we learn from this situation & take forward whilst supporting the client?",
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        required=True
    )

    class Meta:
        model = ABCForm
        fields = ['service_user', 'date_of_birth', 'staff', 'date_time', 'target_behaviours']
        widgets = {
            'service_user': forms.Select(attrs={
                'class': 'form-control select2',
                'data-placeholder': 'Select a service user'
            }),
            'date_time': forms.DateTimeInput(attrs={
                'type': 'datetime-local',
                'class': 'form-control'
            }),
            'date_of_birth': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }),
            'staff': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter staff name manually'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Order service users by last name
        self.fields['service_user'].label_from_instance = lambda obj: obj.get_formatted_name()

        # Parse existing instance data for edit view
        if self.instance and self.instance.pk:
            self.parse_instance_data()

    def parse_instance_data(self):
        """Parse the combined fields into individual form fields"""
        # Parse setting
        setting_data = self.parse_field_text(self.instance.setting)
        self.initial.update({
            'setting_location': setting_data.get('Location', ''),
            'setting_present': setting_data.get('Present', ''),
            'setting_activity': setting_data.get('Activity', ''),
            'setting_environment': setting_data.get('Environment', '')
        })

        # Parse antecedent
        antecedent_data = self.parse_field_text(self.instance.antecedent)
        self.initial.update({
            'antecedent_description': antecedent_data.get('Description', ''),
            'antecedent_change': antecedent_data.get('Routine change', 'no'),
            'antecedent_noise': antecedent_data.get('Unexpected noise', 'no'),
            'antecedent_waiting': antecedent_data.get('Waiting for', '')
        })

        # Parse other fields
        behaviour_data = self.parse_field_text(self.instance.behaviour)
        self.initial['behaviour_description'] = behaviour_data.get('Description', '')

        consequences_data = self.parse_field_text(self.instance.consequences)
        self.initial['consequence_immediate'] = consequences_data.get('Immediate', '')

        reflection_data = self.parse_field_text(self.instance.reflection)
        self.initial['reflection_learnings'] = reflection_data.get('Learnings', '')

    @staticmethod
    def parse_field_text(text):
        """Helper method to parse field text into dictionary"""
        if not text:
            return {}
        return dict(line.split(':', 1) for line in text.split('\n') if ':' in line)

    def save(self, commit=True):
        instance = super().save(commit=False)

        # Combine individual fields into model's text fields
        instance.setting = "\n".join([
            f"Location: {self.cleaned_data.get('setting_location', '')}",
            f"Present: {self.cleaned_data.get('setting_present', '')}",
            f"Activity: {self.cleaned_data.get('setting_activity', '')}",
            f"Environment: {self.cleaned_data.get('setting_environment', '')}"
        ])

        instance.antecedent = "\n".join([
            f"Description: {self.cleaned_data.get('antecedent_description', '')}",
            f"Routine change: {self.cleaned_data.get('antecedent_change', 'no')}",
            f"Unexpected noise: {self.cleaned_data.get('antecedent_noise', 'no')}",
            f"Waiting for: {self.cleaned_data.get('antecedent_waiting', '')}"
        ])

        instance.behaviour = f"Description: {self.cleaned_data.get('behaviour_description', '')}"
        instance.consequences = f"Immediate: {self.cleaned_data.get('consequence_immediate', '')}"
        instance.reflection = f"Learnings: {self.cleaned_data.get('reflection_learnings', '')}"

        if commit:
            instance.save()
            self.save_m2m()

        return instance