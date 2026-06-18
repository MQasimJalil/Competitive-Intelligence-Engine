import re
from collections.abc import Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.schemas import BusinessCategory, CandidateSource, CrawlPlan, PageCandidate
from app.scrapers.domain import is_same_site_url, validate_public_url

PAGE_CATEGORIES = {
    "positioning": (
        "home",
        "why",
        "overview",
        "about",
        "our story",
        "company",
        "mission",
        "who we are",
    ),
    "pricing_packaging": ("pricing", "plans", "packages"),
    "products_modules": (
        "product",
        "platform",
        "module",
        "suite",
        "add-on",
        "addon",
        "shop",
        "shoes",
        "apparel",
        "clothing",
        "equipment",
        "men",
        "women",
        "kids",
        "agent",
        "models",
        "portfolio",
    ),
    "capabilities": ("features", "capabilities", "automation", "analytics", "workflow"),
    "solutions_use_cases": (
        "solutions",
        "use-cases",
        "use cases",
        "industries",
        "industry",
        "roles",
        "teams",
        "customers like you",
    ),
    "target_segments": ("enterprise", "small business", "startup", "agencies", "teams"),
    "proof": ("customers", "case-studies", "case studies", "testimonials", "reviews"),
    "sales_motion": (
        "demo",
        "contact sales",
        "get started",
        "signup",
        "sign up",
        "membership",
        "member benefits",
        "loyalty",
        "rewards",
    ),
    "integrations_ecosystem": ("integrations", "apps", "marketplace", "partners", "api"),
    "trust_compliance": ("security", "trust", "compliance", "soc 2", "gdpr", "hipaa"),
    "technical_depth": (
        "docs",
        "developers",
        "api",
        "documentation",
        "research",
        "papers",
        "training",
    ),
    "recent_moves": (
        "blog",
        "changelog",
        "release",
        "releases",
        "release notes",
        "news",
        "webinars",
    ),
    "hiring_signals": ("careers", "jobs", "join us", "open roles"),
}

PATH_CATEGORY_HINTS = {
    "pricing_packaging": ("/pricing", "/plans", "/packages"),
    "products_modules": (
        "/product",
        "/products",
        "/platform",
        "/modules",
        "/suite",
        "/shop",
        "/men",
        "/women",
        "/kids",
        "/shoes",
        "/apparel",
        "/equipment",
    ),
    "positioning": ("/about", "/our-story", "/mission", "/who-we-are"),
    "capabilities": ("/features", "/capabilities"),
    "solutions_use_cases": ("/solutions", "/use-cases", "/industries"),
    "target_segments": ("/enterprise", "/small-business", "/startups", "/agencies"),
    "proof": ("/customers", "/case-studies", "/testimonials"),
    "integrations_ecosystem": ("/integrations", "/marketplace", "/apps", "/partners"),
    "trust_compliance": ("/security", "/trust", "/compliance"),
    "technical_depth": ("/docs", "/developers", "/api", "/research", "/papers"),
    "recent_moves": ("/changelog", "/release", "/releases", "/release-notes", "/blog", "/news"),
    "hiring_signals": ("/careers", "/jobs"),
}

EXACT_PATH_CATEGORY_HINTS = {
    "products_modules": ("/releases",),
}

CATEGORY_PRIORITIES = {
    "pricing_packaging": 120,
    "products_modules": 110,
    "solutions_use_cases": 100,
    "proof": 95,
    "integrations_ecosystem": 90,
    "trust_compliance": 85,
    "capabilities": 80,
    "target_segments": 70,
    "technical_depth": 65,
    "recent_moves": 60,
    "hiring_signals": 55,
    "sales_motion": 35,
    "positioning": 30,
}

EXCLUDED_PATH_PARTS = (
    "/login",
    "/log-in",
    "/signin",
    "/sign-in",
    "/signup",
    "/sign-up",
    "/register",
    "/cart",
    "/checkout",
    "/search",
    "/privacy",
    "/terms",
    "/cookie",
    "/cookies",
    "/dpa",
    "/subprocessors",
    "/tag/",
    "/tags/",
    "/author/",
    "/page/",
)

NON_CRAWL_PRIMARY_CATEGORIES: set[str] = set()


def discover_relevant_links(html: str, base_url: str) -> dict[str, list[str]]:
    discovered: dict[str, list[str]] = {key: [] for key in PAGE_CATEGORIES}
    for candidate in discover_homepage_candidates(html, base_url):
        for category in candidate.matched_categories:
            url = str(candidate.url)
            if url not in discovered[category]:
                discovered[category].append(url)
    return discovered


def discover_homepage_candidates(html: str, base_url: str) -> list[PageCandidate]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[PageCandidate] = []
    for anchor in soup.find_all("a", href=True):
        candidate = build_page_candidate(
            url=urljoin(base_url, anchor["href"]),
            base_url=base_url,
            source=CandidateSource.HOMEPAGE_LINK,
            anchor_text=anchor.get_text(" ", strip=True),
        )
        if candidate:
            candidates.append(candidate)
    return _deduplicate_candidates(candidates)


