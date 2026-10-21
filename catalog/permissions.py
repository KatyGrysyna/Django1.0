from rest_framework.permissions import (
    BasePermission,
    IsAdminUser,
    SAFE_METHODS,
)


class IsAdminOrReadOnly(IsAdminUser):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True

        return super().has_permission(request, view)


class IsOwnerOrReadOnly(BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True

        return (
            request.user.is_authenticated
            and obj.user_id == request.user.pk
        )