from datetime import UTC, datetime
from urllib.parse import urlparse

from app.adapters.apify_client import ApifyActorSpec
from app.schemas import (
    BusinessCategory,
    ExtractionResult,
    ExtractionStatus,
    ObservedClaim,
    SourceType,
)

EXTRACTOR_INSTAGRAM = "apify_instagram_facts"
EXTRACTOR_LINKEDIN = "apify_linkedin_company_facts"
EXTRACTOR_REDDIT = "apify_reddit_facts"
EXTRACTOR_SEARCH = "apify_search_facts"
EXTRACTOR_WEBSITE_CONTENT = "apify_website_content_facts"

DEFAULT_APIFY_RESULT_COSTS_USD = {
    "instagram": 0.0027,
    "instagram_posts": 0.0027,
    "instagram_comments": 0.0027,
}
DEFAULT_APIFY_ACTOR_COSTS_USD = {
    "linkedin": 0.00005,
    "reddit_search": 0.004,
    "google_search": 0.002,
    "website_content": 0.005,
}


def build_apify_actor_specs(
    domain: str,
    homepage_url: str,
    social_links: list[str],
    *,
    enable_ai: bool = False,
    include_deep_social: bool = False,
    include_linkedin: bool = True,
    include_reddit: bool = False,
    include_search: bool = False,
    include_website_content: bool = False,
    apify_budget_usd: float = 0.075,
    actor_costs_usd: dict[str, float] | None = None,
    reddit_actor_id: str = "apify/reddit-scraper",
) -> dict[str, ApifyActorSpec]:
    instagram_urls = _links_for_host(social_links, "instagram.com")
    linkedin_urls = _links_for_host(social_links, "linkedin.com")
    specs: dict[str, ApifyActorSpec] = {}
    budget = _ApifyBudget(apify_budget_usd, actor_costs_usd or DEFAULT_APIFY_ACTOR_COSTS_USD)
    if instagram_urls:
        _add_actor(
            specs,
            budget,
            "instagram",
            ApifyActorSpec(
                actor_id="apify/instagram-scraper",
                payload={
                    "directUrls": instagram_urls,
                    "search": "",
                    "searchType": "user",
                    "resultsType": "details",
                    "resultsLimit": 1,
                },
            ),
        )
    if not enable_ai:
        return specs
    if include_deep_social and instagram_urls:
        _add_actor(
            specs,
            budget,
            "instagram_posts",
            ApifyActorSpec(
                actor_id="apify/instagram-scraper",
                payload={
                    "directUrls": instagram_urls,
                    "search": "",
                    "searchType": "user",
                    "resultsType": "posts",
                    "resultsLimit": 3,
                },
            ),
        )
    if include_linkedin and linkedin_urls:
        _add_actor(
            specs,
            budget,
            "linkedin",
            ApifyActorSpec(
                actor_id="harvestapi/linkedin-company",
                payload={
                    "companies": linkedin_urls,
                },
            ),
        )
    if include_reddit:
        _add_actor(
            specs,
            budget,
            "reddit_search",
            ApifyActorSpec(
                actor_id=reddit_actor_id,
                payload={
                    "searches": [domain],
                    "queries": [f"{domain} reddit", f"site:reddit.com {domain}"],
                    "searchTerms": [domain],
                    "maxItems": 8,
                    "maxResults": 8,
                    "includeComments": True,
                },
            ),
        )
    if include_search:
        _add_actor(
            specs,
            budget,
            "google_search",
            ApifyActorSpec(
                actor_id="apify/google-search-scraper",
                payload={
                    "queries": [
                        f"{domain} reviews",
                        f"{domain} instagram linkedin",
                        f"{domain} competitors",
                    ],
                    "resultsPerPage": 10,
                    "maxPagesPerQuery": 1,
                },
            ),
        )
    if include_website_content:
        _add_actor(
            specs,
            budget,
            "website_content",
            ApifyActorSpec(
                actor_id="apify/website-content-crawler",
                payload={
                    "startUrls": [{"url": homepage_url}],
                    "maxCrawlPages": 10,
                    "crawlerType": "playwright:firefox",
                },
            ),
        )
    return specs


