from rest_framework.routers import SimpleRouter

from .reservation_views import ReservationViewSet
from .views import StockItemViewSet

router = SimpleRouter()
router.register("stock", StockItemViewSet, basename="stock")
router.register(
    "reservations",
    ReservationViewSet,
    basename="reservation",
)

urlpatterns = router.urls
