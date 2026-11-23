from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _


class StockItem(models.Model):
    """Stock for one book from ProjectA."""

    external_book_id = models.PositiveBigIntegerField(
        _("book ID in ProjectA"),
        unique=True,
        validators=[MinValueValidator(1)],
    )
    title = models.CharField(_("title"), max_length=200)
    quantity = models.PositiveIntegerField(_("total quantity"), default=0)
    reserved = models.PositiveIntegerField(
        _("reserved quantity"),
        default=0,
        editable=False,
    )
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        ordering = ["external_book_id"]
        verbose_name = _("stock item")
        verbose_name_plural = _("stock items")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(external_book_id__gte=1),
                name="inventory_book_id_gt_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(reserved__lte=models.F("quantity")),
                name="inventory_reserved_lte_quantity",
            ),
        ]

    def __str__(self):
        return f"{self.title} (#{self.external_book_id})"

    @property
    def available(self):
        return self.quantity - self.reserved

    def clean(self):
        super().clean()
        if (
            isinstance(self.quantity, int)
            and isinstance(self.reserved, int)
            and self.reserved > self.quantity
        ):
            raise ValidationError(
                {
                    "quantity": _(
                        "Total quantity cannot be lower than reserved quantity."
                    )
                }
            )


class Reservation(models.Model):
    """Reservation for one order from ProjectA."""

    class Status(models.TextChoices):
        PENDING = "pending", _("pending")
        CONFIRMED = "confirmed", _("confirmed")
        RELEASED = "released", _("released")
        EXPIRED = "expired", _("expired")

    id = models.UUIDField(
        primary_key=True,
        default=uuid4,
        editable=False,
    )
    external_order_id = models.PositiveBigIntegerField(
        _("order ID in ProjectA"),
        validators=[MinValueValidator(1)],
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="stock_reservations",
        verbose_name=_("created by"),
    )
    status = models.CharField(
        _("status"),
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )
    expires_at = models.DateTimeField(_("expires at"))
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        ordering = ["-created_at", "id"]
        verbose_name = _("reservation")
        verbose_name_plural = _("reservations")
        constraints = [
            models.UniqueConstraint(
                fields=["created_by", "external_order_id"],
                name="inventory_res_order_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(external_order_id__gte=1),
                name="inventory_res_order_gt_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=["pending", "confirmed", "released", "expired"]
                ),
                name="inventory_res_status_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "expires_at"],
                name="inventory_res_exp_idx",
            ),
        ]

    def __str__(self):
        return f"{self.external_order_id} ({self.status})"


class ReservationItem(models.Model):
    """One book and its quantity within a reservation."""

    reservation = models.ForeignKey(
        Reservation,
        on_delete=models.PROTECT,
        related_name="items",
        verbose_name=_("reservation"),
    )
    stock_item = models.ForeignKey(
        StockItem,
        on_delete=models.PROTECT,
        related_name="reservation_items",
        verbose_name=_("stock item"),
    )
    quantity = models.PositiveIntegerField(
        _("quantity"),
        validators=[MinValueValidator(1)],
    )

    class Meta:
        ordering = ["id"]
        verbose_name = _("reservation item")
        verbose_name_plural = _("reservation items")
        constraints = [
            models.UniqueConstraint(
                fields=["reservation", "stock_item"],
                name="inventory_res_item_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gte=1),
                name="inventory_res_item_qty_gt_zero",
            ),
        ]

    def __str__(self):
        return f"{self.stock_item_id} x {self.quantity}"
