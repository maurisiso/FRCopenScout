import re

from django import template
from django.utils.html import format_html

register = template.Library()


@register.filter
def get_item(d, key):
    if d is None:
        return None
    try:
        return d.get(key)
    except AttributeError:
        return None


@register.filter
def num(value, digits=1):
    """Format a number, or show a dash when it's missing."""
    if value is None or value == "":
        return "—"
    try:
        return f"{float(value):.{int(digits)}f}"
    except (TypeError, ValueError):
        return value


@register.filter
def pct(value):
    if value is None:
        return "—"
    return f"{float(value) * 100:.0f}%"


@register.simple_tag
def team_chip(number, color="", us=None):
    cls = f"team-chip {color}" + (" us" if us and int(number) == int(us) else "")
    return format_html('<span class="{}">{}</span>', cls, number)


@register.filter
def bar_width(value, maximum):
    try:
        return max(0, min(100, round(float(value) / float(maximum) * 100)))
    except (TypeError, ValueError, ZeroDivisionError):
        return 0


@register.filter
def pretty_key(key):
    """'auto_fuel_points' -> 'Auto fuel points'"""
    text = str(key).replace("_", " ").strip()
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)  # camelCase -> camel Case (TBA breakdowns)
    return text[:1].upper() + text[1:].lower() if text else text


@register.filter
def youtube_url(video):
    if isinstance(video, dict) and video.get("type") == "youtube" and video.get("key"):
        return f"https://www.youtube.com/watch?v={video['key']}"
    return ""
