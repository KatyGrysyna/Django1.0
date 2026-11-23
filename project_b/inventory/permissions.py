from rest_framework.permissions import DjangoModelPermissions


class WarehouseModelPermissions(DjangoModelPermissions):
    perms_map = {
        **DjangoModelPermissions.perms_map,
        "GET": ["%(app_label)s.view_%(model_name)s"],
        "HEAD": ["%(app_label)s.view_%(model_name)s"],
        "OPTIONS": ["%(app_label)s.view_%(model_name)s"],
    }


class ReservationPermissions(WarehouseModelPermissions):
    def has_permission(self, request, view):
        if request.method == "POST" and getattr(view, "action", None) in (
            "confirm",
            "release",
        ):
            user = request.user
            return bool(
                user
                and user.is_authenticated
                and user.has_perm("inventory.change_reservation")
            )

        return super().has_permission(request, view)

    def has_object_permission(self, request, view, obj):
        return obj.created_by_id == request.user.pk
