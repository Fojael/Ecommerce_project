from django import forms
from django.contrib.auth.forms import AuthenticationForm, UsernameField, PasswordChangeForm, SetPasswordForm
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from .models import Customer


# ================= LOGIN FORM =================
class LoginForm(AuthenticationForm):

    username = UsernameField(
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Username',
            'autofocus': True
        })
    )

    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Password',
            'id': 'loginPassword'
        })
    )

    remember_me = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )


# ================= REGISTRATION FORM =================
class CustomerRegistrationForm(UserCreationForm):

    username = forms.CharField(widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(widget=forms.EmailInput(attrs={'class': 'form-control'}))
    first_name = forms.CharField(widget=forms.TextInput(attrs={'class': 'form-control'}))
    last_name = forms.CharField(widget=forms.TextInput(attrs={'class': 'form-control'}))
    password1 = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control', 'id': 'password1'}))
    password2 = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control', 'id': 'password2'}))

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name']
        
class MyPasswordResetForm(PasswordChangeForm):
      email = forms.EmailField(
          max_length=254,
          widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email', 'id': 'resetEmail'})
      )
class MySetPasswordForm(SetPasswordForm):
    new_password1 = forms.CharField(
        label="New password",
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'New Password', 'id': 'newPassword1'})
    )
    new_password2 = forms.CharField(
        label="Confirm new password",
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirm New Password', 'id': 'newPassword2'})
    )   
    
class CustomerProfileForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ['name', 'locality', 'city', 'mobile', 'zipcode', 'state']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'locality': forms.TextInput(attrs={'class': 'form-control'}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'mobile': forms.NumberInput(attrs={'class': 'form-control'}),
            'zipcode': forms.NumberInput(attrs={'class': 'form-control'}),
            'state': forms.Select(attrs={'class': 'form-control'})
        }
          
