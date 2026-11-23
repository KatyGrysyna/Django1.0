from rest_framework import serializers

from .models import StockItem


class StockItemSerializer(serializers.ModelSerializer):
    available = serializers.IntegerField(read_only=True)

    class Meta:
        model = StockItem
        fields = (
            "id",
            "external_book_id",
            "title",
            "quantity",
            "reserved",
            "available",
            "updated_at",
        )
        read_only_fields = fields
