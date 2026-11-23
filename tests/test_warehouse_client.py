import json
import logging
from unittest.mock import Mock
from uuid import uuid4

import pytest
import requests

from catalog.warehouse_client import (
    WarehouseAPIError,
    WarehouseAuthenticationError,
    WarehouseClient,
    WarehouseConfigurationError,
    WarehouseProtocolError,
    WarehouseUnavailable,
)

pytestmark = pytest.mark.unit

API_URL = "https://warehouse.example/api"
PASSWORD = "test-warehouse-password"
ACCESS_TOKEN = "test-access-token"
EMPTY_STOCK = {"count": 0, "results": []}


def make_response(status_code, data=None, *, raw=None):
    response = requests.Response()
    response.status_code = status_code
    response.encoding = "utf-8"
    response._content = raw if raw is not None else json.dumps(data).encode("utf-8")
    return response


def token_response(token=ACCESS_TOKEN):
    return make_response(
        200,
        {"access": token, "refresh": "test-refresh-token"},
    )


@pytest.fixture(autouse=True)
def warehouse_settings(settings):
    settings.WAREHOUSE_ENABLED = True
    settings.WAREHOUSE_API_URL = API_URL
    settings.WAREHOUSE_USERNAME = "test-bookshop"
    settings.WAREHOUSE_PASSWORD = PASSWORD
    settings.WAREHOUSE_CONNECT_TIMEOUT = 3.0
    settings.WAREHOUSE_READ_TIMEOUT = 10.0
    return settings


@pytest.fixture(autouse=True)
def http_session(monkeypatch):
    session = Mock(spec=requests.Session)
    monkeypatch.setattr(
        "catalog.warehouse_client.requests.Session",
        lambda: session,
    )
    return session


def test_stock_requests_reuse_token_without_logging_secrets(http_session, caplog):
    caplog.set_level(logging.INFO, logger="catalog.warehouse_client")
    http_session.request.side_effect = [
        token_response(),
        make_response(200, EMPTY_STOCK),
        make_response(200, EMPTY_STOCK),
    ]

    with WarehouseClient() as client:
        assert client.list_stock(external_book_id=101) == EMPTY_STOCK
        assert client.list_stock() == EMPTY_STOCK

    calls = http_session.request.call_args_list

    assert len(calls) == 3
    assert calls[0].args == ("POST", f"{API_URL}/token/")
    assert calls[0].kwargs["json"] == {
        "username": "test-bookshop",
        "password": PASSWORD,
    }
    assert "Authorization" not in calls[0].kwargs["headers"]

    assert calls[1].args == ("GET", f"{API_URL}/stock/")
    assert calls[1].kwargs["params"] == {
        "page": 1,
        "external_book_id": 101,
    }
    assert calls[2].kwargs["params"] == {"page": 1}

    for call in calls[1:]:
        assert call.kwargs["headers"]["Authorization"] == f"Bearer {ACCESS_TOKEN}"

    for call in calls:
        assert call.kwargs["timeout"] == (3.0, 10.0)
        assert call.kwargs["allow_redirects"] is False

    assert http_session.trust_env is False
    http_session.close.assert_called_once()

    assert "status=200" in caplog.text
    assert PASSWORD not in caplog.text
    assert ACCESS_TOKEN not in caplog.text
    assert "test-refresh-token" not in caplog.text


@pytest.mark.parametrize("status_code", [401, 403])
def test_rejected_login_stops_before_stock_request(http_session, status_code):
    http_session.request.side_effect = [
        make_response(status_code, {"detail": "Login rejected"}),
    ]

    with pytest.raises(WarehouseAuthenticationError):
        with WarehouseClient() as client:
            client.list_stock()

    assert http_session.request.call_count == 1
    http_session.close.assert_called_once()


def test_expired_token_triggers_one_new_login(http_session):
    http_session.request.side_effect = [
        token_response("expired-access-token"),
        make_response(401, {"detail": "Token expired"}),
        token_response("renewed-access-token"),
        make_response(200, EMPTY_STOCK),
    ]

    with WarehouseClient() as client:
        assert client.list_stock() == EMPTY_STOCK

    calls = http_session.request.call_args_list

    assert len(calls) == 4
    assert calls[2].args == ("POST", f"{API_URL}/token/")
    assert calls[1].kwargs["headers"]["Authorization"] == (
        "Bearer expired-access-token"
    )
    assert calls[3].kwargs["headers"]["Authorization"] == (
        "Bearer renewed-access-token"
    )