def build_apify_enrichment_results(
    domain: str,
    datasets: dict[str, list[dict]],
    source_urls: dict[str, str],
) -> list[ExtractionResult]:
    instagram_items = [
        *datasets.get("instagram", []),
        *datasets.get("instagram_posts", []),
        *datasets.get("instagram_comments", []),
    ]
    return [
        social_profile_result(domain, instagram_items, source_urls.get("instagram")),
        linkedin_company_result(domain, datasets.get("linkedin", []), source_urls.get("linkedin")),
        reddit_result(domain, datasets.get("reddit_search", []), source_urls.get("reddit_search")),
        search_results_result(
            domain,
            datasets.get("google_search", []),
            source_urls.get("google_search"),
        ),
        website_content_result(
            domain,
            datasets.get("website_content", []),
            source_urls.get("website_content"),
        ),
    ]


def estimate_apify_actor_cost_usd(
    specs: dict[str, ApifyActorSpec],
    actor_costs_usd: dict[str, float] | None = None,
) -> float:
    costs = actor_costs_usd or DEFAULT_APIFY_ACTOR_COSTS_USD
    return round(
        sum(_estimate_actor_cost(actor_key, spec, costs) for actor_key, spec in specs.items()),
        6,
    )


def _estimate_actor_cost(
    actor_key: str,
    spec: ApifyActorSpec,
    actor_costs_usd: dict[str, float],
) -> float:
    if actor_key in DEFAULT_APIFY_RESULT_COSTS_USD:
        limit = _payload_int(spec.payload, "resultsLimit", default=1)
        direct_urls = spec.payload.get("directUrls")
        url_count = len(direct_urls) if isinstance(direct_urls, list) and direct_urls else 1
        if actor_key in {"instagram", "instagram_posts"}:
            unit_count = min(limit, max(1, url_count * limit))
        else:
            unit_count = limit
        return max(0.0, DEFAULT_APIFY_RESULT_COSTS_USD[actor_key] * unit_count)
    return max(0.0, actor_costs_usd.get(actor_key, 0.0))


def social_profile_result(
    domain: str, items: list[dict], source_url: str | None = None
) -> ExtractionResult:
    claims: list[ObservedClaim] = []
    for item in items:
        if _is_instagram_comment(item):
            comment_source = _comment_source_url(item, source_url)
            text = _first_text(item, "text")
            if text and comment_source:
                claims.append(
                    _claim(
                        BusinessCategory.PROOF,
                        "social_comment_excerpt",
                        f"Public Instagram comment: {text}",
                        text,
                        comment_source,
                        "Public Instagram comment returned by Apify Instagram Scraper.",
                    )
                )
            continue

        profile_url = _first_text(item, "url", "inputUrl") or source_url
        if not profile_url:
            continue
        username = _first_text(item, "username", "ownerUsername") or _domain_label(domain)
        followers = _first_number(item, "followersCount")
        posts = _first_number(item, "postsCount")
        bio = _first_text(item, "biography", "bio")
        if _is_instagram_post(item):
            claims.extend(_post_claims(item, profile_url))
        if followers is not None:
            claims.append(
                _claim(
                    BusinessCategory.PROOF,
                    "social_followers",
                    f"Instagram profile {username} shows {followers:,} followers.",
                    f"followersCount={followers}",
                    profile_url,
                    "Public Instagram profile metadata returned by Apify Instagram Scraper.",
                )
            )
        if posts is not None:
            claims.append(
                _claim(
                    BusinessCategory.RECENT_MOVES,
                    "social_post_count",
                    f"Instagram profile {username} shows {posts:,} posts.",
                    f"postsCount={posts}",
                    profile_url,
                    "Public Instagram profile metadata returned by Apify Instagram Scraper.",
                )
            )
        if bio:
            claims.append(
                _claim(
                    BusinessCategory.POSITIONING,
                    "social_bio",
                    bio[:500],
                    bio,
                    profile_url,
                    "Public Instagram profile biography.",
                )
            )
        for post in _latest_posts(item)[:3]:
            post_url = _first_text(post, "url", "postUrl") or profile_url
            claims.extend(_post_claims(post, post_url))
    return _result(
        EXTRACTOR_INSTAGRAM,
        claims,
        source_url or _first_source(claims),
        "Public Instagram profile/post facts from Apify Instagram Scraper.",
    )


