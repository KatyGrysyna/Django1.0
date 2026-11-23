from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

GROUP_PERMISSIONS = {
    "warehouse_viewers": ("view_stockitem",),
    "warehouse_managers": (
        "view_stockitem",
        "add_stockitem",
        "change_stockitem",
    ),
    "warehouse_clients": (
        "view_stockitem",
        "view_reservation",
        "add_reservation",
        "change_reservation",
    ),
}


class Command(BaseCommand):
    help = "Create warehouse groups and configure their permissions."

    def handle(self, *args, **options):
        required = {
            codename
            for codenames in GROUP_PERMISSIONS.values()
            for codename in codenames
        }

        permissions = {
            permission.codename: permission
            for permission in Permission.objects.filter(
                content_type__app_label="inventory",
                content_type__model__in=["stockitem", "reservation"],
                codename__in=required,
            )
        }

        missing = required - set(permissions)

        if missing:
            raise CommandError(
                "Missing permissions: "
                + ", ".join(sorted(missing))
                + ". Run migrations first."
            )

        with transaction.atomic():
            for name, codenames in GROUP_PERMISSIONS.items():
                group, _ = Group.objects.get_or_create(name=name)
                group.permissions.set([permissions[codename] for codename in codenames])

        self.stdout.write(
            self.style.SUCCESS(
                "Warehouse groups configured: " + ", ".join(GROUP_PERMISSIONS)
            )
        )
