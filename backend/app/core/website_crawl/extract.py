"""HTML → clean markdown helpers for website crawl pages."""

from __future__ import annotations

import re
from html import unescape
from typing import Optional, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Comment, Tag

from .config import ALLOWED_ASSET_HOSTS, ALLOWED_DOMAINS, EXCLUDED_DOMAINS


_NOISE_TAGS = {
    "script",
    "style",
    "noscript",
    "svg",
    "iframe",
    "canvas",
    "template",
    "form",
    "nav",
    "footer",
    "header",
    "aside",
}


def _normalize_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def classify_content_type(url: str, title: str = "") -> str:
    path = urlparse(url).path.lower()
    blob = f"{path} {title.lower()}"
    if any(token in blob for token in ("/store", "book", "bundle", "manual", "audacity", "altar")):
        return "book_resource"
    if any(
        token in blob
        for token in (
            "resource-of-the-month",
            "know-your-why",
            "abraham-accords",
            "sermon",
            "message",
            "video",
            "teaching",
        )
    ):
        return "teaching_media"
    if any(token in blob for token in ("visit", "service", "times", "expect", "location", "campus")):
        return "church_info"
    if any(token in blob for token in ("ministry", "about", "pastor", "belief", "contact", "event")):
        return "ministry_page"
    return "website_page"


def source_name_for_url(url: str, extension: str = ".md") -> str:
    parsed = urlparse(url)
    host = (parsed.netloc or "site").lower().removeprefix("www.")
    path = parsed.path.strip("/") or "home"
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "_", f"{host}__{path}")
    slug = re.sub(r"_+", "_", slug).strip("._")
    if len(slug) > 180:
        slug = slug[:180].rstrip("._")
    return f"web__{slug}{extension}"


def extract_title(soup: BeautifulSoup, fallback_url: str) -> str:
    for selector in ("h1", "title", 'meta[property="og:title"]'):
        if selector.startswith("meta"):
            tag = soup.select_one(selector)
            if tag and tag.get("content"):
                return _normalize_whitespace(unescape(tag["content"]))
        else:
            tag = soup.find(selector)
            if tag and tag.get_text(strip=True):
                return _normalize_whitespace(unescape(tag.get_text(" ", strip=True)))
    path = urlparse(fallback_url).path.strip("/") or "home"
    return path.replace("-", " ").replace("_", " ").title()


def _remove_noise(soup: BeautifulSoup) -> None:
    for tag_name in _NOISE_TAGS:
        for node in soup.find_all(tag_name):
            node.decompose()
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    # Cookie / consent / cart chrome often lives in these class/id fragments.
    noise_re = re.compile(
        r"(cookie|consent|cart|checkout|newsletter|social-share|share-buttons|breadcrumb)",
        re.I,
    )
    for node in list(soup.find_all(True)):
        if not isinstance(node, Tag):
            continue
        attrs_map = getattr(node, "attrs", None) or {}
        attrs = " ".join(
            [
                " ".join(attrs_map.get("class") or []),
                str(attrs_map.get("id") or ""),
                str(attrs_map.get("role") or ""),
            ]
        )
        if noise_re.search(attrs):
            node.decompose()


def _main_root(soup: BeautifulSoup) -> Tag:
    for selector in ("main", "article", '[role="main"]', "#content", ".content", "body"):
        node = soup.select_one(selector)
        if node:
            return node
    return soup


def _iter_text_blocks(root: Tag) -> list[str]:
    blocks: list[str] = []
    block_tags = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "td", "th", "figcaption"}
    for node in root.descendants:
        if not isinstance(node, Tag):
            continue
        if node.name not in block_tags:
            continue
        # Skip nested blocks that would double-count list/paragraph text.
        if any(parent.name in block_tags for parent in node.parents if isinstance(parent, Tag) and parent is not root):
            # Allow li/p inside larger containers but not nested p-in-p.
            if node.name == "p" and any(p.name == "p" for p in node.parents if isinstance(p, Tag)):
                continue
            if node.name.startswith("h") and any(
                p.name and p.name.startswith("h") for p in node.parents if isinstance(p, Tag)
            ):
                continue
        text = node.get_text(" ", strip=True)
        text = _normalize_whitespace(unescape(text))
        if not text:
            continue
        if node.name.startswith("h"):
            level = int(node.name[1])
            blocks.append(f'{"#" * min(level, 4)} {text}')
        elif node.name == "li":
            blocks.append(f"- {text}")
        else:
            blocks.append(text)
    if blocks:
        return blocks

    # Fallback: flatten all visible text.
    text = root.get_text("\n", strip=True)
    return [_normalize_whitespace(unescape(text))] if text.strip() else []


def dedupe_near_duplicate_lines(lines: list[str]) -> list[str]:
    """CMS themes often repeat nav/hero copy; drop exact consecutive + exact global dupes of short lines."""
    seen_short: set[str] = set()
    out: list[str] = []
    prev = None
    for line in lines:
        normalized = line.strip()
        if not normalized:
            continue
        if normalized == prev:
            continue
        key = normalized.lower()
        if len(normalized) < 80:
            if key in seen_short:
                continue
            seen_short.add(key)
        out.append(normalized)
        prev = normalized
    return out


def html_to_markdown(html: str, page_url: str, ministry_label: str) -> Tuple[str, str, str]:
    """
    Returns (title, content_type, markdown_body_with_header_metadata).
    """
    soup = BeautifulSoup(html, "html.parser")
    _remove_noise(soup)
    title = extract_title(soup, page_url)
    content_type = classify_content_type(page_url, title)
    root = _main_root(soup)
    lines = dedupe_near_duplicate_lines(_iter_text_blocks(root))
    body = "\n\n".join(lines)
    body = _normalize_whitespace(body)

    header = (
        f"# {title}\n\n"
        f"- Source URL: {page_url}\n"
        f"- Ministry: {ministry_label}\n"
        f"- Content type: {content_type}\n\n"
        f"{body}\n"
    )
    return title, content_type, header


def iter_page_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(base_url, href)
        urls.append(absolute.split("#", 1)[0])
    return urls


def iter_pdf_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href:
            continue
        absolute = urljoin(base_url, href).split("#", 1)[0]
        path = urlparse(absolute).path.lower()
        if path.endswith(".pdf"):
            urls.append(absolute)
    return urls


def host_allowed_for_page(url: str) -> bool:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    if host in EXCLUDED_DOMAINS or any(host.endswith("." + d) for d in EXCLUDED_DOMAINS):
        return False
    return host in ALLOWED_DOMAINS


def host_allowed_for_asset(url: str) -> bool:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    if host in ALLOWED_DOMAINS:
        return True
    return host in ALLOWED_ASSET_HOSTS


def is_probably_html_response(content_type: Optional[str], url: str) -> bool:
    if content_type:
        ct = content_type.lower()
        if "html" in ct or "xml" in ct or "text/plain" in ct:
            return True
        if "pdf" in ct or "image/" in ct or "javascript" in ct:
            return False
    path = urlparse(url).path.lower()
    return not path.endswith((".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".mp4", ".zip"))
