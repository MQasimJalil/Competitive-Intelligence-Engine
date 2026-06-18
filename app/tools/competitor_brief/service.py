import asyncio
from collections.abc import Callable

from pydantic import BaseModel

from app.adapters.apify_client import run_configured_actors
from app.adapters.apify_enrichment import (
    build_apify_actor_specs,
    build_apify_enrichment_results,
    build_instagram_comment_actor_spec,
    estimate_apify_actor_cost_usd,
    instagram_post_urls_from_datasets,
)
from app.adapters.rss import discover_feed_urls, fetch_recent_activity
from app.config import settings
from app.schemas import (
    AIAnalysis,
    AIAnalysisRun,
    BusinessCategory,
    CompetitorProfile,
    CrawlPlan,
    EvidenceKind,
    ExtractionResult,
    ExtractionStatus,
    NodeFailurePolicy,
    NodeRun,
    NodeStatus,
    NormalizedBusinessProfile,
    SourceType,
    StructuredIntelligenceProfile,
    ValidationReport,
    WorkflowRun,
    WorkflowState,
)
from app.scrapers.discovery import (
    build_crawl_plan,
    build_question_driven_plan,
    discover_homepage_candidates,
    discover_relevant_links,
    discover_sitemap_candidates,
)
from app.scrapers.domain import homepage_url, normalize_domain
from app.scrapers.gtm_facts import extract_gtm_page_fact
from app.scrapers.http import FetchError, fetch_text
from app.scrapers.metadata import extract_page_metadata
from app.scrapers.rendered import fetch_rendered_text, has_sparse_business_html
from app.scrapers.robots import RobotsDecision, can_fetch_url
from app.scrapers.shopify import fetch_shopify_products
from app.scrapers.sitemap import SitemapResult, fetch_sitemap
from app.scrapers.structured_data import extract_structured_data
from app.scrapers.tech_signals import detect_tech_signals
from app.tools.competitor_brief.analysis_nodes import build_strategic_analysis_node
from app.tools.competitor_brief.business_normalizer import build_normalized_business_profile
from app.tools.competitor_brief.intelligence_builder import build_structured_intelligence
from app.tools.competitor_brief.page_extraction import extract_ranked_pages_with_candidates
from app.tools.competitor_brief.profile_builder import build_competitor_profile
from app.tools.competitor_brief.validation import validate_business_profile
from app.workflow import NodeRegistry, WorkflowNode, execute_node, execute_parallel_nodes

ProgressCallback = Callable[[WorkflowRun], None]


class CompetitorSnapshot(BaseModel):
    domain: str
    homepage: str
    results: list[ExtractionResult]
    crawl_plan: CrawlPlan | None = None
    profile: CompetitorProfile | None = None
    business_profile: NormalizedBusinessProfile | None = None
    intelligence: StructuredIntelligenceProfile | None = None
    ai_analysis: AIAnalysis | None = None
    ai_analysis_status: str = "not_configured"
    ai_run: AIAnalysisRun | None = None
    apify_estimated_cost_usd: float = 0.0
    validation: ValidationReport | None = None
    workflow: WorkflowRun | None = None
    failure_reason: str = ""


def describe_collection_failure(results: list[ExtractionResult]) -> str:
    failures = [result for result in results if result.status != ExtractionStatus.OK]
    if not failures:
        return ""
    result = failures[-1]
    notes = result.notes.casefold()
    status = result.http_status
    if result.status == ExtractionStatus.ROBOTS_DISALLOWED:
        return "The site does not allow this page to be crawled under its robots policy."
    if result.status == ExtractionStatus.RATE_LIMITED or status == 429:
        return "The site temporarily rate-limited the research request (HTTP 429)."
    if result.status == ExtractionStatus.TOS_BLOCKED:
        if status in {401, 403}:
            return f"The site denied automated access (HTTP {status})."
        if "redirect" in notes:
            return "The site redirected to a different domain, so the crawler stopped safely."
        return "The site denied automated access."
    if status == 404:
        return "The homepage was not found (HTTP 404). The site may have moved."
    if status and 400 <= status < 500:
        return f"The site rejected the request (HTTP {status})."
    if status and status >= 500:
        return f"The site returned a server error (HTTP {status})."
    if "could not be resolved" in notes or "no such host" in notes:
        return "The domain could not be resolved. Check that it exists and is spelled correctly."
    if "timeout" in notes or "timed out" in notes:
        return "The site did not respond before the connection timed out."
    if result.status == ExtractionStatus.PARSE_FAILED:
        return "The site responded, but its public page could not be read safely."
    if result.status == ExtractionStatus.NETWORK_FAILED:
        return "A connection to the site could not be established."
    return "Public website research could not be completed."


