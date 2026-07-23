"""The endpoints a phone booking agent strings together.

Two things make this API usable from a live call: a booking needs nothing but a
slot and a name, and a dropped connection can be retried without guessing what
happened the first time.
"""

from uuid import uuid4

from httpx import AsyncClient

from tests.fakes import FakeBookingRepository


async def test_booking_a_table_takes_one_call(
    client: AsyncClient,
    slots: FakeBookingRepository,
    auth_headers: dict[str, str],
) -> None:
    # Offer what is free…
    offered = await client.get("/api/v1/booking-slots", params={"limit": 3})
    assert offered.status_code == 200
    slot_id = offered.json()["items"][0]["id"]

    # …then book it. No customer lookup, no account creation: a reservation is
    # a table under a name, and the CRM is a separate concern.
    booked = await client.post(
        "/api/v1/bookings",
        json={"guest_name": "Dmitri Volkov", "slot_id": slot_id, "party_size": 4},
        headers=auth_headers,
    )

    assert booked.status_code == 201
    assert booked.json()["guest_name"] == "Dmitri Volkov"
    assert "customer_id" not in booked.json()


async def test_the_guest_name_is_required(
    client: AsyncClient,
    slots: FakeBookingRepository,
    auth_headers: dict[str, str],
) -> None:
    response = await client.post(
        "/api/v1/bookings",
        json={"slot_id": str(next(iter(slots.slots))), "party_size": 2},
        headers=auth_headers,
    )

    assert response.status_code == 422


async def test_a_blank_guest_name_is_rejected(
    client: AsyncClient,
    slots: FakeBookingRepository,
    auth_headers: dict[str, str],
) -> None:
    response = await client.post(
        "/api/v1/bookings",
        json={"guest_name": "   ", "slot_id": str(next(iter(slots.slots))), "party_size": 2},
        headers=auth_headers,
    )

    assert response.status_code == 422


async def test_a_dropped_call_can_retry_the_booking_safely(
    client: AsyncClient,
    slots: FakeBookingRepository,
    auth_headers: dict[str, str],
) -> None:
    body = {"guest_name": "Dmitri Volkov", "slot_id": str(next(iter(slots.slots))), "party_size": 2}
    headers = {**auth_headers, "Idempotency-Key": str(uuid4())}

    first = await client.post("/api/v1/bookings", json=body, headers=headers)
    retry = await client.post("/api/v1/bookings", json=body, headers=headers)

    assert first.status_code == 201
    # The retry gets the same booking back, not "that slot is taken".
    assert retry.status_code == 201
    assert retry.json() == first.json()


async def test_a_retry_with_a_different_key_is_a_real_conflict(
    client: AsyncClient,
    slots: FakeBookingRepository,
    auth_headers: dict[str, str],
) -> None:
    body = {"guest_name": "Dmitri Volkov", "slot_id": str(next(iter(slots.slots))), "party_size": 2}

    await client.post("/api/v1/bookings", json=body, headers={**auth_headers, "Idempotency-Key": str(uuid4())})
    other = await client.post("/api/v1/bookings", json=body, headers={**auth_headers, "Idempotency-Key": str(uuid4())})

    assert other.status_code == 409
    assert other.json()["error_code"] == "slot_unavailable"


async def test_reusing_a_key_for_a_different_booking_is_rejected(
    client: AsyncClient,
    slots: FakeBookingRepository,
    auth_headers: dict[str, str],
) -> None:
    slot_ids = [str(slot_id) for slot_id in slots.slots]
    headers = {**auth_headers, "Idempotency-Key": "reused-key"}

    await client.post(
        "/api/v1/bookings",
        json={"guest_name": "Dmitri Volkov", "slot_id": slot_ids[0], "party_size": 2},
        headers=headers,
    )
    reused = await client.post(
        "/api/v1/bookings",
        json={"guest_name": "Dmitri Volkov", "slot_id": slot_ids[1], "party_size": 2},
        headers=headers,
    )

    assert reused.status_code == 409
    assert reused.json()["error_code"] == "idempotency_key_reused"


async def test_booking_without_a_key_behaves_as_before(
    client: AsyncClient,
    slots: FakeBookingRepository,
    auth_headers: dict[str, str],
) -> None:
    body = {"guest_name": "Dmitri Volkov", "slot_id": str(next(iter(slots.slots))), "party_size": 2}

    assert (await client.post("/api/v1/bookings", json=body, headers=auth_headers)).status_code == 201
    assert (await client.post("/api/v1/bookings", json=body, headers=auth_headers)).status_code == 409


class TestCustomerRegistration:
    """POST /customers stays for the CRM flows, not for taking a reservation."""

    async def test_a_customer_can_be_registered(self, client: AsyncClient, auth_headers: dict[str, str]) -> None:
        created = await client.post(
            "/api/v1/customers",
            json={"name": "Priya Raman", "notes": "Asked about the nutrition package."},
            headers=auth_headers,
        )

        assert created.status_code == 201
        assert created.json()["status"] == "lead"

    async def test_registering_needs_the_api_key(self, client: AsyncClient) -> None:
        assert (await client.post("/api/v1/customers", json={"name": "Anonymous"})).status_code == 401

    async def test_a_blank_name_is_rejected(self, client: AsyncClient, auth_headers: dict[str, str]) -> None:
        response = await client.post("/api/v1/customers", json={"name": "   "}, headers=auth_headers)

        assert response.status_code == 422

    async def test_the_same_name_twice_creates_two_people(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        # Names are not unique in reality; silently merging two callers would be
        # worse than a duplicate row.
        first = await client.post("/api/v1/customers", json={"name": "Anna Petrova"}, headers=auth_headers)
        second = await client.post("/api/v1/customers", json={"name": "Anna Petrova"}, headers=auth_headers)

        assert first.json()["id"] != second.json()["id"]
