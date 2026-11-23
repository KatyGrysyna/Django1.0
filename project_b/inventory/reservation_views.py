import logging

from django.db.models import prefetch_related_objects
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet

from .models import Reservation
from .permissions import ReservationPermissions
from .reservation_lifecycle import (
    ReservationNotFound,
    confirm_reservation,
    release_reservation,
)
from .reservation_serializers import (
    ReservationCreateSerializer,
    ReservationSerializer,
)
from .services import (
    InvalidReservation,
    ReservationConflict,
    StockUnavailable,
    reserve_stock,
)

logger = logging.getLogger(__name__)


class ReservationAPIConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = _("The reservation conflicts with the warehouse state.")
    default_code = "reservation_conflict"


@extend_schema(tags=["Reservations"])
class ReservationViewSet(mixins.CreateModelMixin, ReadOnlyModelViewSet):
    queryset = Reservation.objects.all()
    serializer_class = ReservationSerializer
    permission_classes = [ReservationPermissions]
    filterset_fields = ["external_order_id", "status"]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = super().get_queryset()

        if getattr(self, "swagger_fake_view", False):
            return queryset.none()

        if not self.request.user.is_authenticated:
            return queryset.none()

        return queryset.filter(created_by=self.request.user).prefetch_related(
            "items__stock_item"
        )

    def get_serializer_class(self):
        if self.action == "create":
            return ReservationCreateSerializer
        return ReservationSerializer

    def _reservation_response(self, reservation, status_code=status.HTTP_200_OK):
        prefetch_related_objects([reservation], "items__stock_item")
        serializer = ReservationSerializer(
            reservation,
            context=self.get_serializer_context(),
        )
        return Response(serializer.data, status=status_code)

    @extend_schema(
        summary=_("Create a reservation"),
        request=ReservationCreateSerializer,
        responses={
            200: ReservationSerializer,
            201: ReservationSerializer,
            400: OpenApiResponse(description="Invalid request data."),
            409: OpenApiResponse(
                description="Unavailable stock or conflicting reservation."
            ),
        },
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        reservation, created = reserve_stock(
            created_by=request.user,
            external_order_id=serializer.validated_data["external_order_id"],
            items=serializer.validated_data["items"],
        )

        response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return self._reservation_response(reservation, response_status)

    @extend_schema(
        summary=_("Confirm a reservation"),
        request=None,
        responses={
            200: ReservationSerializer,
            404: OpenApiResponse(description="Reservation not found."),
            409: OpenApiResponse(description="Reservation cannot be confirmed."),
        },
    )
    @action(detail=True, methods=["post"], filter_backends=[])
    def confirm(self, request, *args, **kwargs):
        reservation = self.get_object()
        reservation, _ = confirm_reservation(
            reservation_id=reservation.pk,
            created_by=request.user,
        )
        return self._reservation_response(reservation)

    @extend_schema(
        summary=_("Release a reservation"),
        request=None,
        responses={
            200: ReservationSerializer,
            404: OpenApiResponse(description="Reservation not found."),
            409: OpenApiResponse(description="Reservation cannot be released."),
        },
    )
    @action(detail=True, methods=["post"], filter_backends=[])
    def release(self, request, *args, **kwargs):
        reservation = self.get_object()
        reservation, _ = release_reservation(
            reservation_id=reservation.pk,
            created_by=request.user,
        )
        return self._reservation_response(reservation)

    def handle_exception(self, exc):
        if isinstance(exc, ReservationNotFound):
            api_error = NotFound(detail=str(exc))
        elif isinstance(exc, InvalidReservation):
            api_error = ValidationError({"detail": str(exc)})
        elif isinstance(exc, (ReservationConflict, StockUnavailable)):
            api_error = ReservationAPIConflict(detail=str(exc))
        else:
            return super().handle_exception(exc)

        logger.warning(
            "Reservation API rejected action=%s user_id=%s: %s",
            getattr(self, "action", "unknown"),
            getattr(self.request.user, "pk", None),
            exc,
        )
        return super().handle_exception(api_error)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        return response