def _advance(
    workflow: WorkflowRun,
    state: WorkflowState,
    detail: str,
    progress_callback: ProgressCallback | None,
) -> None:
    workflow.advance(state, detail)
    if progress_callback:
        progress_callback(workflow.model_copy(deep=True))


def _failed_snapshot(
    domain: str,
    homepage: str,
    results: list[ExtractionResult],
    workflow: WorkflowRun,
    detail: str,
    progress_callback: ProgressCallback | None = None,
) -> CompetitorSnapshot:
    _advance(workflow, WorkflowState.FAILED, detail, progress_callback)
    empty_profile = NormalizedBusinessProfile(domain=domain)
    return CompetitorSnapshot(
        domain=domain,
        homepage=homepage,
        results=results,
        validation=validate_business_profile(results, empty_profile),
        workflow=workflow,
        failure_reason=describe_collection_failure(results) or detail,
    )


def _robots_result(decision: RobotsDecision) -> ExtractionResult:
    if decision.status == ExtractionStatus.OK and decision.allowed:
        return ExtractionResult(
            value="allowed",
            source_url=decision.robots_url,
            extractor_name="robots_policy",
            confidence=1.0,
            status=ExtractionStatus.OK,
            source_type=SourceType.COMPANY_PAGE,
            notes=decision.reason,
        )
    return ExtractionResult.unavailable(
        extractor_name="robots_policy",
        source_url=decision.robots_url,
        status=decision.status,
        notes=decision.reason,
    )


def _sitemap_result(result: SitemapResult) -> ExtractionResult:
    if result.status == ExtractionStatus.OK:
        return ExtractionResult(
            value={"usable_urls": len(result.urls)},
            source_url=result.sitemap_url,
            final_url=result.final_url,
            http_status=result.http_status,
            extractor_name="sitemap_discovery",
            confidence=1.0,
            status=ExtractionStatus.OK,
            source_type=SourceType.PUBLIC_FEED,
            notes=result.notes,
        )
    return ExtractionResult.unavailable(
        extractor_name="sitemap_discovery",
        source_url=result.sitemap_url,
        final_url=result.final_url,
        http_status=result.http_status,
        status=result.status,
        notes=result.notes,
    )


def _crawl_plan_result(plan: CrawlPlan, source_url: str) -> ExtractionResult:
    if not plan.selected:
        return ExtractionResult.unavailable(
            extractor_name="ranked_crawl_plan",
            source_url=source_url,
            notes="No high-signal GTM pages were selected.",
        )
    value = [
        {
            "category": candidate.primary_category,
            "url": str(candidate.url),
            "score": candidate.score,
            "source": candidate.source.value,
        }
        for candidate in plan.selected
    ]
    return ExtractionResult(
        value=value,
        source_url=source_url,
        extractor_name="ranked_crawl_plan",
        confidence=0.8,
        status=ExtractionStatus.OK,
        source_type=SourceType.MIXED_PUBLIC_SIGNALS,
        notes=(
            f"Selected {len(plan.selected)} of {plan.candidate_count} candidate pages. "
            "This is a deterministic crawl priority, not a business conclusion."
        ),
        evidence_kind=EvidenceKind.INFERRED,
    )


async def _feed_activity(html: str, final_url: str) -> ExtractionResult | None:
    feed_urls = discover_feed_urls(html, final_url)
    return await fetch_recent_activity(feed_urls) if feed_urls else None


