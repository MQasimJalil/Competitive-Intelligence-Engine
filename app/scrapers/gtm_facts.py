import re
from collections.abc import Iterable

from bs4 import BeautifulSoup, Tag

from app.schemas import BusinessCategory, GTMPageFact, ObservedClaim

_CURRENCY_PREFIX = (
    r"(?:[$\u20ac\u00a3\u0141\u20b9\u20a8]|Rs\.?|PKR|INR|NPR|BDT|LKR|AED|SAR|QAR|"
    r"USD|EUR|GBP|CAD|AUD|NZD|SGD|ZAR)"
)
_CURRENCY_SUFFIX = (
    r"(?:[$\u20ac\u00a3\u0141\u20b9\u20a8]|PKR|INR|NPR|BDT|LKR|AED|SAR|QAR|"
    r"USD|EUR|GBP|CAD|AUD|NZD|SGD|ZAR)"
)
PRICE_PATTERN = re.compile(
    rf"(?<!\w)(?:{_CURRENCY_PREFIX}\s?\d[\d,.]*(?:\s?/\s?(?:month|mo|year|yr))?|"
    rf"\d[\d,.]*\s?{_CURRENCY_SUFFIX}(?!\d)(?:\s?/\s?(?:month|mo|year|yr))?)",
    re.IGNORECASE,
)
PRICE_NOISE_PATTERN = re.compile(
    rf"(?:\u00c2|\u00c3\u201a)?{_CURRENCY_PREFIX}\s?\d[\d,.]*|"
    rf"\d[\d,.]*\s?(?:\u00c2|\u00c3\u201a)?{_CURRENCY_SUFFIX}|"
    r"\d[\d,.]*\s?\u00e2\u201a\u00ac",
    re.IGNORECASE,
)
METRIC_PATTERN = re.compile(
    r"(?<!\w)(?:\d+(?:\.\d+)?%|\d{1,3}(?:,\d{3})+\+?|\d+[kKmMbB]\+?|\d+\+)\b",
)

CATEGORY_SIGNAL_KEYWORDS = {
    BusinessCategory.PRICING_PACKAGING: (
        "free",
        "trial",
        "monthly",
        "annual",
        "per month",
        "per year",
        "contact sales",
        "enterprise",
    ),
    BusinessCategory.PRODUCTS_MODULES: (
        "platform",
        "product",
        "module",
        "suite",
        "add-on",
        "workspace",
    ),
    BusinessCategory.CAPABILITIES: (
        "automation",
        "analytics",
        "reporting",
        "workflow",
        "collaboration",
    ),
    BusinessCategory.SOLUTIONS_USE_CASES: (
        "for teams",
        "for enterprise",
        "use case",
        "industry",
        "workflow",
    ),
    BusinessCategory.TARGET_SEGMENTS: (
        "enterprise",
        "startup",
        "small business",
        "agency",
        "team",
    ),
    BusinessCategory.PROOF: ("customers", "trusted by", "case study", "testimonial", "results"),
    BusinessCategory.INTEGRATIONS_ECOSYSTEM: (
        "integration",
        "marketplace",
        "api",
        "partner",
        "connect",
    ),
    BusinessCategory.TRUST_COMPLIANCE: (
        "soc 2",
        "gdpr",
        "hipaa",
        "iso 27001",
        "sso",
        "encryption",
    ),
    BusinessCategory.TECHNICAL_DEPTH: ("api", "sdk", "webhook", "developer", "documentation"),
    BusinessCategory.RECENT_MOVES: ("changelog", "release", "launched", "new", "update"),
    BusinessCategory.HIRING_SIGNALS: ("open roles", "careers", "join", "hiring", "jobs"),
}

CTA_KEYWORDS = (
    "get started",
    "start free",
    "try free",
    "book a demo",
    "request a demo",
    "contact sales",
    "sign up",
)

NOISE_PHRASES = (
    "skip to content",
    "skip to main content",
    "open menu",
    "close menu",
    "accept all cookies",
    "manage cookies",
)


