import asyncio
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass(frozen=True)
class ApifyActorSpec:
    actor_id: str
    payload: dict[str, Any] = field(default_factory=dict)


class ApifyActorClient:
    def __init__(
        self,
        token: str,
        *,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = "https://api.apify.com",
        timeout_seconds: float = 120.0,
    ) -> None:
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client

    async def run_actor(self, actor_id: str, payload: dict[str, Any]) -> list[dict]:
        owns_client = self._http_client is None
        client = self._http_client or httpx.AsyncClient(timeout=self.timeout_seconds)
        try:
            encoded_actor = actor_id.replace("/", "~")
            run_response = await client.post(
                f"{self.base_url}/v2/acts/{encoded_actor}/runs",
                params={"token": self.token, "waitForFinish": str(int(self.timeout_seconds))},
                json=payload,
            )
            run_response.raise_for_status()
            dataset_id = run_response.json().get("data", {}).get("defaultDatasetId")
            if not dataset_id:
                return []
            dataset_response = await client.get(
                f"{self.base_url}/v2/datasets/{dataset_id}/items",
                params={"token": self.token, "clean": "true", "format": "json"},
            )
            dataset_response.raise_for_status()
            data = dataset_response.json()
            return data if isinstance(data, list) else []
        finally:
            if owns_client:
                await client.aclose()


async def run_configured_actors(
    token: str,
    specs: dict[str, ApifyActorSpec],
    *,
    http_client: httpx.AsyncClient | None = None,
    timeout_seconds: float = 120.0,
) -> dict[str, list[dict]]:
    if not token or not specs:
        return {}
    client = ApifyActorClient(
        token,
        http_client=http_client,
        timeout_seconds=timeout_seconds,
    )

    async def run_one(name: str, spec: ApifyActorSpec) -> tuple[str, list[dict]]:
        try:
            return name, await client.run_actor(spec.actor_id, spec.payload)
        except (httpx.HTTPError, ValueError, KeyError):
            return name, []

    pairs = await asyncio.gather(*(run_one(name, spec) for name, spec in specs.items()))
    return {name: items for name, items in pairs if items}
