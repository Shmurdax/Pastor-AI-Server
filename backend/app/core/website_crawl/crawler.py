"""Bounded allowlist crawler for Nordins + sister ministry sites."""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import requests

from .config import (
    ALLOWED_SITES,
    DEFAULT_USER_AGENT,
    EXCLUDED_PATH_SUBSTRINGS,
    EXCLUDED_TITLE_EXACT,
    MAX_PAGES_PER_DOMAIN,
    MAX_PDFS_PER_DOMAIN,
    MIN_PAGE_TEXT_CHARS,
    REQUEST_TIMEOUT_S,
    SiteConfig,
)
from .extract import (
    host_allowed_for_asset,
    host_allowed_for_page,
    html_to_markdown,
    is_probably_html_response,
    iter_page_links,
    iter_pdf_links,
    source_name_for_url,
)

logger = logging.getLogger(__name__)

LogFn = Optional[Callable[[str], None]]


@dataclass
class CrawledPage:
    url: str
    domain: str
    ministry_label: str
    title: str
    content_type: str
    markdown: str
    source_name: str


@dataclass
class CrawledPdf:
    url: str
    domain: str
    ministry_label: str
    source_name: str
    content: bytes


@dataclass
class CrawlResult:
    pages: List[CrawledPage] = field(default_factory=list)
    pdfs: List[CrawledPdf] = field(default_factory=list)
    pages_fetched: int = 0
    pages_skipped: int = 0
    pages_failed: int = 0
    pdfs_fetched: int = 0
    pdfs_failed: int = 0
    domains_touched: Set[str] = field(default_factory=set)


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    # Drop query noise from CMS sort/filter params; keep empty query.
    return urlunparse((scheme, netloc, path, "", "", ""))


