from django.urls import reverse_lazy
from django.views.generic import CreateView

from .forms import CustomUserCreationForm
from .models import CustomUser


class RegisterView(CreateView):
    """Display the registration form and create a user from valid data.

    Show validation errors for invalid submissions.
    Redirect to the login page after successful registration.
    """

    model = CustomUser
    form_class = CustomUserCreationForm
    template_name = 'accounts/register.html'
    success_url = reverse_lazy('accounts:login')