def extract_gtm_page_fact(
    html: str,
    source_url: str,
    category: BusinessCategory | str,
) -> GTMPageFact:
    normalized_category = BusinessCategory(category)
    soup = BeautifulSoup(html, "html.parser")
    content_root = soup.find("main") or soup.body or soup
    _remove_noise(content_root)

    title = _page_title(soup)
    headline = _first_text(content_root.find("h1"))
    evidence_texts = _unique_texts(
        content_root.find_all(["h1", "h2", "h3", "p"]),
        limit=48,
        min_length=3,
    )
    visible_text = content_root.get_text(" ", strip=True)
    claims = _extract_claims(
        soup=soup,
        root=content_root,
        evidence_texts=evidence_texts,
        visible_text=visible_text,
        source_url=source_url,
        category=normalized_category,
    )

    return GTMPageFact(
        category=normalized_category,
        page_url=source_url,
        page_title=title,
        headline=headline,
        claims=claims[:40],
    )


def _extract_claims(
    *,
    soup: BeautifulSoup,
    root: Tag,
    evidence_texts: list[str],
    visible_text: str,
    source_url: str,
    category: BusinessCategory,
) -> list[ObservedClaim]:
    claims: list[ObservedClaim] = []
    headline = _first_text(root.find("h1"))
    if headline:
        claims.append(
            _claim(
                category,
                "page_headline",
                headline,
                headline,
                source_url,
                "Visible page headline",
            )
        )
    if category in {BusinessCategory.PRICING_PACKAGING, BusinessCategory.PRODUCTS_MODULES}:
        claims.extend(_structured_product_metadata(soup, source_url, category))
    for excerpt in evidence_texts[:24]:
        if len(excerpt) < 20:
            continue
        if headline and excerpt == headline:
            continue
        claims.append(
            _claim(
                category,
                "page_claim",
                excerpt,
                excerpt,
                source_url,
                "Visible heading or paragraph",
            )
        )

    if category in {BusinessCategory.PRICING_PACKAGING, BusinessCategory.PRODUCTS_MODULES}:
        for price, excerpt in _product_card_prices(root):
            claims.append(
                _claim(
                    category,
                    "visible_price",
                    price,
                    excerpt,
                    source_url,
                    "Visible price near a product link",
                )
            )
        for price in _deduplicate(PRICE_PATTERN.findall(visible_text))[:8]:
            excerpt = _find_excerpt(evidence_texts, price)
            claims.append(
                _claim(category, "visible_price", price, excerpt, source_url, "Visible price")
            )
    if category == BusinessCategory.PRICING_PACKAGING:
        for heading in _pricing_plan_names(root):
            claims.append(
                _claim(category, "pricing_plan", heading, heading, source_url, "Visible plan name")
            )
        for capability in _packaging_capabilities(root, evidence_texts):
            claims.append(
                _claim(
                    category,
                    "packaging_capability",
                    capability,
                    capability,
                    source_url,
                    "Visible pricing-tier capability",
                )
            )
    if category == BusinessCategory.PRODUCTS_MODULES:
        for fact_type, name, context in _product_link_names(root):
            claims.append(
                _claim(
                    category,
                    fact_type,
                    name,
                    context,
                    source_url,
                    "Visible product or collection link",
                )
            )
    if category in {BusinessCategory.RECENT_MOVES, BusinessCategory.PRODUCTS_MODULES}:
        for portfolio_type in _keyword_matches(
            visible_text,
            ("agent", "model", "dataset", "framework", "training", "paper", "simulator"),
        ):
            claims.append(
                _claim(
                    category,
                    "portfolio_type",
                    portfolio_type,
                    _find_excerpt(evidence_texts, portfolio_type),
                    source_url,
                    "Visible release portfolio type",
                )
            )
        for artifact in _public_artifacts(root):
            claims.append(
                _claim(
                    category,
                    "public_artifact",
                    artifact,
                    artifact,
                    source_url,
                    "Visible public artifact link",
                )
            )
    if category == BusinessCategory.POSITIONING:
        for sentence in _strategic_positioning_sentences(visible_text):
            claims.append(
                _claim(
                    category,
                    "strategic_sentence",
                    sentence,
                    sentence,
                    source_url,
                    "Visible strategic positioning sentence",
                )
            )
    if category == BusinessCategory.PROOF:
        segments = _keyword_matches(
            visible_text,
            ("startup", "enterprise", "saas", "ai", "fintech", "consumer", "hardware", "health"),
        )
        if len(segments) >= 3:
            claims.append(
                _claim(
                    category,
                    "market_segments",
                    f"Customer segments: {', '.join(segments)}",
                    f"Visible customer segment labels: {', '.join(segments)}",
                    source_url,
                    "Visible customer segment labels",
                )
            )
    if category in {
        BusinessCategory.POSITIONING,
        BusinessCategory.CAPABILITIES,
        BusinessCategory.PRODUCTS_MODULES,
    }:
        for stage in _workflow_stages(root):
            claims.append(
                _claim(
                    category,
                    "workflow_stage",
                    stage,
                    stage,
                    source_url,
                    "Visible workflow stage",
                )
            )
    if category == BusinessCategory.PROOF:
        for metric in _deduplicate(METRIC_PATTERN.findall(visible_text))[:8]:
            excerpt = _find_excerpt(evidence_texts, metric)
            claims.append(
                _claim(category, "proof_metric", metric, excerpt, source_url, "Proof text")
            )

    for keyword in _keyword_matches(visible_text, CATEGORY_SIGNAL_KEYWORDS.get(category, ())):
        excerpt = _find_excerpt(evidence_texts, keyword)
        claims.append(
            _claim(
                category,
                "keyword_mention",
                keyword,
                excerpt,
                source_url,
                "Visible page text",
            )
        )

    if category in {
        BusinessCategory.PRICING_PACKAGING,
        BusinessCategory.SALES_MOTION,
        BusinessCategory.TARGET_SEGMENTS,
    }:
        for cta in _link_text_matches(root, CTA_KEYWORDS):
            claims.append(_claim(category, "cta", cta, cta, source_url, "Visible link text"))

    return _prioritize_claims(_deduplicate_claims(claims))


