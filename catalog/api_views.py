from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.viewsets import ModelViewSet
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)

from .filters import BookFilter, OrderFilter
from .models import Book, Cart, Category, Order
from .permissions import IsAdminOrReadOnly, IsOwnerOrReadOnly
from .serializers import (
    BookSerializer,
    CartSerializer,
    CategorySerializer,
    OrderSerializer,
)


class BookViewSet(ModelViewSet):
    """List and retrieve books publicly; allow staff to manage them."""

    queryset = Book.objects.select_related('category').order_by('id')
    serializer_class = BookSerializer
    permission_classes = [IsAdminOrReadOnly]
    filterset_class = BookFilter


class CategoryViewSet(ModelViewSet):
    """List and retrieve categories publicly; allow staff to manage them."""

    queryset = Category.objects.order_by('id')
    serializer_class = CategorySerializer
    permission_classes = [IsAdminOrReadOnly]
    filterset_fields = ['name', 'slug']


class OrderViewSet(ModelViewSet):
    """Manage the authenticated user's orders with nested items."""

    queryset = Order.objects.prefetch_related(
        'items__book__category'
    ).order_by('-created_at', '-id')
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrReadOnly]
    filterset_class = OrderFilter

    def get_queryset(self):
        """Return only orders belonging to the current user."""
        queryset = super().get_queryset()

        if (
            getattr(self, 'swagger_fake_view', False)
            or not self.request.user.is_authenticated
        ):
            return queryset.none()

        return queryset.filter(user=self.request.user)

    def perform_create(self, serializer):
        """Assign ownership using the authenticated user."""
        serializer.save(user=self.request.user)

    @transaction.atomic
    def perform_destroy(self, instance):
        """Delete only pending orders without a payment session."""
        order = get_object_or_404(
            Order.objects.select_for_update(),
            pk=instance.pk,
            user=self.request.user,
        )

        if order.status != 'pending' or order.stripe_session_id:
            raise ValidationError({
                'detail': (
                    'Only pending orders without a payment session '
                    'can be deleted.'
                ),
            })

        order.delete()


class CartViewSet(ModelViewSet):
    """Manage the authenticated user's database cart and its items."""

    queryset = Cart.objects.prefetch_related(
        'items__book__category'
    ).order_by('id')
    serializer_class = CartSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrReadOnly]

    def get_queryset(self):
        """Return only the current user's cart."""
        queryset = super().get_queryset()

        if (
            getattr(self, 'swagger_fake_view', False)
            or not self.request.user.is_authenticated
        ):
            return queryset.none()

        return queryset.filter(user=self.request.user)

    def perform_create(self, serializer):
        """Assign the new cart to the authenticated user."""
        serializer.save(user=self.request.user)


class ThrottledTokenObtainPairView(TokenObtainPairView):
    """Issue access and refresh tokens with an authentication rate limit."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'


class ThrottledTokenRefreshView(TokenRefreshView):
    """Refresh an access token with an authentication rate limit."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'


class ThrottledTokenVerifyView(TokenVerifyView):
    """Verify a token with an authentication rate limit."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'