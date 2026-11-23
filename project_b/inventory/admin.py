from django import forms
from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import StockItem


class StockItemAdminForm(forms.ModelForm):
    class Meta:
        model = StockItem
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()

        if self.instance._state.adding:
            return cleaned_data

        try:
            current = StockItem.objects.select_for_update().get(pk=self.instance.pk)
        except StockItem.DoesNotExist as exc:
            raise forms.ValidationError(
                _("This stock item no longer exists. Reload the page.")
            ) from exc

        self.instance.reserved = current.reserved
        self.instance.external_book_id = current.external_book_id

        return cleaned_data


@admin.register(StockItem)
class StockItemAdmin(admin.ModelAdmin):
    form = StockItemAdminForm

    list_display = (
        "external_book_id",
        "title",
        "quantity",
        "reserved",
        "available_quantity",
        "updated_at",
    )
    search_fields = ("title", "=external_book_id")
    readonly_fields = ("reserved", "available_quantity", "updated_at")

    @admin.display(description=_("available quantity"))
    def available_quantity(self, obj):
        return obj.available

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        if obj is not None:
            return fields + ("external_book_id",)
        return fields