def _claim(
    category: BusinessCategory,
    fact_type: str,
    value: str,
    excerpt: str,
    source_url: str,
    context: str,
) -> ObservedClaim:
    cleaned_value = _clean_text(value)
    cleaned_excerpt = _clean_text(excerpt)
    return ObservedClaim(
        category=category,
        fact_type=fact_type,
        value=cleaned_value[:500],
        evidence_excerpt=cleaned_excerpt[:1_000],
        source_url=source_url,
        context=context,
    )


def _structured_product_metadata(
    soup: BeautifulSoup,
    source_url: str,
    category: BusinessCategory,
) -> list[ObservedClaim]:
    title = _meta_content(soup, "og:title") or _meta_content(soup, "twitter:title")
    product_type = _meta_content(soup, "og:type").casefold()
    amount = _meta_content(soup, "og:price:amount") or _meta_content(
        soup,
        "product:price:amount",
    )
    currency = _meta_content(soup, "og:price:currency") or _meta_content(
        soup,
        "product:price:currency",
    )
    looks_like_product = product_type == "product" or "/products/" in source_url.casefold()
    claims: list[ObservedClaim] = []
    if title and looks_like_product:
        claims.append(
            _claim(
                category,
                "structured_product",
                title,
                title,
                source_url,
                "Open Graph product title metadata",
            )
        )
    if amount and currency and looks_like_product:
        normalized_currency = currency.strip().upper()
        normalized_amount = amount.strip()
        value = f"{normalized_currency} {normalized_amount}"
        excerpt = f"{title} {value}".strip()
        claims.append(
            _claim(
                category,
                "structured_price",
                value,
                excerpt,
                source_url,
                "Open Graph product price metadata",
            )
        )
    return claims


def _meta_content(soup: BeautifulSoup, key: str) -> str:
    tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
    if not tag:
        return ""
    return _clean_text(str(tag.get("content", "")))


