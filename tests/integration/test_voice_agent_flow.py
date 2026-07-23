"""The endpoints a voice booking agent actually strings together.

Registering an unknown caller and surviving a dropped call are the two things
that turn this API from "browsable" into "usable by a phone agent", so they are
exercised as one flow rather than as isolated endpoints.
"""

from uuid import uuid4

from httpx import AsyncClient

from tests.fakes import FakeBookingRepository


async def test_a_new_caller_can_be_registered_and_booked(
    client: AsyncClient,
    slots: FakeBookingRepository,
    auth_headers: dict[str, str],
) -> None:
    # 1. The caller is not in the system: "I don't have you yet, what's your name?"
    missing = await client.get("/api/v1/customers", params={"search": "Priya Raman"})
    assert missing.json()["total"] == 0

    # 2. Register them.
    created = await client.post(
        "/api/v1/customers",
        json={"name": "Priya Raman", "notes": "Called about a table on Friday."},
        headers=auth_headers,
    )
    assert created.status_code == 201
    assert created.json()["status"] == "lead"
    customer_id = created.json()["id"]

    # 3. Offer a slot and book it.
    slot_id = str(next(iter(slots.slots)))
    booked = await client.post(
        "/api/v1/bookings",
        json={"customer_id": customer_id, "slot_id": slot_id, "party_size": 2},
        headers=auth_headers,
    )

    assert booked.status_code == 201
    # 4. And they are now findable by name on the next call.
    assert (await client.get("/api/v1/customers", params={"search": "priya"})).json()["total"] == 1


async def test_registering_a_customer_needs_the_api_key(client: AsyncClient) -> None:
    response = await client.post("/api/v1/customers", json={"name": "Anonymous"})

    assert response.status_code == 401


async def test_a_blank_name_is_rejected(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.post("/api/v1/customers", json={"name": "   "}, headers=auth_headers)

    assert response.status_code in (400, 422)


async def test_the_same_name_twice_creates_two_people(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    # Names are not unique in reality; silently merging two callers would be
    # worse than a duplicate row.
    first = await client.post("/api/v1/customers", json={"name": "Anna Petrova"}, headers=auth_headers)
    second = await client.post("/api/v1/customers", json={"name": "Anna Petrova"}, headers=auth_headers)

    assert first.json()["id"] != second.json()["id"]


async def test_a_dropped_call_can_retry_the_booking_safely(
    client: AsyncClient,
    customers,  # noqa: ANN001
    slots: FakeBookingRepository,
    auth_headers: dict[str, str],
) -> None:
    body = {
        "customer_id": str(customers.customers[0].id),
        "slot_id": str(next(iter(slots.slots))),
        "party_size": 2,
    }
    headers = {**auth_headers, "Idempotency-Key": str(uuid4())}

    first = await client.post("/api/v1/bookings", json=body, headers=headers)
    retry = await client.post("/api/v1/bookings", json=body, headers=headers)

    assert first.status_code == 201
    # The retry gets the same booking back, not "that slot is taken".
    assert retry.status_code == 201
    assert retry.json() == first.json()


async def test_a_retry_with_a_different_key_is_a_real_conflict(
    client: AsyncClient,
    customers,  # noqa: ANN001
    slots: FakeBookingRepository,
    auth_headers: dict[str, str],
) -> None:
    body = {
        "customer_id": str(customers.customers[0].id),
        "slot_id": str(next(iter(slots.slots))),
        "party_size": 2,
    }

    await client.post("/api/v1/bookings", json=body, headers={**auth_headers, "Idempotency-Key": str(uuid4())})
    other = await client.post("/api/v1/bookings", json=body, headers={**auth_headers, "Idempotency-Key": str(uuid4())})

    assert other.status_code == 409
    assert other.json()["error_code"] == "slot_unavailable"


async def test_reusing_a_key_for_a_different_booking_is_rejected(
    client: AsyncClient,
    customers,  # noqa: ANN001
    slots: FakeBookingRepository,
    auth_headers: dict[str, str],
) -> None:
    slot_ids = [str(slot_id) for slot_id in slots.slots]
    headers = {**auth_headers, "Idempotency-Key": "reused-key"}
    customer_id = str(customers.customers[0].id)

    await client.post(
        "/api/v1/bookings",
        json={"customer_id": customer_id, "slot_id": slot_ids[0], "party_size": 2},
        headers=headers,
    )
    reused = await client.post(
        "/api/v1/bookings",
        json={"customer_id": customer_id, "slot_id": slot_ids[1], "party_size": 2},
        headers=headers,
    )

    assert reused.status_code == 409
    assert reused.json()["error_code"] == "idempotency_key_reused"


async def test_booking_without_a_key_behaves_as_before(
    client: AsyncClient,
    customers,  # noqa: ANN001
    slots: FakeBookingRepository,
    auth_headers: dict[str, str],
) -> None:
    body = {
        "customer_id": str(customers.customers[0].id),
        "slot_id": str(next(iter(slots.slots))),
        "party_size": 2,
    }

    assert (await client.post("/api/v1/bookings", json=body, headers=auth_headers)).status_code == 201
    assert (await client.post("/api/v1/bookings", json=body, headers=auth_headers)).status_code == 409
