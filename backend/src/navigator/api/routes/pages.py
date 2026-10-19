"""Crawled pages and what each gives the search."""


from fastapi import APIRouter, HTTPException

from navigator.api.deps import Conn, PageRules
from navigator.ingest import pages
from navigator.models import (
    PageDetail,
    ResourcePage,
)

router = APIRouter()


@router.get("/api/pages")
def list_pages(conn: Conn, rules: PageRules) -> list[ResourcePage]:
    """Every crawled page with its score, by id (the UI sorts)."""
    return pages.list_pages(conn, rules)


@router.get("/api/pages/{page_id}")
def get_page(conn: Conn, rules: PageRules, page_id: int) -> PageDetail:
    """One page with the shown facts extracted from it."""
    found = pages.get_page(conn, rules, page_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return found
