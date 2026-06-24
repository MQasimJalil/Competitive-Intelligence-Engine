import pytest
from app.adapters.apify_enrichment import (
    build_apify_actor_specs,
    build_apify_enrichment_results,
    estimate_apify_actor_cost_usd,
    linkedin_company_result,
    reddit_result,
    search_results_result,
    social_profile_result,
    website_content_result,
)
from app.schemas import BusinessCategory, ExtractionStatus, SourceType


def _claims(result):
    return result.value["claims"]


def test_instagram_dataset_becomes_cited_social_proof_claims():
    result = social_profile_result(
        "example.com",
        [
            {
                "url": "https://www.instagram.com/example/",
                "username": "example",
                "fullName": "Example Gloves",
                "biography": "Goalkeeper gloves for serious keepers",
                "followersCount": 12000,
                "postsCount": 220,
                "latestPosts": [
                    {
                        "url": "https://www.instagram.com/p/abc/",
                        "caption": "New negative cut gloves are live",
                        "likesCount": 410,
                        "commentsCount": 22,
                        "timestamp": "2026-06-01T10:00:00.000Z",
                    }
                ],
            }
        ],
    )

    assert result.status == ExtractionStatus.OK
    assert result.source_type == SourceType.PUBLIC_API
    claims = _claims(result)
    assert any(claim["fact_type"] == "social_followers" for claim in claims)
    assert any(claim["fact_type"] == "social_post_engagement" for claim in claims)
    assert claims[0]["source_url"] == "https://www.instagram.com/example/"
    assert claims[0]["category"] == BusinessCategory.PROOF


def test_instagram_flat_post_items_become_engagement_and_caption_claims():
    result = social_profile_result(
        "example.com",
        [
            {
                "inputUrl": "https://www.instagram.com/example/",
                "url": "https://www.instagram.com/p/abc/",
                "ownerUsername": "example",
                "caption": "Customers wearing the new match gloves",
                "likesCount": 410,
                "commentsCount": 22,
                "firstComment": "These look great",
            }
        ],
    )

    assert result.status == ExtractionStatus.OK
    claims = _claims(result)
    assert any(claim["fact_type"] == "social_post_engagement" for claim in claims)
    assert any(claim["fact_type"] == "social_post_caption" for claim in claims)
    assert any(claim["fact_type"] == "social_comment_excerpt" for claim in claims)


def test_instagram_comment_items_become_public_comment_claims():
    result = social_profile_result(
        "example.com",
        [
            {
                "postId": "C3TTthZLoQK",
                "text": "Best grip I have used this season",
                "ownerUsername": "keeperbuyer",
                "timestamp": "2026-06-01T10:00:00.000Z",
            }
        ],
    )

    assert result.status == ExtractionStatus.OK
    claim = _claims(result)[0]
    assert claim["fact_type"] == "social_comment_excerpt"
    assert claim["value"] == "Public Instagram comment: Best grip I have used this season"


def test_reddit_dataset_becomes_public_perception_claims():
    result = reddit_result(
        "example.com",
        [
            {
                "title": "Anyone tried Example gloves?",
                "url": "https://www.reddit.com/r/GoalKeepers/comments/abc/example/",
                "body": "The latex grip is strong but delivery took a while.",
                "score": 18,
                "commentsCount": 7,
            },
            {
                "comment": "Good value for training, not my match-day glove.",
                "postUrl": "https://www.reddit.com/r/GoalKeepers/comments/abc/example/",
                "score": 4,
            },
        ],
    )

    assert result.status == ExtractionStatus.OK
    claims = _claims(result)
    assert claims[0]["fact_type"] == "reddit_thread_signal"
    assert claims[0]["category"] == BusinessCategory.PROOF
    assert any(claim["fact_type"] == "reddit_comment_excerpt" for claim in claims)


def test_linkedin_company_dataset_becomes_company_and_proof_claims():
    result = linkedin_company_result(
        "example.com",
        [
            {
                "linkedinUrl": "https://www.linkedin.com/company/example",
                "name": "Example Inc.",
                "description": "Example builds planning software for modern teams.",
                "employeeCount": 58,
                "followerCount": 9000,
                "industries": ["Software Development"],
                "locations": [{"parsed": {"text": "San Francisco, CA, United States"}}],
            }
        ],
    )

    assert result.status == ExtractionStatus.OK
    claims = _claims(result)
    assert any(claim["fact_type"] == "linkedin_employee_count" for claim in claims)
    assert any(claim["fact_type"] == "linkedin_followers" for claim in claims)
    assert any(claim["category"] == BusinessCategory.POSITIONING for claim in claims)


def test_search_results_dataset_becomes_external_mention_claims():
    result = search_results_result(
        "example.com",
        [
            {
                "organicResults": [
                    {
                        "title": "Example review",
                        "url": "https://reviews.example/example",
                        "description": "A detailed user review of Example.",
                    },
                    {
                        "title": "Example homepage",
                        "url": "https://example.com",
                        "description": "Official website.",
                    },
                ]
            }
        ],
    )

    assert result.status == ExtractionStatus.OK
    claims = _claims(result)
    assert claims[0]["fact_type"] == "external_mention"
    assert claims[0]["source_url"] == "https://reviews.example/example"


