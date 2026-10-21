from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
)
from rest_framework.permissions import AllowAny
from rest_framework.routers import DefaultRouter

from .api_views import (
    BookViewSet,
    CartViewSet,
    CategoryViewSet,
    OrderViewSet,
    ThrottledTokenObtainPairView,
    ThrottledTokenRefreshView,
    ThrottledTokenVerifyView,
)


app_name = 'api'

router = DefaultRouter()
router.register('books', BookViewSet, basename='book')
router.register('categories', CategoryViewSet, basename='category')
router.register('orders', OrderViewSet, basename='order')
router.register('cart', CartViewSet, basename='cart')

urlpatterns = [
    path(
        'token/',
        ThrottledTokenObtainPairView.as_view(),
        name='token_obtain_pair',
    ),
    path(
        'token/refresh/',
        ThrottledTokenRefreshView.as_view(),
        name='token_refresh',
    ),
    path(
        'token/verify/',
        ThrottledTokenVerifyView.as_view(),
        name='token_verify',
    ),
    path(
        'schema/',
        SpectacularAPIView.as_view(
            permission_classes=[AllowAny],
        ),
        name='schema',
    ),
    path(
        'docs/',
        SpectacularSwaggerView.as_view(
            url_name='api:schema',
            permission_classes=[AllowAny],
        ),
        name='docs',
    ),
    path('', include(router.urls)),
]