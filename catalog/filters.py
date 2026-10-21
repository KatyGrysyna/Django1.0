from django_filters import rest_framework as filters

from .models import Book, Order


class BookFilter(filters.FilterSet):
    title = filters.CharFilter(
        field_name='title',
        lookup_expr='icontains',
    )
    author = filters.CharFilter(
        field_name='author',
        lookup_expr='icontains',
    )
    category_slug = filters.CharFilter(
        field_name='category__slug',
    )
    min_price = filters.NumberFilter(
        field_name='price',
        lookup_expr='gte',
    )
    max_price = filters.NumberFilter(
        field_name='price',
        lookup_expr='lte',
    )

    class Meta:
        model = Book
        fields = [
            'category',
            'category_slug',
            'title',
            'author',
            'min_price',
            'max_price',
        ]


class OrderFilter(filters.FilterSet):
    created_after = filters.IsoDateTimeFilter(
        field_name='created_at',
        lookup_expr='gte',
    )
    created_before = filters.IsoDateTimeFilter(
        field_name='created_at',
        lookup_expr='lte',
    )

    class Meta:
        model = Order
        fields = [
            'status',
            'created_after',
            'created_before',
        ]