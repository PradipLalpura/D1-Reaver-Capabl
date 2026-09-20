"""robots.txt compliance gate. Every fetch path goes through allowed(); disallowed → skip + reason."""
from __future__ import annotations

import urllib.parse
import urllib.robotparser

from connectors import http
from data import cache

TTL = 7 * 24 * 3600


def allowed(url: str) -> tuple[bool, str]:
    """Fail-open on robots-fetch failure (standard practice), with the reason recorded."""
    try:
        parts = urllib.parse.urlparse(url)
        robots_url = parts.scheme + "://" + parts.hostname + "/robots.txt"
    except Exception:
        return False, "unparseable URL"
    key = cache.make_key("robots", robots_url)
    rules = cache.get(key)
    if rules is None:
        try:
            res = http.call(robots_url)
        except ValueError as exc:
            return False, "blocked: " + str(exc).lower()
        if res["http"] != 200:
            return True, "robots.txt unreachable; fetched with note"
        rules = res["body"].decode("utf-8", "replace")
        cache.put(key, rules, TTL)
    assert isinstance(rules, str)
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(rules.splitlines())
    if parser.can_fetch("*", url):
        return True, "allowed"
    return False, "disallowed by robots.txt"