def _remove_noise(root: Tag) -> None:
    noise_tags = ["script", "style", "noscript", "svg", "nav", "footer", "form", "template"]
    for tag in root.find_all(noise_tags):
        tag.decompose()
    for tag in root.find_all(attrs={"aria-hidden": "true"}):
        tag.decompose()
    for tag in root.find_all(style=True):
        if tag.attrs is None:
            continue
        style = str(tag.get("style", "")).replace(" ", "").lower()
        if "display:none" in style or "visibility:hidden" in style:
            tag.decompose()
    for tag in root.find_all(hidden=True):
        tag.decompose()


def _page_title(soup: BeautifulSoup) -> str:
    return soup.title.get_text(" ", strip=True)[:300] if soup.title else ""


def _first_text(tag: Tag | None) -> str:
    return _clean_text(tag.get_text(" ", strip=True))[:500] if tag else ""


def _unique_texts(
    tags: Iterable[Tag],
    *,
    limit: int,
    min_length: int = 3,
) -> list[str]:
    values: list[str] = []
    for tag in tags:
        value = _clean_text(tag.get_text(" ", strip=True))
        if len(value) < min_length or value in values:
            continue
        values.append(value)
        if len(values) == limit:
            break
    return values


def _keyword_matches(text: str, keywords: Iterable[str]) -> list[str]:
    return [keyword for keyword in keywords if _phrase_present(text, keyword)]


def _phrase_present(text: str, phrase: str) -> bool:
    pattern = rf"(?<![\w-]){re.escape(phrase)}(?![\w-])"
    return bool(re.search(pattern, text, re.IGNORECASE))


def _link_text_matches(root: Tag, keywords: Iterable[str]) -> list[str]:
    matches: list[str] = []
    for anchor in root.find_all("a"):
        text = anchor.get_text(" ", strip=True)
        if text and any(_phrase_present(text, keyword) for keyword in keywords):
            matches.append(text)
    return _deduplicate(matches)[:6]


def _pricing_plan_names(root: Tag) -> list[str]:
    excluded = {"pricing", "plans", "compare plans", "frequently asked questions"}
    common_names = {
        "free",
        "basic",
        "starter",
        "pro",
        "professional",
        "business",
        "team",
        "growth",
        "enterprise",
    }
    names = []
    for heading in root.find_all(["h2", "h3"]):
        text = " ".join(heading.get_text(" ", strip=True).split())
        if (
            2 <= len(text) <= 40
            and text.casefold() not in excluded
            and not PRICE_PATTERN.search(text)
            and any(word in common_names for word in text.casefold().split())
        ):
            names.append(text)
    return _deduplicate(names)[:8]


def _product_link_names(root: Tag) -> list[tuple[str, str, str]]:
    names: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for anchor in root.find_all("a", href=True):
        href = str(anchor.get("href", "")).casefold()
        if "/products/" not in href and "/collections/" not in href:
            continue
        text = " ".join(anchor.get_text(" ", strip=True).split())
        text = PRICE_PATTERN.sub("", text).strip(" -|")
        text = PRICE_NOISE_PATTERN.sub("", text).strip(" -|")
        text = re.sub(r"\s+\d+[,.]\d{1,2}$", "", text).strip(" -|")
        if not 2 <= len(text) <= 100 or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        fact_type = "product_collection" if "/collections/" in href else "linked_product"
        names.append((fact_type, text, anchor.get_text(" ", strip=True)[:1_000]))
    return names[:30]


def _product_card_prices(root: Tag) -> list[tuple[str, str]]:
    prices: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for anchor in root.find_all("a", href=True):
        href = str(anchor.get("href", "")).casefold()
        if "/products/" not in href:
            continue
        container: Tag | None = anchor
        for _ in range(6):
            if container.parent is None or not isinstance(container.parent, Tag):
                break
            container = container.parent
            text = " ".join(container.get_text(" ", strip=True).split())
            matches = PRICE_PATTERN.findall(text)
            if not matches and len(text) > 2_000:
                break
            if not matches:
                continue
            for price in matches:
                key = (price.casefold(), text.casefold())
                if key not in seen:
                    seen.add(key)
                    prices.append((price, text[:1_000]))
            break
    return prices[:30]


