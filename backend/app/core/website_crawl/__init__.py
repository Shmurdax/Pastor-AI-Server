"""Allowlisted website crawl → markdown → RAG ingest for Pastor Don ministries."""

__all__ = ["CrawlIngestResult", "run_website_crawl_and_ingest"]


def __getattr__(name: str):
    if name in {"CrawlIngestResult", "run_website_crawl_and_ingest"}:
        from .pipeline import CrawlIngestResult, run_website_crawl_and_ingest

        return {
            "CrawlIngestResult": CrawlIngestResult,
            "run_website_crawl_and_ingest": run_website_crawl_and_ingest,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
