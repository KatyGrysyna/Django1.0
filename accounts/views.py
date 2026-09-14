from django.urls import reverse_lazy
from django.views.generic import CreateView
from .models import CustomUser
from .forms import CustomUserCreationForm


class RegisterView(CreateView):
    model = CustomUser
    form_class = CustomUserCreationForm
    template_name = 'accounts/register.html'
    success_url = reverse_lazy('accounts:login')

# Create your views here.
