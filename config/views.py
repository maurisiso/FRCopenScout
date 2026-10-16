import json

from django.conf import settings
from django.contrib.staticfiles import finders
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static


def home(request):
    return render(request, "home.html")


SW_VERSION = "v1"


def service_worker(request):
    path = finders.find("js/sw.js")
    with open(path, encoding="utf-8") as fh:
        body = fh.read()
    precache = [
        "/offline/",
        static("css/app.css"),
        static("js/htmx.min.js"),
        static("js/app.js"),
        static("js/scout.js"),
        static("img/icon.svg"),
    ]
    body = body.replace("__PRECACHE__", json.dumps(precache)).replace("__VERSION__", SW_VERSION)
    resp = HttpResponse(body, content_type="application/javascript")
    resp["Service-Worker-Allowed"] = "/"
    resp["Cache-Control"] = "no-cache"
    return resp


def manifest(request):
    return JsonResponse({
        "name": "FRC Open Scout",
        "short_name": "OpenScout",
        "start_url": "/dashboard/",
        "display": "standalone",
        "background_color": "#0b1220",
        "theme_color": "#0b1220",
        "icons": [{"src": static("img/icon.svg"), "sizes": "any", "type": "image/svg+xml", "purpose": "any"}],
    }, content_type="application/manifest+json")