def _packaging_capabilities(root: Tag, evidence_texts: list[str]) -> list[str]:
    terms = (
        "agent",
        "code intelligence",
        "insights",
        "asks",
        "saml",
        "scim",
        "admin controls",
        "onboarding",
    )
    candidates = _deduplicate(
        [
            *evidence_texts,
            *_unique_texts(root.find_all(["li", "span"]), limit=100, min_length=10),
        ]
    )
    return [
        text
        for text in candidates
        if 20 <= len(text) <= 500 and any(term in text.casefold() for term in terms)
    ][:8]


def _public_artifacts(root: Tag) -> list[str]:
    artifacts = []
    for anchor in root.find_all("a", href=True):
        text = " ".join(anchor.get_text(" ", strip=True).split())
        href = str(anchor.get("href", "")).casefold()
        if "github.com" in href:
            artifacts.append("GitHub")
        elif "huggingface.co" in href:
            artifacts.append("Hugging Face")
        elif any(term in text.casefold() for term in ("paper", "technical report")):
            artifacts.append(text)
    return _deduplicate(artifacts)[:8]


def _strategic_positioning_sentences(visible_text: str) -> list[str]:
    terms = ("human rights", "freedom", "unrestricted", "open source")
    sentences = re.split(r"(?<=[.!?])\s+", visible_text)
    return [
        sentence
        for sentence in _deduplicate(sentences)
        if 30 <= len(sentence) <= 500 and sum(term in sentence.casefold() for term in terms) >= 2
    ][:4]


def _workflow_stages(root: Tag) -> list[str]:
    known = {
        "intake",
        "plan",
        "planning",
        "build",
        "diffs",
        "review",
        "monitor",
        "triage",
        "roadmap",
    }
    values = []
    for element in root.find_all(["a", "h2", "h3"]):
        text = " ".join(element.get_text(" ", strip=True).split())
        if text.casefold() in known:
            values.append(text)
    return _deduplicate(values)[:10]


def _find_excerpt(evidence_texts: list[str], needle: str) -> str:
    for text in evidence_texts:
        if needle.casefold() in text.casefold():
            return text
    return needle


def _deduplicate(values: Iterable[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _clean_text(value)
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        unique.append(normalized)
    return unique


def _clean_text(value: str) -> str:
    normalized = " ".join(value.split()).strip()
    for phrase in NOISE_PHRASES:
        normalized = re.sub(
            rf"(?i)(?:^|\s){re.escape(phrase)}(?:\s*(?:→|>|/|-)\s*)?",
            " ",
            normalized,
        )
    normalized = re.sub(r"\s+", " ", normalized).strip(" -|/→")
    normalized = _collapse_repeated_prefix(normalized)
    return normalized


def _collapse_repeated_prefix(value: str) -> str:
    words = value.split()
    if len(words) < 8:
        return value
    for size in range(3, min(14, len(words) // 2) + 1):
        first = " ".join(words[:size]).casefold()
        second = " ".join(words[size : size * 2]).casefold()
        if first == second:
            return " ".join([*words[:size], *words[size * 2 :]])
    return value


def _deduplicate_claims(claims: Iterable[ObservedClaim]) -> list[ObservedClaim]:
    unique: list[ObservedClaim] = []
    seen: set[tuple[str, str]] = set()
    for claim in claims:
        key = (claim.fact_type, claim.value.casefold())
        if key in seen:
            continue
        seen.add(key)
        unique.append(claim)
    return unique


def _prioritize_claims(claims: list[ObservedClaim]) -> list[ObservedClaim]:
    priority = {
        "structured_product": 110,
        "structured_price": 108,
        "linked_product": 105,
        "product_collection": 104,
        "visible_price": 100,
        "pricing_plan": 95,
        "packaging_capability": 94,
        "portfolio_type": 90,
        "public_artifact": 89,
        "market_segments": 88,
        "strategic_sentence": 87,
        "workflow_stage": 90,
        "proof_metric": 85,
        "page_headline": 80,
        "page_claim": 60,
        "cta": 50,
        "keyword_mention": 30,
    }
    return sorted(
        claims,
        key=lambda claim: (
            -priority.get(claim.fact_type, 0),
            abs(min(len(claim.value), 300) - 120),
        ),
    )
