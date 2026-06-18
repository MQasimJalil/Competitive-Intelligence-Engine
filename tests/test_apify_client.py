import httpx
import pytest
from app.adapters.apify_client import ApifyActorClient, ApifyActorSpec, run_configured_actors


@pytest.mark.anyio
async def test_apify_client_runs_actor_and_fetches_dataset_items():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/runs"):
            return httpx.Response(201, json={"data": {"defaultDatasetId": "dataset-1"}})
        if request.url.path.endswith("/items"):
            return httpx.Response(200, json=[{"value": "ok"}])
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = ApifyActorClient("token", http_client=http_client)
        items = await client.run_actor("apify/instagram-scraper", {"directUrls": ["x"]})

    assert items == [{"value": "ok"}]
    assert requests[0].url.path == "/v2/acts/apify~instagram-scraper/runs"
    assert requests[0].url.params["token"] == "token"


@pytest.mark.anyio
async def test_run_configured_actors_skips_without_token():
    specs = {"instagram": ApifyActorSpec(actor_id="apify/instagram-scraper", payload={})}

    assert await run_configured_actors("", specs) == {}


@pytest.mark.anyio
async def test_run_configured_actors_isolates_actor_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        if "instagram" in str(request.url):
            return httpx.Response(500, json={"error": "broken"})
        if request.url.path.endswith("/runs"):
            return httpx.Response(201, json={"data": {"defaultDatasetId": "dataset-2"}})
        if request.url.path.endswith("/items"):
            return httpx.Response(200, json=[{"value": "linkedin"}])
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        datasets = await run_configured_actors(
            "token",
            {
                "instagram": ApifyActorSpec(
                    actor_id="apify/instagram-scraper",
                    payload={"search": "example"},
                ),
                "linkedin": ApifyActorSpec(
                    actor_id="harvestapi/linkedin-company",
                    payload={"companies": ["example.com"]},
                ),
            },
            http_client=http_client,
        )

    assert datasets == {"linkedin": [{"value": "linkedin"}]}