def linkedin_company_result(
    domain: str, items: list[dict], source_url: str | None = None
) -> ExtractionResult:
    claims: list[ObservedClaim] = []
    for item in items:
        linkedin_url = _first_text(item, "linkedinUrl", "url") or source_url
        if not linkedin_url:
            continue
        name = _first_text(item, "name", "companyName") or _domain_label(domain)
        description = _first_text(item, "description", "tagline")
        employee_count = _first_number(item, "employeeCount")
        follower_count = _first_number(item, "followerCount")
        industries = _string_list(item.get("industries"))
        locations = _locations(item)
        if description:
            claims.append(
                _claim(
                    BusinessCategory.POSITIONING,
                    "linkedin_description",
                    description[:500],
                    description,
                    linkedin_url,
                    "Public LinkedIn company description returned by HarvestAPI.",
                )
            )
        if employee_count is not None:
            claims.append(
                _claim(
                    BusinessCategory.HIRING_SIGNALS,
                    "linkedin_employee_count",
                    f"LinkedIn lists {name} with {employee_count:,} employees.",
                    f"employeeCount={employee_count}",
                    linkedin_url,
                    "Public LinkedIn company metadata returned by HarvestAPI.",
                )
            )
        if follower_count is not None:
            claims.append(
                _claim(
                    BusinessCategory.PROOF,
                    "linkedin_followers",
                    f"LinkedIn lists {name} with {follower_count:,} followers.",
                    f"followerCount={follower_count}",
                    linkedin_url,
                    "Public LinkedIn company metadata returned by HarvestAPI.",
                )
            )
        if industries:
            joined = ", ".join(industries[:3])
            claims.append(
                _claim(
                    BusinessCategory.POSITIONING,
                    "linkedin_industry",
                    f"LinkedIn industry classification: {joined}.",
                    joined,
                    linkedin_url,
                    "Public LinkedIn industry metadata returned by HarvestAPI.",
                )
            )
        if locations:
            claims.append(
                _claim(
                    BusinessCategory.HIRING_SIGNALS,
                    "linkedin_location",
                    f"LinkedIn location signal: {locations[0]}.",
                    "; ".join(locations[:3]),
                    linkedin_url,
                    "Public LinkedIn location metadata returned by HarvestAPI.",
                )
            )
    return _result(
        EXTRACTOR_LINKEDIN,
        claims,
        source_url or _first_source(claims),
        "Public LinkedIn company facts from HarvestAPI LinkedIn Company Details.",
    )


def reddit_result(
    domain: str, items: list[dict], source_url: str | None = None
) -> ExtractionResult:
    claims: list[ObservedClaim] = []
    for item in items:
        url = _first_text(item, "url", "postUrl", "permalink") or source_url
        if not url:
            continue
        title = _first_text(item, "title", "postTitle")
        body = _first_text(item, "body", "text", "selftext", "description")
        comment = _first_text(item, "comment", "commentText")
        score = _first_number(item, "score", "upVotes", "upvotes")
        comments_count = _first_number(item, "commentsCount", "numComments", "numberOfComments")
        if title or body:
            metrics = []
            if score is not None:
                metrics.append(f"{score:,} score")
            if comments_count is not None:
                metrics.append(f"{comments_count:,} comments")
            metric_suffix = f" ({', '.join(metrics)})" if metrics else ""
            text = _first_sentence(body) or title
            claims.append(
                _claim(
                    BusinessCategory.PROOF,
                    "reddit_thread_signal",
                    f"Reddit thread signal: {title or text}{metric_suffix}",
                    text or title,
                    url,
                    "Public Reddit thread returned by Apify Reddit enrichment.",
                )
            )
        if comment:
            claims.append(
                _claim(
                    BusinessCategory.PROOF,
                    "reddit_comment_excerpt",
                    f"Public Reddit comment: {comment}",
                    comment,
                    url,
                    "Public Reddit comment returned by Apify Reddit enrichment.",
                )
            )
        for nested in _latest_comments(item)[:2]:
            claims.append(
                _claim(
                    BusinessCategory.PROOF,
                    "reddit_comment_excerpt",
                    f"Public Reddit comment: {nested}",
                    nested,
                    url,
                    "Public Reddit comment returned by Apify Reddit enrichment.",
                )
            )
        if len(claims) >= 8:
            break
    return _result(
        EXTRACTOR_REDDIT,
        claims,
        source_url or _first_source(claims),
        "Public Reddit perception facts from Apify Reddit enrichment.",
    )


def search_results_result(
    domain: str, items: list[dict], source_url: str | None = None
) -> ExtractionResult:
    claims: list[ObservedClaim] = []
    for item in items:
        for result in _search_items(item):
            url = _first_text(result, "url", "link")
            title = _first_text(result, "title")
            description = _first_text(result, "description", "snippet")
            if not url or _same_domain(domain, url):
                continue
            label = title or url
            claims.append(
                _claim(
                    BusinessCategory.PROOF,
                    "external_mention",
                    f"External search result mentions the company: {label}"[:500],
                    description or label,
                    url,
                    "Public Google Search result returned by Apify Google Search Results Scraper.",
                )
            )
            if len(claims) >= 6:
                break
        if len(claims) >= 6:
            break
    return _result(
        EXTRACTOR_SEARCH,
        claims,
        source_url or _first_source(claims),
        "External public mentions from Apify Google Search Results Scraper.",
    )


