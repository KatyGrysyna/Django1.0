from decimal import Decimal

from django.db import transaction
from rest_framework import serializers

from .models import Book, Cart, CartItem, Category, Order, OrderItem


def validate_unique_items(items):
    book_ids = set()

    for item in items:
        if 'book' not in item:
            raise serializers.ValidationError(
                'Each item must include book_id.'
            )

        book_id = item['book'].pk

        if book_id in book_ids:
            raise serializers.ValidationError(
                'Each book may appear only once.'
            )

        book_ids.add(book_id)
        item.setdefault('quantity', 1)

    return items


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'slug']
        read_only_fields = ['id']


class BookSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        source='category',
        queryset=Category.objects.all(),
        write_only=True,
    )
    price = serializers.DecimalField(
        max_digits=8,
        decimal_places=2,
        min_value=Decimal('0.00'),
    )

    class Meta:
        model = Book
        fields = [
            'id',
            'title',
            'author',
            'price',
            'description',
            'stock',
            'category',
            'category_id',
        ]
        read_only_fields = ['id']


class OrderItemSerializer(serializers.ModelSerializer):
    book = BookSerializer(read_only=True)
    book_id = serializers.PrimaryKeyRelatedField(
        source='book',
        queryset=Book.objects.all(),
        write_only=True,
    )
    quantity = serializers.IntegerField(
        min_value=1,
        max_value=2147483647,
        default=1,
    )
    subtotal = serializers.DecimalField(
        source='get_subtotal',
        max_digits=20,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = OrderItem
        fields = [
            'id',
            'book',
            'book_id',
            'quantity',
            'price',
            'subtotal',
        ]
        read_only_fields = ['id', 'price']


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(
        many=True,
        allow_empty=False,
        max_length=100,
    )
    total = serializers.DecimalField(
        source='get_total',
        max_digits=20,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = Order
        fields = [
            'id',
            'user',
            'created_at',
            'status',
            'items',
            'total',
        ]
        read_only_fields = [
            'id',
            'user',
            'created_at',
            'status',
        ]

    def validate_items(self, items):
        return validate_unique_items(items)

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop('items')
        order = Order.objects.create(**validated_data)

        OrderItem.objects.bulk_create([
            OrderItem(
                order=order,
                book=item['book'],
                quantity=item['quantity'],
                price=item['book'].price,
            )
            for item in items
        ])

        return Order.objects.prefetch_related(
            'items__book__category'
        ).get(pk=order.pk)

    @transaction.atomic
    def update(self, instance, validated_data):
        order = Order.objects.select_for_update().get(pk=instance.pk)

        if order.status != 'pending' or order.stripe_session_id:
            raise serializers.ValidationError(
                'Only pending orders without a payment session can be changed.'
            )

        items = validated_data.pop('items', None)

        if items is not None:
            order.items.all().delete()

            OrderItem.objects.bulk_create([
                OrderItem(
                    order=order,
                    book=item['book'],
                    quantity=item['quantity'],
                    price=item['book'].price,
                )
                for item in items
            ])

        return Order.objects.prefetch_related(
            'items__book__category'
        ).get(pk=order.pk)


class CartItemSerializer(serializers.ModelSerializer):
    book = BookSerializer(read_only=True)
    book_id = serializers.PrimaryKeyRelatedField(
        source='book',
        queryset=Book.objects.all(),
        write_only=True,
    )
    quantity = serializers.IntegerField(
        min_value=1,
        max_value=2147483647,
        default=1,
    )
    subtotal = serializers.DecimalField(
        source='get_subtotal',
        max_digits=20,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = CartItem
        fields = [
            'id',
            'book',
            'book_id',
            'quantity',
            'subtotal',
        ]
        read_only_fields = ['id']


class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(
        many=True,
        required=False,
        allow_empty=True,
        max_length=100,
    )
    total = serializers.DecimalField(
        source='get_total',
        max_digits=20,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = Cart
        fields = [
            'id',
            'user',
            'created_at',
            'items',
            'total',
        ]
        read_only_fields = [
            'id',
            'user',
            'created_at',
        ]

    def validate_items(self, items):
        return validate_unique_items(items)

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop('items', [])

        cart, created = Cart.objects.get_or_create(
            user=validated_data['user']
        )

        if not created:
            raise serializers.ValidationError(
                'You already have a cart. Update the existing cart.'
            )

        CartItem.objects.bulk_create([
            CartItem(
                cart=cart,
                book=item['book'],
                quantity=item['quantity'],
            )
            for item in items
        ])

        return Cart.objects.prefetch_related(
            'items__book__category'
        ).get(pk=cart.pk)

    @transaction.atomic
    def update(self, instance, validated_data):
        cart = Cart.objects.select_for_update().get(pk=instance.pk)
        items = validated_data.pop('items', None)

        if items is not None:
            cart.items.all().delete()

            CartItem.objects.bulk_create([
                CartItem(
                    cart=cart,
                    book=item['book'],
                    quantity=item['quantity'],
                )
                for item in items
            ])

        return Cart.objects.prefetch_related(
            'items__book__category'
        ).get(pk=cart.pk)