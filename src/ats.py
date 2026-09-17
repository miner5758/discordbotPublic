"""Fetch postings straight from the applicant-tracking system's public API.

Careers pages on Greenhouse, Ashby and Lever are JavaScript shells that block fetchers,
but every one of them backs onto an unauthenticated JSON API that returns the full
posting. Resolving a URL here gives Gemini the complete text without touching the page.
"""

import html
import logging
import re
from urllib.parse import parse_qs, urlparse

import requests

log = logging.getLogger(__name__)

TIMEOUT = 10
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36",
    "Accept": "text/html,application/json",
}

# Prefixes companies bolt onto their careers domain: careers.withwaymo.com -> waymo.
DOMAIN_PREFIXES = ("with", "join", "go", "work", "get", "try", "at", "the")

GREENHOUSE_TOKEN_IN_HTML = (
    re.compile(r"greenhouse\.io/v1/boards/([A-Za-z0-9_-]+)"),
    re.compile(r"greenhouse\.io/embed/job_(?:board|app)\?for=([A-Za-z0-9_-]+)"),
    re.compile(r"(?:boards|job-boards)\.greenhouse\.io/([A-Za-z0-9_-]+)"),
)


def strip_tags(text):
    # Greenhouse entity-escapes its HTML, so unescape before looking for tags.
    text = html.unescape(text)
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def get(url, **kwargs):
    try:
        return requests.get(url, headers=HEADERS, timeout=TIMEOUT, **kwargs)
    except requests.RequestException as error:
        log.debug("ATS request failed for %s: %s", url, error)
        return None


# --- Greenhouse ---


def greenhouse_job_id(parts):
    jid = parse_qs(parts.query).get("gh_jid", [None])[0]
    if jid and jid.isdigit():
        return jid
    match = re.search(r"/jobs/(\d{7,})", parts.path)
    return match.group(1) if match else None


def greenhouse_token_candidates(url, parts):
    # Direct greenhouse.io URLs carry the token in the path or the ?for= param.
    if parts.netloc.endswith("greenhouse.io"):
        match = re.match(r"/([A-Za-z0-9_-]+)/jobs/", parts.path)
        if match:
            yield match.group(1)
        token = parse_qs(parts.query).get("for", [None])[0]
        if token:
            yield token
        return

    # Custom careers domains usually reference the board in their page source.
    response = get(url)
    if response is not None and response.ok:
        found = []
        for pattern in GREENHOUSE_TOKEN_IN_HTML:
            found.extend(pattern.findall(response.text))
        for token in dict.fromkeys(found):
            if token not in ("embed", "v1"):
                yield token

    # Otherwise guess from the domain name.
    labels = parts.netloc.lower().split(".")
    base = labels[-2] if len(labels) >= 2 else labels[0]
    yield base
    for prefix in DOMAIN_PREFIXES:
        if base.startswith(prefix) and len(base) > len(prefix) + 2:
            yield base[len(prefix) :]


def greenhouse(url, parts):
    jid = greenhouse_job_id(parts)
    if not jid:
        return None
    tried = set()
    for token in greenhouse_token_candidates(url, parts):
        if token in tried:
            continue
        tried.add(token)
        response = get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{jid}")
        if response is None or not response.ok:
            continue
        job = response.json()
        return {
            "system": "Greenhouse",
            "title": job.get("title"),
            "location": (job.get("location") or {}).get("name"),
            "text": strip_tags(job.get("content", "")),
        }
    return None


# --- Ashby ---


def ashby(url, parts):
    match = re.match(r"/([A-Za-z0-9_-]+)/([0-9a-f-]{36})", parts.path)
    if not match:
        return None
    company, job_id = match.groups()
    response = get(f"https://api.ashbyhq.com/posting-api/job-board/{company}")
    if response is None or not response.ok:
        return None
    for job in response.json().get("jobs", []):
        if job.get("id") == job_id:
            return {
                "system": "Ashby",
                "title": job.get("title"),
                "location": job.get("location"),
                "text": strip_tags(job.get("descriptionHtml") or job.get("descriptionPlain") or ""),
            }
    return None


# --- Lever ---


def lever(url, parts):
    match = re.match(r"/([A-Za-z0-9_-]+)/([0-9a-f-]{36})", parts.path)
    if not match:
        return None
    company, job_id = match.groups()
    response = get(f"https://api.lever.co/v0/postings/{company}/{job_id}")
    if response is None or not response.ok:
        return None
    job = response.json()
    return {
        "system": "Lever",
        "title": job.get("text"),
        "location": (job.get("categories") or {}).get("location"),
        "text": job.get("descriptionPlain") or strip_tags(job.get("description", "")),
    }


# --- entry point ---


def resolve(url):
    """Return {"system", "title", "location", "text"} or None if the URL is not on a
    recognised system or the posting could not be fetched."""
    parts = urlparse(url if "://" in url else "https://" + url)
    host = parts.netloc.lower()
    try:
        if "ashbyhq.com" in host:
            return ashby(url, parts)
        if "lever.co" in host:
            return lever(url, parts)
        return greenhouse(url, parts)
    except (ValueError, KeyError, TypeError) as error:
        log.warning("ATS resolve failed for %s: %s", url, error)
        return None
