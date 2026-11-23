from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet

from .models import StockItem
from .permissions import WarehouseModelPermissions
from .serializers import StockItemSerializer
from .stock_cache import get_stock_list_cache, set_stock_list_cache


class StockItemViewSet(ReadOnlyModelViewSet):
    queryset = StockItem.objects.all()
    serializer_class = StockItemSerializer
    permission_classes = [WarehouseModelPermissions]
    filterset_fields = ["external_book_id"]

    def list(self, request, *args, **kwargs):
        key, cached_data = get_stock_list_cache(request)

        if cached_data is not None:
            response = Response(cached_data)
        else:
            response = super().list(request, *args, **kwargs)
            if response.status_code == 200:
                set_stock_list_cache(key, response.data)

        response["Cache-Control"] = "private, no-store"
        return response