def discover_sitemap_candidates(urls: Iterable[str], base_url: str) -> list[PageCandidate]:
    candidates = [
        candidate
        for url in urls
        if (
            candidate := build_page_candidate(
                url=url,
                base_url=base_url,
                source=CandidateSource.SITEMAP,
            )
        )
    ]
    return _deduplicate_candidates(candidates)


def build_page_candidate(
    *,
    url: str,
    base_url: str,
    source: CandidateSource,
    anchor_text: str = "",
) -> PageCandidate | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not is_same_site_url(url, base_url):
        return None
    path = parsed.path.lower().rstrip("/") or "/"
    base_host = urlparse(base_url).hostname
    is_related_subdomain_root = path == "/" and parsed.hostname != base_host
    if (path == "/" and not is_related_subdomain_root) or any(
        part in path for part in EXCLUDED_PATH_PARTS
    ):
        return None
    canonical_url = parsed._replace(query="", fragment="").geturl()
    try:
        safe_url = validate_public_url(canonical_url)
    except ValueError:
        return None

    haystack = f"{anchor_text.lower()} {path}".replace("_", "-")
    matched = [
        category
        for category, keywords in PAGE_CATEGORIES.items()
        if any(_phrase_present(haystack, keyword) for keyword in keywords)
    ]
    path_matched = [
        category
        for category, path_hints in PATH_CATEGORY_HINTS.items()
        if any(path == path_hint or path.startswith(f"{path_hint}/") for path_hint in path_hints)
    ]
    exact_path_matched = [
        category for category, path_hints in EXACT_PATH_CATEGORY_HINTS.items() if path in path_hints
    ]
    matched = list(dict.fromkeys([*exact_path_matched, *path_matched, *matched]))
    if not matched:
        return None

    primary_pool = exact_path_matched or path_matched or matched
    primary = max(primary_pool, key=lambda category: CATEGORY_PRIORITIES[category])
    depth = len([part for part in path.split("/") if part])
    source_bonus = 20 if source == CandidateSource.HOMEPAGE_LINK else 5
    short_path_bonus = 10 if depth == 1 else 0
    score = max(0, CATEGORY_PRIORITIES[primary] + source_bonus + short_path_bonus - depth * 3)
    reasons = [
        f"matched {', '.join(matched)}",
        f"discovered via {source.value}",
        f"path depth {depth}",
    ]
    if path_matched:
        reasons.append(f"path classified as {primary}")
    return PageCandidate(
        url=safe_url,
        primary_category=primary,
        matched_categories=matched,
        source=source,
        score=score,
        reasons=reasons,
    )


def _phrase_present(text: str, phrase: str) -> bool:
    pattern = rf"(?<![\w-]){re.escape(phrase)}(?![\w-])"
    return bool(re.search(pattern, text, re.IGNORECASE))


def build_crawl_plan(
    *,
    homepage_candidates: list[PageCandidate],
    sitemap_candidates: list[PageCandidate],
    selection_limit: int,
) -> CrawlPlan:
    combined = _deduplicate_candidates([*homepage_candidates, *sitemap_candidates])
    eligible = [
        candidate
        for candidate in combined
        if candidate.primary_category not in NON_CRAWL_PRIMARY_CATEGORIES
    ]
    selected = _select_category_diverse_pages(eligible, selection_limit)
    return CrawlPlan(
        selected=selected,
        candidate_count=len(combined),
        selection_limit=selection_limit,
    )


def build_question_driven_plan(
    *,
    candidates: list[PageCandidate],
    answered_categories: set[BusinessCategory],
    already_selected_urls: set[str],
    selection_limit: int,
) -> CrawlPlan:
    eligible = [
        candidate.model_copy(update={"source": CandidateSource.SECOND_HOP})
        for candidate in _deduplicate_candidates(candidates)
        if str(candidate.url) not in already_selected_urls
        and candidate.primary_category not in answered_categories
    ]
    return CrawlPlan(
        selected=_select_category_diverse_pages(eligible, selection_limit),
        candidate_count=len(eligible),
        selection_limit=selection_limit,
    )


def _deduplicate_candidates(candidates: list[PageCandidate]) -> list[PageCandidate]:
    by_url: dict[str, PageCandidate] = {}
    for candidate in candidates:
        url = str(candidate.url)
        existing = by_url.get(url)
        if existing is None or candidate.score > existing.score:
            by_url[url] = candidate
    return list(by_url.values())


def _select_category_diverse_pages(
    candidates: list[PageCandidate],
    selection_limit: int,
) -> list[PageCandidate]:
    ranked = sorted(candidates, key=lambda item: (-item.score, str(item.url)))
    selected: list[PageCandidate] = []
    selected_urls: set[str] = set()
    covered_categories: set[str] = set()

    for candidate in ranked:
        if candidate.primary_category in covered_categories:
            continue
        selected.append(candidate)
        selected_urls.add(str(candidate.url))
        covered_categories.add(candidate.primary_category)
        if len(selected) == selection_limit:
            return selected

    for candidate in ranked:
        if str(candidate.url) in selected_urls:
            continue
        selected.append(candidate)
        if len(selected) == selection_limit:
            break
    return selected