def _collect_social_links(results: list[ExtractionResult]) -> list[str]:
    allowed_hosts = {"instagram.com", "linkedin.com"}
    links: list[str] = []
    for result in results:
        if (
            result.status != ExtractionStatus.OK
            or result.extractor_name != "structured_social_links"
        ):
            continue
        if not isinstance(result.value, list):
            continue
        for value in result.value:
            if not isinstance(value, str):
                continue
            try:
                host = value.split("/")[2].removeprefix("www.").casefold()
            except IndexError:
                continue
            if host in allowed_hosts and value not in links:
                links.append(value)
    return links[:6]


async def _apify_enrichment(
    domain: str,
    homepage: str,
    results: list[ExtractionResult],
    *,
    enable_ai: bool,
) -> tuple[list[ExtractionResult], float]:
    if not settings.apify_enabled or not settings.apify_api_token:
        return build_apify_enrichment_results(domain, {}, {}), 0.0
    social_links = _collect_social_links(results)
    specs = build_apify_actor_specs(
        domain,
        homepage,
        social_links,
        enable_ai=enable_ai,
        apify_budget_usd=settings.apify_max_cost_usd,
        reddit_actor_id=settings.apify_reddit_actor_id,
    )
    estimated_cost = estimate_apify_actor_cost_usd(specs)
    datasets = await run_configured_actors(
        settings.apify_api_token,
        specs,
        timeout_seconds=settings.apify_timeout_seconds,
    )
    comment_spec = (
        build_instagram_comment_actor_spec(instagram_post_urls_from_datasets(datasets))
        if enable_ai
        else None
    )
    remaining_apify_budget = settings.apify_max_cost_usd - estimate_apify_actor_cost_usd(specs)
    comment_cost = (
        estimate_apify_actor_cost_usd({"instagram_comments": comment_spec})
        if comment_spec is not None
        else 0.0
    )
    if comment_spec is not None and remaining_apify_budget >= comment_cost:
        estimated_cost += comment_cost
        comment_datasets = await run_configured_actors(
            settings.apify_api_token,
            {"instagram_comments": comment_spec},
            timeout_seconds=settings.apify_timeout_seconds,
        )
        datasets.update(comment_datasets)
    return build_apify_enrichment_results(domain, datasets, {}), estimated_cost


async def _homepage_analysis(
    workflow: WorkflowRun,
    domain: str,
    fetched,
) -> dict:
    text = fetched.text
    final_url = fetched.final_url
    registry = NodeRegistry()
    nodes = [
        WorkflowNode(
            "homepage_metadata",
            lambda: asyncio.to_thread(extract_page_metadata, text, final_url),
            failure_policy=NodeFailurePolicy.OPTIONAL,
        ),
        WorkflowNode(
            "homepage_structured_data",
            lambda: asyncio.to_thread(extract_structured_data, text, final_url),
            failure_policy=NodeFailurePolicy.OPTIONAL,
        ),
        WorkflowNode(
            "homepage_feed",
            lambda: _feed_activity(text, final_url),
            failure_policy=NodeFailurePolicy.OPTIONAL,
        ),
        WorkflowNode(
            "homepage_positioning",
            lambda: asyncio.to_thread(extract_gtm_page_fact, text, final_url, "positioning"),
        ),
        WorkflowNode(
            "homepage_products",
            lambda: asyncio.to_thread(
                extract_gtm_page_fact,
                text,
                final_url,
                BusinessCategory.PRODUCTS_MODULES,
            ),
        ),
        WorkflowNode(
            "homepage_discovery",
            lambda: asyncio.to_thread(
                lambda: (
                    discover_homepage_candidates(text, final_url),
                    discover_relevant_links(text, final_url),
                )
            ),
        ),
        WorkflowNode(
            "sitemap_discovery",
            lambda: fetch_sitemap(domain),
            failure_policy=NodeFailurePolicy.OPTIONAL,
        ),
        WorkflowNode(
            "tech_signals",
            lambda: asyncio.to_thread(
                detect_tech_signals,
                text,
                dict(fetched.headers),
                final_url,
            ),
            failure_policy=NodeFailurePolicy.OPTIONAL,
        ),
    ]
    if _should_probe_shopify_catalog(text):
        nodes.append(
            WorkflowNode(
                "shopify_product_catalog",
                lambda: fetch_shopify_products(domain),
                failure_policy=NodeFailurePolicy.OPTIONAL,
            )
        )
    for node in nodes:
        registry.register(node)
    outcomes = await execute_parallel_nodes(workflow, registry.values())
    return {name: outcome.value for name, outcome in outcomes.items()}