def website_content_result(
    domain: str, items: list[dict], source_url: str | None = None
) -> ExtractionResult:
    claims: list[ObservedClaim] = []
    for item in items:
        url = _first_text(item, "url", "loadedUrl") or source_url
        text = _first_text(item, "text", "markdown")
        if not url or not text:
            continue
        sentence = _first_sentence(text)
        if not sentence:
            continue
        claims.append(
            _claim(
                BusinessCategory.POSITIONING,
                "fallback_page_claim",
                sentence[:500],
                sentence[:1_000],
                url,
                "Fallback public page text from Apify Website Content Crawler.",
            )
        )
        if len(claims) >= 6:
            break
    return _result(
        EXTRACTOR_WEBSITE_CONTENT,
        claims,
        source_url or _first_source(claims),
        "Fallback public page facts from Apify Website Content Crawler.",
    )


def _result(
    extractor_name: str,
    claims: list[ObservedClaim],
    source_url: str | None,
    notes: str,
) -> ExtractionResult:
    if not claims:
        return ExtractionResult.unavailable(
            extractor_name=extractor_name,
            source_url=source_url,
            notes="No Apify enrichment data was available.",
        )
    return ExtractionResult(
        value={"claims": [claim.model_dump(mode="json") for claim in claims]},
        source_url=source_url or str(claims[0].source_url),
        extractor_name=extractor_name,
        confidence=0.82,
        status=ExtractionStatus.OK,
        source_type=SourceType.PUBLIC_API,
        notes=notes,
        evidence=" | ".join(claim.evidence_excerpt for claim in claims[:4])[:1000],
    )


def _claim(
    category: BusinessCategory,
    fact_type: str,
    value: str,
    evidence: str,
    source_url: str,
    context: str,
) -> ObservedClaim:
    return ObservedClaim(
        category=category,
        fact_type=fact_type,
        value=" ".join(value.split())[:500],
        evidence_excerpt=" ".join(evidence.split())[:1000] or value,
        source_url=source_url,
        retrieved_at=datetime.now(UTC),
        context=context,
    )


class _ApifyBudget:
    def __init__(self, limit_usd: float, actor_costs_usd: dict[str, float]) -> None:
        self.limit_usd = max(0.0, limit_usd)
        self.actor_costs_usd = actor_costs_usd
        self.spent_usd = 0.0

    def reserve(self, actor_key: str, spec: ApifyActorSpec) -> bool:
        cost = _estimate_actor_cost(actor_key, spec, self.actor_costs_usd)
        if self.spent_usd + cost > self.limit_usd:
            return False
        self.spent_usd += cost
        return True


def _add_actor(
    specs: dict[str, ApifyActorSpec],
    budget: _ApifyBudget,
    actor_key: str,
    spec: ApifyActorSpec,
) -> None:
    if budget.reserve(actor_key, spec):
        specs[actor_key] = spec


def build_instagram_comment_actor_spec(post_urls: list[str]) -> ApifyActorSpec | None:
    selected = _unique(post_urls)[:1]
    if not selected:
        return None
    return ApifyActorSpec(
        actor_id="apify/instagram-scraper",
        payload={
            "directUrls": selected,
            "resultsType": "comments",
            "resultsLimit": 12,
        },
    )


def instagram_post_urls_from_datasets(datasets: dict[str, list[dict]]) -> list[str]:
    urls: list[str] = []
    for key in ("instagram", "instagram_posts"):
        for item in datasets.get(key, []):
            if _is_instagram_post(item):
                urls.append(_first_text(item, "url", "postUrl"))
            for post in _latest_posts(item):
                urls.append(_first_text(post, "url", "postUrl"))
    return _unique([url for url in urls if url])


