from httpx import AsyncClient


async def test_approve_closes_the_case_and_uses_the_session_user(
    client: AsyncClient, acme: dict[str, str]
) -> None:
    response = await client.post(
        "/api/acme/cases/31/feedback",
        json={"verdict": "approve", "note": "confirmed", "analyst": "mallory"},
        headers=acme,
    )
    assert response.status_code == 200
    assert response.json()["playbook_created"] is None

    case = (await client.get("/api/acme/cases/31", headers=acme)).json()
    assert case["status"] == "closed"
    assert case["decision"]["outcome"] == "approved"
    assert [(f["verdict"], f["analyst"]) for f in case["feedback"]] == [("approve", "acme.analyst")]


async def test_approve_twice_is_a_conflict(client: AsyncClient, acme: dict[str, str]) -> None:
    url = "/api/acme/cases/31/feedback"
    assert (await client.post(url, json={"verdict": "approve"}, headers=acme)).status_code == 200
    assert (await client.post(url, json={"verdict": "reject"}, headers=acme)).status_code == 409


async def test_benign_allowed_on_a_closed_case_only_as_benign(
    client: AsyncClient, acme: dict[str, str]
) -> None:
    url = "/api/acme/cases/32/feedback"
    assert (await client.post(url, json={"verdict": "approve"}, headers=acme)).status_code == 409
    assert (
        await client.post(url, json={"verdict": "benign", "note": "still benign"}, headers=acme)
    ).status_code == 200


async def test_benign_on_awaiting_case_learns_a_playbook(
    client: AsyncClient, acme: dict[str, str]
) -> None:
    response = await client.post(
        "/api/acme/cases/31/feedback",
        json={"verdict": "benign", "note": "red team exercise"},
        headers=acme,
    )
    assert response.status_code == 200
    created = response.json()["playbook_created"]
    assert created is not None

    playbooks = (await client.get("/api/acme/playbooks", headers=acme)).json()
    assert any(
        f"{p['name']} v{p['version']}" == created and p["source_case"] == 31 for p in playbooks
    )


async def test_feedback_validation(client: AsyncClient, acme: dict[str, str]) -> None:
    url = "/api/acme/cases/31/feedback"
    assert (await client.post(url, json={"verdict": "maybe"}, headers=acme)).status_code == 422
    assert (
        await client.post(url, json={"verdict": "approve", "note": "x" * 501}, headers=acme)
    ).status_code == 422
    assert (
        await client.post("/api/acme/cases/999/feedback", json={"verdict": "approve"}, headers=acme)
    ).status_code == 404
