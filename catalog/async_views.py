from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import aget_object_or_404
from django.views.decorators.http import require_GET

from .models import Book, Category


@require_GET
async def book_list(request):
    queryset = Book.objects.order_by('id')

    category_slug = request.GET.get('category')
    if category_slug:
        queryset = queryset.filter(category__slug=category_slug)

    books = [
        {
            'id': book.id,
            'title': book.title,
            'author': book.author,
            'price': str(book.price),
            'stock': book.stock,
            'category_id': book.category_id,
        }
        async for book in queryset
    ]

    return JsonResponse(
        {'books': books},
        json_dumps_params={'ensure_ascii': False},
    )


@require_GET
async def book_detail(request, pk):
    book = await aget_object_or_404(
        Book.objects.select_related('category'),
        pk=pk,
    )

    return JsonResponse(
        {
            'id': book.id,
            'title': book.title,
            'author': book.author,
            'description': book.description,
            'price': str(book.price),
            'stock': book.stock,
            'category_id': book.category_id,
            'category_name': book.category.name,
        },
        json_dumps_params={'ensure_ascii': False},
    )


@require_GET
async def category_list(request):
    queryset = Category.objects.annotate(
        book_count=Count('books'),
    ).order_by('name', 'id')

    categories = [
        {
            'id': category.id,
            'name': category.name,
            'slug': category.slug,
            'book_count': category.book_count,
        }
        async for category in queryset
    ]

    return JsonResponse(
        {'categories': categories},
        json_dumps_params={'ensure_ascii': False},
    )