def _post_claims(post: dict, fallback_url: str) -> list[ObservedClaim]:
    post_url = _first_text(post, "url", "postUrl") or fallback_url
    caption = _first_text(post, "caption", "text")
    likes = _first_number(post, "likesCount")
    comments = _first_number(post, "commentsCount")
    claims: list[ObservedClaim] = []
    if likes is not None or comments is not None:
        engagement = []
        if likes is not None:
            engagement.append(f"{likes:,} likes")
        if comments is not None:
            engagement.append(f"{comments:,} comments")
        claims.append(
            _claim(
                BusinessCategory.PROOF,
                "social_post_engagement",
                f"Instagram post engagement: {', '.join(engagement)}.",
                caption[:1_000] or f"likesCount={likes}; commentsCount={comments}",
                post_url,
                "Public Instagram post metrics returned by Apify Instagram Scraper.",
            )
        )
    if caption:
        claims.append(
            _claim(
                BusinessCategory.RECENT_MOVES,
                "social_post_caption",
                caption[:500],
                caption,
                post_url,
                "Public Instagram post caption returned by Apify Instagram Scraper.",
            )
        )
    first_comment = _first_text(post, "firstComment")
    latest_comments = _latest_comments(post)
    comment_texts = [first_comment, *latest_comments]
    for text in [item for item in comment_texts if item][:2]:
        claims.append(
            _claim(
                BusinessCategory.PROOF,
                "social_comment_excerpt",
                f"Public Instagram comment: {text}",
                text,
                post_url,
                "Public Instagram comment excerpt returned by Apify Instagram Scraper.",
            )
        )
    return claims


def _first_text(item: dict, *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return ""


def _first_number(item: dict, *keys: str) -> int | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            return int(value)
        if isinstance(value, str):
            normalized = value.replace(",", "").strip()
            if normalized.isdigit():
                return int(normalized)
    return None


def _payload_int(payload: dict, key: str, *, default: int) -> int:
    value = payload.get(key)
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return max(0, int(value))
    if isinstance(value, str) and value.strip().isdigit():
        return max(0, int(value.strip()))
    return default


def _latest_posts(item: dict) -> list[dict]:
    value = item.get("latestPosts") or item.get("posts") or []
    return value if isinstance(value, list) else []


def _latest_comments(item: dict) -> list[str]:
    value = item.get("latestComments") or item.get("comments") or []
    if not isinstance(value, list):
        return []
    comments = []
    for comment in value:
        if isinstance(comment, str):
            comments.append(comment)
        elif isinstance(comment, dict):
            text = _first_text(comment, "text", "comment")
            if text:
                comments.append(text)
    return comments


def _is_instagram_post(item: dict) -> bool:
    return bool(
        _first_text(item, "shortCode")
        or (_first_text(item, "url", "postUrl") and "/p/" in _first_text(item, "url", "postUrl"))
    )


def _is_instagram_comment(item: dict) -> bool:
    return bool(_first_text(item, "postId") and _first_text(item, "text"))


def _comment_source_url(item: dict, fallback_url: str | None) -> str:
    post_url = _first_text(item, "postUrl", "url")
    if post_url:
        return post_url
    post_id = _first_text(item, "postId")
    if post_id:
        return f"https://www.instagram.com/p/{post_id}/"
    return fallback_url or ""


def _search_items(item: dict) -> list[dict]:
    for key in ("organicResults", "results", "organic"):
        value = item.get(key)
        if isinstance(value, list):
            return value
    return [item]


def _string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _locations(item: dict) -> list[str]:
    raw = item.get("locations")
    if not isinstance(raw, list):
        return []
    locations: list[str] = []
    for location in raw:
        if not isinstance(location, dict):
            continue
        parsed = location.get("parsed")
        if isinstance(parsed, dict) and parsed.get("text"):
            locations.append(str(parsed["text"]))
            continue
        parts = [location.get("city"), location.get("country")]
        label = ", ".join(str(part) for part in parts if part)
        if label:
            locations.append(label)
    return locations


def _first_sentence(text: str) -> str:
    normalized = " ".join(text.split())
    if not normalized:
        return ""
    for delimiter in (". ", "! ", "? "):
        if delimiter in normalized:
            return normalized.split(delimiter, 1)[0] + delimiter.strip()
    return normalized[:240]


def _first_source(claims: list[ObservedClaim]) -> str | None:
    return str(claims[0].source_url) if claims else None


def _domain_label(domain: str) -> str:
    return domain.split(".")[0]


def _same_domain(domain: str, url: str) -> bool:
    hostname = urlparse(url).hostname or ""
    return hostname.removeprefix("www.").casefold() == domain.casefold()


def _links_for_host(links: list[str], host: str) -> list[str]:
    selected = []
    for link in links:
        hostname = urlparse(link).hostname or ""
        if hostname.removeprefix("www.").casefold() == host and link not in selected:
            selected.append(link)
    return selected[:3]


def _unique(values: list[str]) -> list[str]:
    selected = []
    for value in values:
        if value and value not in selected:
            selected.append(value)
    return selected
