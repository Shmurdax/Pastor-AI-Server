"""Allowlist, seeds, and path filters for the Nordins / ministry website crawl."""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Tuple


@dataclass(frozen=True)
class SiteConfig:
    domain: str
    label: str
    seed_urls: Tuple[str, ...]
    # Prefer sitemap discovery when available.
    sitemap_urls: Tuple[str, ...] = ()
    # Max same-domain link hops beyond seeds/sitemap (0 = sitemap/seeds only).
    max_depth: int = 1


# Domains linked from thenordins.org/ministries (plus primary site).
# Sites that are currently down / Cloudflare-blocked stay listed so future crawls pick them up.
ALLOWED_SITES: Tuple[SiteConfig, ...] = (
    SiteConfig(
        domain="thenordins.org",
        label="The Nordins",
        seed_urls=("https://thenordins.org/",),
        sitemap_urls=("https://thenordins.org/sitemap.xml",),
        max_depth=1,
    ),
    SiteConfig(
        domain="myct.church",
        label="Community Transformation Church",
        seed_urls=("https://myct.church/",),
        sitemap_urls=("https://myct.church/sitemap.xml",),
        max_depth=1,
    ),
    SiteConfig(
        domain="mycthouston.org",
        label="Community Transformation Church - Houston",
        seed_urls=("https://mycthouston.org/", "https://mycthouston.org/visit"),
        sitemap_urls=("https://mycthouston.org/sitemap.xml",),
        max_depth=1,
    ),
    SiteConfig(
        domain="gmnonline.org",
        label="Global Ministries Network",
        seed_urls=("https://gmnonline.org/",),
        sitemap_urls=("https://gmnonline.org/sitemap.xml",),
        max_depth=1,
    ),
    SiteConfig(
        domain="empowermentconf.com",
        label="Empowerment Conference",
        seed_urls=("https://empowermentconf.com/",),
        sitemap_urls=("https://empowermentconf.com/sitemap.xml",),
        max_depth=1,
    ),
    SiteConfig(
        domain="homeofhopetexas.org",
        label="Home of Hope Texas",
        seed_urls=("https://homeofhopetexas.org/",),
        sitemap_urls=("https://homeofhopetexas.org/sitemap.xml",),
        max_depth=1,
    ),
    SiteConfig(
        domain="projecthoperc.com",
        label="Project Hope",
        seed_urls=("https://projecthoperc.com/",),
        sitemap_urls=("https://projecthoperc.com/sitemap.xml",),
        max_depth=1,
    ),
    SiteConfig(
        domain="projecthouston.org",
        label="Project Houston",
        seed_urls=("https://projecthouston.org/",),
        sitemap_urls=("https://projecthouston.org/sitemap.xml",),
        max_depth=1,
    ),
    SiteConfig(
        domain="savinggracewh.com",
        label="Saving Grace",
        seed_urls=("https://savinggracewh.com/",),
        sitemap_urls=("https://savinggracewh.com/sitemap.xml",),
        max_depth=1,
    ),
    SiteConfig(
        domain="mountainsidehideaway.org",
        label="Mountainside Hideaway",
        seed_urls=("https://mountainsidehideaway.org/",),
        sitemap_urls=("https://mountainsidehideaway.org/sitemap.xml",),
        max_depth=1,
    ),
    SiteConfig(
        domain="tinyescapes.org",
        label="Tiny Escapes",
        seed_urls=("https://tinyescapes.org/",),
        sitemap_urls=("https://tinyescapes.org/sitemap.xml",),
        max_depth=1,
    ),
    SiteConfig(
        domain="texcamps.com",
        label="TexCamps",
        seed_urls=("https://texcamps.com/",),
        sitemap_urls=("https://texcamps.com/sitemap.xml",),
        max_depth=1,
    ),
    SiteConfig(
        domain="nordinhomes.com",
        label="Nordin Homes",
        seed_urls=("https://nordinhomes.com/",),
        sitemap_urls=("https://nordinhomes.com/sitemap.xml",),
        max_depth=1,
    ),
)

ALLOWED_DOMAINS: FrozenSet[str] = frozenset(site.domain for site in ALLOWED_SITES)

# CDN hosts that may serve public teaching PDFs linked from ministry pages.
ALLOWED_ASSET_HOSTS: FrozenSet[str] = frozenset(
    {
        "content.app-sources.com",
        "static.web-repository.com",
    }
)

# Path substrings / patterns that are never crawled (cart, admin, form confirmations, social).
EXCLUDED_PATH_SUBSTRINGS: Tuple[str, ...] = (
    "/login",
    "/signin",
    "/sign-in",
    "/forgotpassword",
    "/forgot-password",
    "/cart",
    "/checkout",
    "/admin",
    "/account",
    "/wp-admin",
    "/wp-login",
    "/sort/",
    "/range/",
    "/search/",
    "/var/",
    "/sub/",
    "thank-you",
    "thank_you",
    "thankyou",
    "-completed",
    "registration-closed",
    "scholarship-approved",
    "booking-thank-you",
    "we-can-t-wait-to-see-you",
    "events-copy",
    "-forms",
    "forms-meeting",
    "credapp",  # credential application flows
    "empowerment-plus-testing",
    "test-campus-map",
    "resource-of-the-month-download",  # gated download wall
)

# Page titles that indicate an auth wall / empty shell rather than public content.
EXCLUDED_TITLE_EXACT: FrozenSet[str] = frozenset(
    {
        "log in",
        "login",
        "sign in",
        "signin",
        "forgot password?",
        "forgot password",
        "reset password",
    }
)

# Social / chat platforms — out of scope for now.
EXCLUDED_DOMAINS: FrozenSet[str] = frozenset(
    {
        "facebook.com",
        "www.facebook.com",
        "m.facebook.com",
        "instagram.com",
        "www.instagram.com",
        "twitter.com",
        "x.com",
        "www.x.com",
        "youtube.com",
        "www.youtube.com",
        "youtu.be",
        "tiktok.com",
        "www.tiktok.com",
        "linkedin.com",
        "www.linkedin.com",
    }
)

DEFAULT_USER_AGENT = (
    "PastorAIWebsiteCrawler/1.0 (+https://thenordins.org; ministry knowledge ingest; contact info@thenordins.org)"
)

REQUEST_TIMEOUT_S = 30
MAX_PAGES_PER_DOMAIN = 80
MAX_PDFS_PER_DOMAIN = 15
MIN_PAGE_TEXT_CHARS = 120
