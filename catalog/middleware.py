import logging
import time

from django.middleware.locale import LocaleMiddleware
from django.utils import translation
from django.utils.cache import patch_vary_headers


logger = logging.getLogger('django')


class ApiLocaleMiddleware(LocaleMiddleware):
    def process_response(self, request, response):
        if request.path_info.startswith('/api/'):
            patch_vary_headers(response, ('Accept-Language',))
            response.headers.setdefault(
                'Content-Language',
                translation.get_language(),
            )
            return response

        return super().process_response(request, response)


class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start_time = time.time()

        response = self.get_response(request)

        duration = time.time() - start_time
        logger.info(
            f'{request.method} {request.path} -> '
            f'{response.status_code} ({duration:.3f}s)'
        )

        return response