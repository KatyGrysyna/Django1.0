from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import aget_object_or_404
from django.views.decorators.http import require_GET

from .models import Book, Category


@require_GET
async def book_list(request):
    """Return a filtered page of books using asynchronous ORM queries.

    Default to 20 books per page and allow at most 100.
    Return HTTP 400 for invalid parameters and 404 for a missing page.
    """
    try:
        page = int(request.GET.get('page', '1'))
        page_size = int(request.GET.get('page_size', '20'))

        if page < 1 or not 1 <= page_size <= 100:
            raise ValueError

    except (TypeError, ValueError):
        return JsonResponse(
            {
                'error': (
                    'page must be a positive integer; '
                    'page_size must be an integer from 1 to 100.'
                ),
            },
            status=400,
        )

    queryset = Book.objects.order_by('id')

    category_slug = request.GET.get('category')
    if category_slug:
        queryset = queryset.filter(category__slug=category_slug)

    total = await queryset.acount()
    total_pages = max(1, (total + page_size - 1) // page_size)

    if page > total_pages:
        return JsonResponse(
            {'error': 'Page not found.'},
            status=404,
        )

    start = (page - 1) * page_size

    books = [
        {
            'id': book.id,
            'title': book.title,
            'author': book.author,
            'price': str(book.price),
            'stock': book.stock,
            'category_id': book.category_id,
        }
        async for book in queryset[start:start + page_size]
    ]

    return JsonResponse(
        {
            'books': books,
            'pagination': {
                'page': page,
                'page_size': page_size,
                'total': total,
                'total_pages': total_pages,
                'has_next': page < total_pages,
                'has_previous': page > 1,
            },
        },
        json_dumps_params={'ensure_ascii': False},
    )


@require_GET
async def book_detail(request, pk):
    """Return a book and its category as JSON using an asynchronous query.

    Raise HTTP 404 when the requested book does not exist.
    Serialize the price as a string to preserve decimal precision.
    """
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
    """Return categories and their book counts as JSON.

    Include empty categories and sort results by name, then ID.
    Retrieve results using asynchronous iteration.
    """
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