def test_website_content_dataset_becomes_fallback_public_claims():
    result = website_content_result(
        "example.com",
        [
            {
                "url": "https://example.com/pricing",
                "text": "Starter plan costs $19 per month. Teams can upgrade for SSO.",
            }
        ],
    )

    assert result.status == ExtractionStatus.OK
    claims = _claims(result)
    assert any(claim["fact_type"] == "fallback_page_claim" for claim in claims)


def test_empty_apify_outputs_are_no_data_not_guessed():
    result = build_apify_enrichment_results("example.com", {}, {})

    assert len(result) == 5
    assert {item.status for item in result} == {ExtractionStatus.NO_DATA}


def test_build_actor_specs_free_mode_uses_profile_only_and_skips_deep_social():
    specs = build_apify_actor_specs(
        "sologk.com",
        "https://sologk.com/",
        [
            "https://www.instagram.com/sologkgloves/",
            "https://www.linkedin.com/company/sologk/",
            "https://x.com/sologk",
        ],
        enable_ai=False,
    )

    assert set(specs) == {"instagram"}
    assert specs["instagram"].actor_id == "apify/instagram-scraper"
    assert specs["instagram"].payload["resultsType"] == "details"
    assert specs["instagram"].payload["resultsLimit"] == 1
    assert "https://www.instagram.com/sologkgloves/" in str(specs["instagram"].payload)


def test_build_actor_specs_ai_mode_is_fast_by_default():
    specs = build_apify_actor_specs(
        "sologk.com",
        "https://sologk.com/",
        [
            "https://www.instagram.com/sologkgloves/",
            "https://www.linkedin.com/company/sologk/",
        ],
        enable_ai=True,
        apify_budget_usd=0.05,
    )

    assert "instagram" in specs
    assert "linkedin" in specs
    assert "instagram_posts" not in specs
    assert "reddit_search" not in specs
    assert "google_search" not in specs
    assert "website_content" not in specs
    assert specs["linkedin"].actor_id == "harvestapi/linkedin-company"
    assert "https://www.linkedin.com/company/sologk/" in str(specs["linkedin"].payload)


def test_build_actor_specs_deep_enrichment_is_opt_in():
    specs = build_apify_actor_specs(
        "sologk.com",
        "https://sologk.com/",
        [
            "https://www.instagram.com/sologkgloves/",
            "https://www.linkedin.com/company/sologk/",
        ],
        enable_ai=True,
        include_deep_social=True,
        include_reddit=True,
        include_search=True,
        include_website_content=True,
        apify_budget_usd=0.05,
    )

    assert "instagram_posts" in specs
    assert specs["instagram_posts"].payload["resultsLimit"] <= 3
    assert "reddit_search" in specs
    assert "reddit.com" in str(specs["reddit_search"].payload).casefold()
    assert "google_search" in specs
    assert "website_content" in specs


def test_build_actor_specs_skips_social_actors_without_discovered_social_links():
    specs = build_apify_actor_specs("sologk.com", "https://sologk.com/", [], enable_ai=True)

    assert "instagram" not in specs
    assert "instagram_posts" not in specs
    assert "linkedin" not in specs
    assert "google_search" not in specs
    assert "website_content" not in specs


def test_build_actor_specs_respects_apify_budget_before_calling_paid_actors():
    specs = build_apify_actor_specs(
        "sologk.com",
        "https://sologk.com/",
        [
            "https://www.instagram.com/sologkgloves/",
            "https://www.linkedin.com/company/sologk/",
        ],
        enable_ai=True,
        apify_budget_usd=0.002,
    )

    assert "instagram" not in specs
    assert "instagram_posts" not in specs
    assert "linkedin" in specs


def test_estimated_apify_cost_tracks_selected_actor_specs():
    specs = build_apify_actor_specs(
        "sologk.com",
        "https://sologk.com/",
        [
            "https://www.instagram.com/sologkgloves/",
            "https://www.linkedin.com/company/sologk/",
        ],
        enable_ai=True,
        apify_budget_usd=0.008,
        include_deep_social=True,
        include_reddit=True,
    )

    assert estimate_apify_actor_cost_usd(specs) <= 0.008
    assert (
        estimate_apify_actor_cost_usd({**specs, "instagram_comments": specs["instagram"]}) > 0.008
    )


@pytest.mark.parametrize(
    ("actor_key", "expected"),
    [
        ("instagram", "apify_instagram_facts"),
        ("instagram_posts", "apify_instagram_facts"),
        ("instagram_comments", "apify_instagram_facts"),
        ("linkedin", "apify_linkedin_company_facts"),
        ("reddit_search", "apify_reddit_facts"),
        ("google_search", "apify_search_facts"),
        ("website_content", "apify_website_content_facts"),
    ],
)
def test_apify_dispatcher_maps_actor_outputs(actor_key, expected):
    datasets = {
        actor_key: [
            {
                "url": "https://www.instagram.com/example/",
                "followersCount": 1,
                "linkedinUrl": "https://www.linkedin.com/company/example",
                "name": "Example",
                "organicResults": [{"title": "Mention", "url": "https://news.example"}],
                "title": "Example Reddit thread",
                "body": "People praise the grip but mention slower delivery.",
                "comment": "Great grip, shipping could be better.",
                "text": "Example public page claim.",
            }
        ]
    }

    results = build_apify_enrichment_results("example.com", datasets, {})

    assert any(result.extractor_name == expected for result in results)