def test_repeated_401_does_not_create_an_infinite_retry_loop(http_session):
    http_session.request.side_effect = [
        token_response(),
        make_response(401, {}),
        token_response("replacement-token"),
        make_response(401, {}),
    ]

    with pytest.raises(WarehouseAuthenticationError):
        with WarehouseClient() as client:
            client.list_stock()

    assert http_session.request.call_count == 4
    http_session.close.assert_called_once()


@pytest.mark.parametrize(
    ("operation", "http_method", "suffix", "state"),
    [
        ("reserve", "POST", "", "pending"),
        ("get_reservation", "GET", "", "pending"),
        ("confirm", "POST", "confirm/", "confirmed"),
        ("release", "POST", "release/", "released"),
    ],
)
def test_reservation_requests_use_correct_routes(
    http_session, operation, http_method, suffix, state
):
    reservation_id = str(uuid4())
    items = [{"external_book_id": 101, "quantity": 2}]
    body = {
        "id": reservation_id,
        "external_order_id": 1001,
        "status": state,
        "items": items,
    }

    http_session.request.side_effect = [
        token_response(),
        make_response(201 if operation == "reserve" else 200, body),
    ]

    with WarehouseClient() as client:
        if operation == "reserve":
            result = client.reserve(external_order_id=1001, items=items)
            expected_url = f"{API_URL}/reservations/"
        else:
            result = getattr(client, operation)(reservation_id)
            expected_url = f"{API_URL}/reservations/{reservation_id}/{suffix}"

    assert result == body
    request = http_session.request.call_args
    assert request.args == (http_method, expected_url)

    if operation == "reserve":
        assert request.kwargs["json"] == {
            "external_order_id": 1001,
            "items": items,
        }


@pytest.mark.parametrize(
    ("status_code", "exception_type"),
    [
        (400, WarehouseAPIError),
        (404, WarehouseAPIError),
        (409, WarehouseAPIError),
        (403, WarehouseAuthenticationError),
        (429, WarehouseUnavailable),
        (503, WarehouseUnavailable),
        (302, WarehouseAPIError),
    ],
)
def test_api_errors_are_reported_without_repeating_reservation(
    http_session, status_code, exception_type
):
    http_session.request.side_effect = [
        token_response(),
        make_response(status_code, {"detail": "Request rejected"}),
    ]

    with pytest.raises(exception_type) as error:
        with WarehouseClient() as client:
            client.reserve(
                external_order_id=1001,
                items=[{"external_book_id": 101, "quantity": 2}],
            )

    assert http_session.request.call_count == 2

    if exception_type is WarehouseAPIError:
        assert error.value.status_code == status_code


@pytest.mark.parametrize(
    "exception_type",
    [requests.Timeout, requests.ConnectionError],
)
def test_network_failure_is_not_retried_or_logged_with_sensitive_details(
    http_session, exception_type, caplog
):
    http_session.request.side_effect = [
        token_response(),
        exception_type("do-not-log-this-sensitive-message"),
    ]

    with pytest.raises(WarehouseUnavailable):
        with WarehouseClient() as client:
            client.reserve(
                external_order_id=1001,
                items=[{"external_book_id": 101, "quantity": 2}],
            )

    assert http_session.request.call_count == 2
    http_session.close.assert_called_once()
    assert "Warehouse connection failed" in caplog.text
    assert "do-not-log-this-sensitive-message" not in caplog.text


@pytest.mark.parametrize(
    "raw",
    [
        b"not valid JSON",
        b"[]",
        b'{"count": 0, "results": {}}',
        b'{"count": -1, "results": []}',
    ],
)
def test_invalid_stock_response_raises_protocol_error(http_session, raw):
    http_session.request.side_effect = [
        token_response(),
        make_response(200, raw=raw),
    ]

    with pytest.raises(WarehouseProtocolError):
        with WarehouseClient() as client:
            client.list_stock()


@pytest.mark.parametrize("token", [None, "", "token with spaces"])
def test_invalid_access_token_stops_the_request(http_session, token):
    http_session.request.side_effect = [token_response(token)]

    with pytest.raises(WarehouseProtocolError):
        with WarehouseClient() as client:
            client.list_stock()

    assert http_session.request.call_count == 1


@pytest.mark.parametrize(
    ("setting_name", "value"),
    [
        ("WAREHOUSE_ENABLED", False),
        ("WAREHOUSE_PASSWORD", ""),
        ("WAREHOUSE_API_URL", "ftp://warehouse.example/api"),
        ("WAREHOUSE_READ_TIMEOUT", 0),
    ],
)
def test_invalid_configuration_prevents_network_requests(
    warehouse_settings, http_session, setting_name, value
):
    setattr(warehouse_settings, setting_name, value)

    with pytest.raises(WarehouseConfigurationError):
        WarehouseClient()

    http_session.request.assert_not_called()
