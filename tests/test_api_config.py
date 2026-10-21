from datetime import timedelta

import pytest
from django.urls import reverse
from rest_framework.throttling import SimpleRateThrottle
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken


pytestmark = pytest.mark.django_db


def test_api_token_obtain_returns_working_tokens(api_client, user, order):
    # Generated with AI, reviewed and modified
    response = api_client.post(
        reverse('api:token_obtain_pair'),
        {
            'username': user.username,
            'password': 'TestPass123!',
        },
        format='json',
    )

    assert response.status_code == 200

    data = response.json()
    access = AccessToken(data['access'])
    refresh = RefreshToken(data['refresh'])

    assert str(access['user_id']) == str(user.pk)
    assert str(refresh['user_id']) == str(user.pk)

    api_client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {data['access']}"
    )
    orders_response = api_client.get(reverse('api:order-list'))

    assert orders_response.status_code == 200
    assert [
        item['id'] for item in orders_response.json()['results']
    ] == [order.pk]


def test_api_token_obtain_rejects_wrong_password(api_client, user):
    # Generated with AI, reviewed and modified
    response = api_client.post(
        reverse('api:token_obtain_pair'),
        {
            'username': user.username,
            'password': 'WrongPassword123!',
        },
        format='json',
    )

    assert response.status_code == 401
    assert 'access' not in response.json()


def test_api_token_refresh_returns_working_access_token(
    api_client, user, order
):
    # Generated with AI, reviewed and modified
    refresh = RefreshToken.for_user(user)

    response = api_client.post(
        reverse('api:token_refresh'),
        {'refresh': str(refresh)},
        format='json',
    )

    assert response.status_code == 200

    access = response.json()['access']
    api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

    orders_response = api_client.get(reverse('api:order-list'))

    assert orders_response.status_code == 200
    assert [
        item['id'] for item in orders_response.json()['results']
    ] == [order.pk]


def test_api_token_verify_accepts_valid_access_token(api_client, user):
    # Generated with AI, reviewed and modified
    access = AccessToken.for_user(user)

    response = api_client.post(
        reverse('api:token_verify'),
        {'token': str(access)},
        format='json',
    )

    assert response.status_code == 200
    assert response.json() == {}


@pytest.mark.parametrize(
    'url_name, field_name',
    [
        ('api:token_refresh', 'refresh'),
        ('api:token_verify', 'token'),
    ],
)
def test_api_token_endpoints_reject_invalid_tokens(
    api_client, url_name, field_name
):
    # Generated with AI, reviewed and modified
    response = api_client.post(
        reverse(url_name),
        {field_name: 'not-a-jwt'},
        format='json',
    )

    assert response.status_code == 401


def test_api_refresh_rejects_access_token(api_client, user):
    # Generated with AI, reviewed and modified
    access = AccessToken.for_user(user)

    response = api_client.post(
        reverse('api:token_refresh'),
        {'refresh': str(access)},
        format='json',
    )

    assert response.status_code == 401


def test_api_rejects_expired_access_token(api_client, user):
    # Generated with AI, reviewed and modified
    access = AccessToken.for_user(user)
    access.set_exp(lifetime=timedelta(seconds=-60))

    api_client.credentials(
        HTTP_AUTHORIZATION=f'Bearer {access}'
    )

    response = api_client.get(reverse('api:order-list'))

    assert response.status_code == 401


def test_api_anonymous_requests_are_throttled(api_client, monkeypatch):
    # Generated with AI, reviewed and modified
    monkeypatch.setattr(
        SimpleRateThrottle,
        'THROTTLE_RATES',
        {
            **SimpleRateThrottle.THROTTLE_RATES,
            'anon': '2/min',
        },
    )

    responses = [
        api_client.get(reverse('api:book-list'))
        for _ in range(3)
    ]

    assert [
        response.status_code for response in responses
    ] == [200, 200, 429]
    assert int(responses[-1]['Retry-After']) > 0


