from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import WarehouseUser

admin.site.register(WarehouseUser, UserAdmin)