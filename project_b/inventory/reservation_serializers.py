from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from .models import Reservation, ReservationItem
from .services import MAX_EXTERNAL_ID, MAX_ITEMS, MAX_QUANTITY


class ReservationItemInputSerializer(serializers.Serializer):
    external_book_id = serializers.IntegerField(
        min_value=1,
        max_value=MAX_EXTERNAL_ID,
    )
    quantity = serializers.IntegerField(
        min_value=1,
        max_value=MAX_QUANTITY,
    )


class ReservationCreateSerializer(serializers.Serializer):
    external_order_id = serializers.IntegerField(
        min_value=1,
        max_value=MAX_EXTERNAL_ID,
    )
    items = ReservationItemInputSerializer(
        many=True,
        allow_empty=False,
        min_length=1,
        max_length=MAX_ITEMS,
    )

    def validate_items(self, items):
        book_ids = [item["external_book_id"] for item in items]

        if len(book_ids) != len(set(book_ids)):
            raise serializers.ValidationError(
                _("Each book must appear only once in a reservation.")
            )

        return items


class ReservationItemSerializer(serializers.ModelSerializer):
    external_book_id = serializers.IntegerField(
        source="stock_item.external_book_id",
        read_only=True,
    )
    title = serializers.CharField(
        source="stock_item.title",
        read_only=True,
    )

    class Meta:
        model = ReservationItem
        fields = ("external_book_id", "title", "quantity")
        read_only_fields = fields


class ReservationSerializer(serializers.ModelSerializer):
    items = ReservationItemSerializer(many=True, read_only=True)

    class Meta:
        model = Reservation
        fields = (
            "id",
            "external_order_id",
            "status",
            "expires_at",
            "created_at",
            "updated_at",
            "items",
        )
        read_only_fields = fields
