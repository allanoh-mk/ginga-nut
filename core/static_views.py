from django.conf import settings
from django.http import FileResponse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET


@require_GET
@cache_control(public=True, max_age=0, must_revalidate=True)
def site_stylesheet(request):
    stylesheet = settings.BASE_DIR / "static" / "css" / "kola.css"
    return FileResponse(stylesheet.open("rb"), content_type="text/css; charset=utf-8")
