import logging
from math import isfinite
from urllib.parse import urlsplit
from uuid import UUID

import requests
from django.conf import settings
from django.utils.translation import get_language

logger = logging.getLogger(__name__)


class WarehouseError(Exception):
    """Base error for communication with the warehouse."""


class WarehouseConfigurationError(WarehouseError):
    """Warehouse connection settings are missing or invalid."""


class WarehouseUnavailable(WarehouseError):
    """The warehouse cannot currently process the request."""


class WarehouseProtocolError(WarehouseUnavailable):
    """The warehouse returned an unexpected response."""


class WarehouseAuthenticationError(WarehouseError):
    """The warehouse rejected authentication or permissions."""


class WarehouseAPIError(WarehouseError):
    def __init__(self, status_code):
        self.status_code = status_code
        super().__init__(f"Warehouse returned HTTP {status_code}.")


class WarehouseClient:
    def __init__(self):
        if not settings.WAREHOUSE_ENABLED:
            raise WarehouseConfigurationError("Warehouse integration is disabled.")

        self.base_url = settings.WAREHOUSE_API_URL.rstrip("/")
        self.username = settings.WAREHOUSE_USERNAME
        self.password = settings.WAREHOUSE_PASSWORD
        self.timeout = (
            settings.WAREHOUSE_CONNECT_TIMEOUT,
            settings.WAREHOUSE_READ_TIMEOUT,
        )

        try:
            parsed = urlsplit(self.base_url)
            valid_url = (
                parsed.scheme in ("http", "https")
                and bool(parsed.hostname)
                and parsed.username is None
                and parsed.password is None
                and not parsed.query
                and not parsed.fragment
            )
        except ValueError:
            valid_url = False

        if not valid_url or not self.username or not self.password:
            raise WarehouseConfigurationError(
                "Warehouse connection settings are incomplete or invalid."
            )

        if any(not isfinite(value) or value <= 0 for value in self.timeout):
            raise WarehouseConfigurationError(
                "Warehouse timeouts must be positive finite numbers."
            )

        self._access_token = None
        self._session = requests.Session()
        self._session.trust_env = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        self._access_token = None
        self._session.close()

    def _send(self, method, path, *, data=None, params=None, token=None):
        headers = {
            "Accept": "application/json",
            "Accept-Language": get_language() or "en",
        }

        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            response = self._session.request(
                method,
                f"{self.base_url}/{path}",
                json=data,
                params=params,
                headers=headers,
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            logger.warning(
                "Warehouse connection failed: method=%s path=%s error=%s",
                method,
                path,
                type(exc).__name__,
            )
            raise WarehouseUnavailable("Could not connect to the warehouse.") from None

        logger.log(
            logging.INFO if 200 <= response.status_code < 300 else logging.WARNING,
            "Warehouse API: method=%s path=%s status=%s",
            method,
            path,
            response.status_code,
        )
        return response

    @staticmethod
    def _invalid_response(message):
        logger.warning("Warehouse response rejected: %s", message)
        raise WarehouseProtocolError(message) from None

    def _decode(self, response):
        status_code = response.status_code

        if status_code in (401, 403):
            raise WarehouseAuthenticationError(
                "Warehouse authentication or permissions were rejected."
            )

        if status_code >= 500 or status_code in (408, 429):
            raise WarehouseUnavailable(
                f"Warehouse is temporarily unavailable: HTTP {status_code}."
            )

        if not 200 <= status_code < 300:
            raise WarehouseAPIError(status_code)

        try:
            data = response.json()
        except ValueError:
            self._invalid_response("Warehouse returned invalid JSON.")

        if not isinstance(data, dict):
            self._invalid_response("Warehouse must return a JSON object.")

        return data

    def _authenticate(self):
        response = self._send(
            "POST",
            "token/",
            data={
                "username": self.username,
                "password": self.password,
            },
        )
        data = self._decode(response)
        token = data.get("access")

        if (
            not isinstance(token, str)
            or not token
            or any(character.isspace() for character in token)
        ):
            self._invalid_response("Warehouse returned an invalid access token.")

        self._access_token = token

    def _request(self, method, path, *, data=None, params=None):
        if self._access_token is None:
            self._authenticate()

        response = self._send(
            method,
            path,
            data=data,
            params=params,
            token=self._access_token,
        )

        if response.status_code == 401:
            self._access_token = None
            self._authenticate()

            response = self._send(
                method,
                path,
                data=data,
                params=params,
                token=self._access_token,
            )

        if response.status_code == 401:
            self._access_token = None

        return self._decode(response)

    def list_stock(self, *, external_book_id=None, page=1):
        params = {"page": page}

        if external_book_id is not None:
            params["external_book_id"] = external_book_id

        data = self._request("GET", "stock/", params=params)

        if (
            not isinstance(data.get("results"), list)
            or type(data.get("count")) is not int
            or data["count"] < 0
        ):
            self._invalid_response("Warehouse returned an invalid stock list.")

        return data

    def reserve(self, *, external_order_id, items):
        return self._request(
            "POST",
            "reservations/",
            data={
                "external_order_id": external_order_id,
                "items": items,
            },
        )

    @staticmethod
    def _reservation_path(reservation_id):
        return f"reservations/{UUID(str(reservation_id))}/"

    def get_reservation(self, reservation_id):
        return self._request(
            "GET",
            self._reservation_path(reservation_id),
        )

    def confirm(self, reservation_id):
        return self._request(
            "POST",
            self._reservation_path(reservation_id) + "confirm/",
            data={},
        )

    def release(self, reservation_id):
        return self._request(
            "POST",
            self._reservation_path(reservation_id) + "release/",
            data={},
        )