async def build_preview_snapshot(
    raw_domain: str,
    *,
    enable_ai: bool = True,
    progress_callback: ProgressCallback | None = None,
) -> CompetitorSnapshot:
    domain = normalize_domain(raw_domain)
    url = homepage_url(domain)
    results: list[ExtractionResult] = []
    workflow = WorkflowRun(domain=domain)
    _advance(
        workflow,
        WorkflowState.SCRAPING,
        "Started robots and homepage collection.",
        progress_callback,
    )

    robots = await can_fetch_url(url)
    results.append(_robots_result(robots))
    if not robots.allowed and robots.status != ExtractionStatus.NO_DATA:
        return _failed_snapshot(
            domain,
            url,
            results,
            workflow,
            "Homepage collection was blocked by robots policy.",
            progress_callback,
        )

    try:
        fetched = await fetch_text(url)
    except FetchError as exc:
        results.append(
            ExtractionResult.unavailable(
                extractor_name="homepage_fetch",
                source_url=exc.source_url,
                status=exc.status,
                notes=str(exc),
                final_url=exc.final_url,
                http_status=exc.http_status,
            )
        )
        return _failed_snapshot(
            domain,
            url,
            results,
            workflow,
            "Homepage collection failed.",
            progress_callback,
        )
    except ValueError as exc:
        results.append(
            ExtractionResult.unavailable(
                extractor_name="homepage_fetch",
                source_url=url,
                status=ExtractionStatus.NETWORK_FAILED,
                notes=str(exc),
            )
        )
        return _failed_snapshot(
            domain,
            url,
            results,
            workflow,
            "Homepage collection failed.",
            progress_callback,
        )

    if settings.rendered_browser_enabled and has_sparse_business_html(fetched.text):
        try:
            rendered = await fetch_rendered_text(fetched.final_url)
            fetched = fetched.__class__(
                text=rendered.text,
                headers=fetched.headers,
                final_url=rendered.final_url,
                http_status=rendered.http_status,
            )
        except FetchError:
            pass

    _advance(
        workflow,
        WorkflowState.CLASSIFYING,
        "Classifying discovered public pages.",
        progress_callback,
    )
    homepage_analysis = await _homepage_analysis(workflow, domain, fetched)
    results.extend(homepage_analysis.get("homepage_metadata") or [])
    results.extend(homepage_analysis.get("homepage_structured_data") or [])
    feed_activity = homepage_analysis.get("homepage_feed")
    if feed_activity:
        results.append(feed_activity)
    homepage_fact = homepage_analysis.get("homepage_positioning")
    if homepage_fact and (homepage_fact.headline or homepage_fact.claims):
        results.append(
            ExtractionResult(
                value=homepage_fact.model_dump(mode="json"),
                source_url=fetched.final_url,
                final_url=fetched.final_url,
                http_status=fetched.http_status,
                extractor_name="positioning_facts",
                confidence=0.8,
                status=ExtractionStatus.OK,
                source_type=SourceType.HTML,
                notes="Observed public claims extracted from the homepage.",
                evidence=" | ".join(claim.evidence_excerpt for claim in homepage_fact.claims[:4])[
                    :1000
                ],
            )
        )
    homepage_products = homepage_analysis.get("homepage_products")
    homepage_product_claims = [
        claim
        for claim in (homepage_products.claims if homepage_products else [])
        if claim.fact_type in {"linked_product", "product_collection", "visible_price"}
    ]
    if homepage_product_claims:
        homepage_products.claims = homepage_product_claims
        results.append(
            ExtractionResult(
                value=homepage_products.model_dump(mode="json"),
                source_url=fetched.final_url,
                final_url=fetched.final_url,
                http_status=fetched.http_status,
                extractor_name="homepage_products_facts",
                confidence=0.8,
                status=ExtractionStatus.OK,
                source_type=SourceType.HTML,
                notes="Observed product and collection links extracted from the homepage.",
                evidence=" | ".join(
                    claim.evidence_excerpt for claim in homepage_product_claims[:4]
                )[:1000],
            )
        )
    shopify_catalog = homepage_analysis.get("shopify_product_catalog")
    if shopify_catalog:
        results.append(shopify_catalog)
    homepage_candidates, discovered = homepage_analysis.get("homepage_discovery") or ([], {})
    discovered_value = {key: links[:5] for key, links in discovered.items() if links}
    if discovered_value:
        results.append(
            ExtractionResult(
                value=discovered_value,
                source_url=fetched.final_url,
                final_url=fetched.final_url,
                http_status=fetched.http_status,
                extractor_name="business_page_map",
                confidence=0.7,
                status=ExtractionStatus.OK,
                notes="Candidate GTM pages discovered from same-site public homepage links.",
            )
        )
    else:
        results.append(
            ExtractionResult.unavailable(
                extractor_name="business_page_map",
                source_url=fetched.final_url,
                notes="No high-signal business pages were linked from the homepage.",
            )
        )

    sitemap = homepage_analysis.get("sitemap_discovery") or SitemapResult(
        urls=[],
        sitemap_url=f"https://{domain}/sitemap.xml",
        status=ExtractionStatus.NO_DATA,
        notes="Sitemap discovery node returned no result.",
    )
    results.append(_sitemap_result(sitemap))
    sitemap_candidates = discover_sitemap_candidates(sitemap.urls, fetched.final_url)
    crawl_plan = build_crawl_plan(
        homepage_candidates=homepage_candidates,
        sitemap_candidates=sitemap_candidates,
        selection_limit=settings.crawl_selection_limit,
    )
    results.append(_crawl_plan_result(crawl_plan, fetched.final_url))
    _advance(
        workflow,
        WorkflowState.EXTRACTING,
        "Extracting facts from selected pages.",
        progress_callback,
    )
    first_batch = await extract_ranked_pages_with_candidates(crawl_plan)
    results.extend(first_batch.results)
    answered_categories = {
        BusinessCategory(result.extractor_name.removesuffix("_facts"))
        for result in first_batch.results
        if result.status == ExtractionStatus.OK and result.extractor_name.endswith("_facts")
    }
    remaining_limit = max(
        0,
        min(
            3,
            settings.crawl_max_pages_per_domain - len(crawl_plan.selected),
        ),
    )
    if remaining_limit:
        second_plan = build_question_driven_plan(
            candidates=first_batch.discovered_candidates,
            answered_categories=answered_categories,
            already_selected_urls={str(item.url) for item in crawl_plan.selected},
            selection_limit=remaining_limit,
        )
        if second_plan.selected:
            results.append(_crawl_plan_result(second_plan, fetched.final_url))
            second_batch = await extract_ranked_pages_with_candidates(second_plan)
            results.extend(second_batch.results)

    tech_result = homepage_analysis.get("tech_signals")
    if tech_result:
        results.append(tech_result)
    apify_estimated_cost_usd = 0.0
    apify_results = await execute_node(
        workflow,
        WorkflowNode(
            "apify_public_enrichment",
            lambda: _apify_enrichment(domain, fetched.final_url, results, enable_ai=enable_ai),
            failure_policy=NodeFailurePolicy.OPTIONAL,
        ),
    )
    if apify_results.value:
        enrichment_results, apify_estimated_cost_usd = apify_results.value
        results.extend(enrichment_results)
    _advance(
        workflow,
        WorkflowState.VALIDATING,
        "Normalizing and validating extracted facts.",
        progress_callback,
    )
    normalized_outcome = await execute_node(
        workflow,
        WorkflowNode(
            "normalize_business_evidence",
            lambda: asyncio.to_thread(build_normalized_business_profile, domain, results),
            failure_policy=NodeFailurePolicy.FATAL,
        ),
    )
    business_profile = normalized_outcome.value
    validation_outcome = await execute_node(
        workflow,
        WorkflowNode(
            "validate_business_evidence",
            lambda: asyncio.to_thread(validate_business_profile, results, business_profile),
            failure_policy=NodeFailurePolicy.FATAL,
        ),
    )
    validation = validation_outcome.value
    intelligence_outcome = await execute_node(
        workflow,
        WorkflowNode(
            "assemble_structured_intelligence",
            lambda: asyncio.to_thread(
                build_structured_intelligence,
                business_profile,
                validation,
            ),
            failure_policy=NodeFailurePolicy.FATAL,
        ),
    )
    intelligence = intelligence_outcome.value
    report_business_profile = intelligence.to_business_profile()
    profile = build_competitor_profile(domain, results)
    ai_analysis = None
    ai_run = None
    ai_analysis_status = (
        "disabled" if not enable_ai or not settings.ai_analysis_enabled else "not_configured"
    )
    if not validation.ready_for_report:
        ai_analysis_status = "validation_blocked"
    elif enable_ai:
        analysis_node = build_strategic_analysis_node(settings)
        if analysis_node is None:
            ai_analysis_status = "not_configured"
            workflow.node_runs.append(
                NodeRun(
                    name="strategic_ai_analysis",
                    version=settings.ai_prompt_version,
                    failure_policy=NodeFailurePolicy.OPTIONAL,
                    status=NodeStatus.SKIPPED,
                    message="AI analysis is disabled or no API key is configured.",
                )
            )
        else:
            analysis_outcome = await execute_node(
                workflow,
                WorkflowNode(
                    analysis_node.name,
                    lambda: analysis_node.run(report_business_profile),
                    version=analysis_node.version,
                    failure_policy=NodeFailurePolicy.OPTIONAL,
                ),
            )
            ai_run = analysis_outcome.value
            if ai_run:
                ai_analysis = ai_run.analysis
                ai_analysis_status = ai_run.status
                if ai_run.status in {"failed", "budget_blocked"}:
                    workflow.node_runs[-1].status = NodeStatus.FAILED
                    workflow.node_runs[-1].message = ai_run.message
            elif analysis_outcome.error:
                ai_analysis_status = "failed"
    else:
        workflow.node_runs.append(
            NodeRun(
                name="strategic_ai_analysis",
                version=settings.ai_prompt_version,
                failure_policy=NodeFailurePolicy.OPTIONAL,
                status=NodeStatus.SKIPPED,
                message="AI analysis was disabled for this workflow run.",
            )
        )
    terminal_state = (
        WorkflowState.PARTIAL
        if not validation.ready_for_report
        or any(issue.code == "partial_collection" for issue in validation.issues)
        or any(
            node.status == NodeStatus.FAILED and node.failure_policy == NodeFailurePolicy.PARTIAL
            for node in workflow.node_runs
        )
        else WorkflowState.COMPLETE
    )
    _advance(
        workflow,
        terminal_state,
        "Workflow finished after deterministic validation.",
        progress_callback,
    )
    return CompetitorSnapshot(
        domain=domain,
        homepage=url,
        results=results,
        crawl_plan=crawl_plan,
        profile=profile,
        business_profile=report_business_profile,
        intelligence=intelligence,
        ai_analysis=ai_analysis,
        ai_analysis_status=ai_analysis_status,
        ai_run=ai_run,
        apify_estimated_cost_usd=apify_estimated_cost_usd,
        validation=validation,
        workflow=workflow,
    )


def _should_probe_shopify_catalog(html: str) -> bool:
    lowered = html.casefold()
    return any(
        signal in lowered
        for signal in (
            "cdn.shopify.com",
            "shopify.theme",
            "/collections/",
            "/products/",
        )
    )