def test_api_authenticated_requests_are_throttled(
    auth_api_client, monkeypatch
):
    # Generated with AI, reviewed and modified
    monkeypatch.setattr(
        SimpleRateThrottle,
        'THROTTLE_RATES',
        {
            **SimpleRateThrottle.THROTTLE_RATES,
            'user': '2/min',
        },
    )

    responses = [
        auth_api_client.get(reverse('api:order-list'))
        for _ in range(3)
    ]

    assert [
        response.status_code for response in responses
    ] == [200, 200, 429]
    assert int(responses[-1]['Retry-After']) > 0


def test_api_token_obtain_is_throttled(api_client, user, monkeypatch):
    # Generated with AI, reviewed and modified
    monkeypatch.setattr(
        SimpleRateThrottle,
        'THROTTLE_RATES',
        {
            **SimpleRateThrottle.THROTTLE_RATES,
            'auth': '2/min',
        },
    )

    responses = [
        api_client.post(
            reverse('api:token_obtain_pair'),
            {
                'username': user.username,
                'password': 'WrongPassword123!',
            },
            format='json',
        )
        for _ in range(3)
    ]

    assert [
        response.status_code for response in responses
    ] == [401, 401, 429]
    assert int(responses[-1]['Retry-After']) > 0


@pytest.mark.parametrize(
    'origin, allowed',
    [
        ('http://localhost:3000', True),
        ('https://untrusted.example', False),
    ],
)
def test_api_cors_respects_allowed_origins(
    api_client, settings, origin, allowed
):
    # Generated with AI, reviewed and modified
    settings.CORS_ALLOWED_ORIGINS = ['http://localhost:3000']
    settings.CORS_ALLOW_ALL_ORIGINS = False
    settings.CORS_ALLOWED_ORIGIN_REGEXES = []

    response = api_client.get(
        reverse('api:book-list'),
        HTTP_ORIGIN=origin,
    )

    assert response.status_code == 200

    if allowed:
        assert response['Access-Control-Allow-Origin'] == origin
    else:
        assert 'Access-Control-Allow-Origin' not in response.headers


def test_api_cors_preflight_allows_authorization_header(
    api_client, settings
):
    # Generated with AI, reviewed and modified
    origin = 'http://localhost:3000'
    settings.CORS_ALLOWED_ORIGINS = [origin]
    settings.CORS_ALLOW_ALL_ORIGINS = False

    response = api_client.options(
        reverse('api:cart-list'),
        HTTP_ORIGIN=origin,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD='POST',
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS='authorization,content-type',
    )

    assert response.status_code == 200
    assert response['Access-Control-Allow-Origin'] == origin

    allowed_methods = {
        method.strip()
        for method in response['Access-Control-Allow-Methods'].split(',')
    }
    allowed_headers = {
        header.strip().lower()
        for header in response['Access-Control-Allow-Headers'].split(',')
    }

    assert 'POST' in allowed_methods
    assert {'authorization', 'content-type'} <= allowed_headers


def test_api_docs_are_public(api_client):
    # Generated with AI, reviewed and modified
    response = api_client.get(reverse('api:docs'))

    assert response.status_code == 200
    assert b'SwaggerUIBundle' in response.content


def test_api_schema_contains_resources_and_jwt_authentication(api_client):
    # Generated with AI, reviewed and modified
    response = api_client.get(
        reverse('api:schema'),
        HTTP_ACCEPT='application/vnd.oai.openapi+json',
    )

    assert response.status_code == 200

    schema = response.json()
    expected_paths = {
        '/api/books/',
        '/api/categories/',
        '/api/orders/',
        '/api/cart/',
        '/api/token/',
        '/api/token/refresh/',
        '/api/token/verify/',
    }

    assert expected_paths <= set(schema['paths'])

    security_schemes = schema['components']['securitySchemes']

    assert any(
        scheme.get('type') == 'http'
        and scheme.get('scheme') == 'bearer'
        for scheme in security_schemes.values()
    )