def path_is_excluded(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(token in path for token in EXCLUDED_PATH_SUBSTRINGS)


def _log(log_fn: LogFn, message: str) -> None:
    if log_fn:
        log_fn(message)
    logger.info(message)


class WebsiteCrawler:
    def __init__(
        self,
        *,
        session: Optional[requests.Session] = None,
        sites: Iterable[SiteConfig] = ALLOWED_SITES,
        delay_s: float = 0.35,
        log_fn: LogFn = None,
        respect_robots: bool = True,
    ):
        self.sites = list(sites)
        self.delay_s = delay_s
        self.log_fn = log_fn
        self.respect_robots = respect_robots
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        self._robots: Dict[str, Optional[RobotFileParser]] = {}

    def crawl(self) -> CrawlResult:
        result = CrawlResult()
        for site in self.sites:
            try:
                self._crawl_site(site, result)
            except Exception as exc:
                _log(self.log_fn, f"Domain crawl aborted for {site.domain}: {exc}")
                logger.exception("Domain crawl aborted for %s", site.domain)
        return result

    def _crawl_site(self, site: SiteConfig, result: CrawlResult) -> None:
        _log(self.log_fn, f"Starting crawl for {site.label} ({site.domain})")
        result.domains_touched.add(site.domain)

        queue: Deque[Tuple[str, int]] = deque()
        seen: Set[str] = set()
        pdf_seen: Set[str] = set()

        for seed in site.seed_urls:
            queue.append((normalize_url(seed), 0))
        for sitemap_url in site.sitemap_urls:
            for loc in self._fetch_sitemap_urls(sitemap_url):
                queue.append((normalize_url(loc), 0))

        pages_for_domain = 0
        pdfs_for_domain = 0

        while queue and pages_for_domain < MAX_PAGES_PER_DOMAIN:
            url, depth = queue.popleft()
            if url in seen:
                continue
            seen.add(url)

            if not host_allowed_for_page(url):
                result.pages_skipped += 1
                continue
            if urlparse(url).netloc.lower().removeprefix("www.") != site.domain:
                result.pages_skipped += 1
                continue
            if path_is_excluded(url):
                result.pages_skipped += 1
                continue
            if not self._robots_allows(url):
                result.pages_skipped += 1
                _log(self.log_fn, f"Skipped by robots.txt: {url}")
                continue

            time.sleep(self.delay_s)
            response = self._get(url)
            if response is None:
                result.pages_failed += 1
                continue

            content_type = response.headers.get("Content-Type", "")
            if not is_probably_html_response(content_type, url):
                result.pages_skipped += 1
                continue

            html = response.text
            try:
                title, content_type_label, markdown = html_to_markdown(html, url, site.label)
            except Exception as exc:
                result.pages_failed += 1
                _log(self.log_fn, f"Extract failed for {url}: {exc}")
                continue

            if title.strip().lower() in EXCLUDED_TITLE_EXACT:
                result.pages_skipped += 1
                _log(self.log_fn, f"Skipped auth/empty shell page: {url}")
                continue

            # Strip metadata header length estimate: require real body text.
            body_only = markdown.split("\n\n", 3)[-1] if "\n\n" in markdown else markdown
            if len(body_only) < MIN_PAGE_TEXT_CHARS:
                result.pages_skipped += 1
                _log(self.log_fn, f"Skipped thin page: {url}")
                continue

            page = CrawledPage(
                url=url,
                domain=site.domain,
                ministry_label=site.label,
                title=title,
                content_type=content_type_label,
                markdown=markdown,
                source_name=source_name_for_url(url, ".md"),
            )
            result.pages.append(page)
            result.pages_fetched += 1
            pages_for_domain += 1
            _log(self.log_fn, f"Fetched page ({pages_for_domain}): {url}")

            # Discover PDFs linked from this page.
            if pdfs_for_domain < MAX_PDFS_PER_DOMAIN:
                for pdf_url in iter_pdf_links(html, url):
                    pdf_url = normalize_url(pdf_url)
                    if pdf_url in pdf_seen:
                        continue
                    if not host_allowed_for_asset(pdf_url):
                        continue
                    if path_is_excluded(pdf_url):
                        continue
                    pdf_seen.add(pdf_url)
                    time.sleep(self.delay_s)
                    pdf_bytes = self._get_bytes(pdf_url)
                    if pdf_bytes is None:
                        result.pdfs_failed += 1
                        continue
                    if not pdf_bytes.startswith(b"%PDF"):
                        result.pdfs_failed += 1
                        continue
                    result.pdfs.append(
                        CrawledPdf(
                            url=pdf_url,
                            domain=site.domain,
                            ministry_label=site.label,
                            source_name=source_name_for_url(pdf_url, ".pdf"),
                            content=pdf_bytes,
                        )
                    )
                    result.pdfs_fetched += 1
                    pdfs_for_domain += 1
                    _log(self.log_fn, f"Fetched PDF: {pdf_url}")
                    if pdfs_for_domain >= MAX_PDFS_PER_DOMAIN:
                        break

            if depth >= site.max_depth:
                continue
            for link in iter_page_links(html, url):
                link = normalize_url(link)
                if link in seen:
                    continue
                if not host_allowed_for_page(link):
                    continue
                if urlparse(link).netloc.lower().removeprefix("www.") != site.domain:
                    continue
                if path_is_excluded(link):
                    continue
                queue.append((link, depth + 1))

        _log(
            self.log_fn,
            f"Finished {site.domain}: pages={pages_for_domain}, pdfs={pdfs_for_domain}",
        )

    def _fetch_sitemap_urls(self, sitemap_url: str) -> List[str]:
        response = self._get(sitemap_url)
        if response is None:
            return []
        text = response.text
        urls: List[str] = []
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            # Fallback: regex-ish loc scrape without full XML parse.
            for part in text.split("<loc>"):
                if "</loc>" in part:
                    urls.append(part.split("</loc>", 1)[0].strip())
            return urls

        # Handle urlset and sitemapindex (with or without namespace).
        tag = root.tag.lower()
        if tag.endswith("sitemapindex"):
            for loc in root.findall(".//{*}loc"):
                if loc.text:
                    child_urls = self._fetch_sitemap_urls(loc.text.strip())
                    urls.extend(child_urls)
            return urls

        for loc in root.findall(".//{*}loc"):
            if loc.text:
                urls.append(loc.text.strip())
        return urls

    def _robots_allows(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if host not in self._robots:
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            parser = RobotFileParser()
            try:
                response = self._get(robots_url)
                if response is None or response.status_code >= 400:
                    self._robots[host] = None
                else:
                    parser.parse(response.text.splitlines())
                    self._robots[host] = parser
            except Exception:
                self._robots[host] = None
        parser = self._robots.get(host)
        if parser is None:
            return True
        try:
            return parser.can_fetch(DEFAULT_USER_AGENT, url)
        except Exception:
            return True

    def _get(self, url: str) -> Optional[requests.Response]:
        try:
            response = self.session.get(url, timeout=REQUEST_TIMEOUT_S, allow_redirects=True)
            if response.status_code >= 400:
                _log(self.log_fn, f"HTTP {response.status_code} for {url}")
                return None
            return response
        except requests.RequestException as exc:
            _log(self.log_fn, f"Request failed for {url}: {exc}")
            return None

    def _get_bytes(self, url: str) -> Optional[bytes]:
        response = self._get(url)
        if response is None:
            return None
        return response.content
