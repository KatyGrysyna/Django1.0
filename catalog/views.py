from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from .models import Book, Category


class BookListView(ListView):
    model = Book
    template_name = 'catalog/book_list.html'
    context_object_name = 'books'
    paginate_by = 6

    def get_queryset(self):
        queryset = Book.objects.all()
        category_slug = self.request.GET.get('category')
        if category_slug:
            queryset = queryset.filter(category__slug=category_slug)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['categories'] = Category.objects.all()
        context['selected_category'] = self.request.GET.get('category')
        return context
class BookDetailView(DetailView):
    model = Book
    template_name = 'catalog/book_detail.html'
    context_object_name = 'book'


class BookCreateView(CreateView):
    model = Book
    template_name = 'catalog/book_form.html'
    fields = ['title', 'author', 'price', 'description', 'stock', 'category']
    success_url = reverse_lazy('catalog:book_list')


class BookUpdateView(UpdateView):
    model = Book
    template_name = 'catalog/book_form.html'
    fields = ['title', 'author', 'price', 'description', 'stock', 'category']
    success_url = reverse_lazy('catalog:book_list')


class BookDeleteView(DeleteView):
    model = Book
    template_name = 'catalog/book_confirm_delete.html'
    success_url = reverse_lazy('catalog:book_list')

# Create your views here.
