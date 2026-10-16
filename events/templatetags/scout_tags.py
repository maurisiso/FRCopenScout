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


_AVATAR_COLORS = ["#1f5fd6", "#d7263d", "#138a52", "#b46b00", "#6a3fd1", "#0f8b8d", "#c2410c", "#4b5563"]


@register.simple_tag
def team_avatar(frc_team=None, number=None, size=28):
    """TBA avatar as an inline image, or a coloured badge with the team number if there is none."""
    number = number or getattr(frc_team, "number", None) or "?"
    avatar = getattr(frc_team, "avatar", "") if frc_team else ""
    if avatar:
        return format_html(
            '<img class="avatar" src="data:image/png;base64,{}" width="{}" height="{}" alt="">', avatar, size, size
        )
    color = _AVATAR_COLORS[int(number) % len(_AVATAR_COLORS)] if str(number).isdigit() else "#4b5563"
    label = str(number)[-2:]
    return format_html(
        '<span class="avatar avatar-fallback" style="width:{}px;height:{}px;background:{};font-size:{}px">{}</span>',
        size, size, color, max(9, int(size) // 2 - 2), label,
    )
