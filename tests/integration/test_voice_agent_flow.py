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

    async def test_registering_needs_the_api_key(self, anonymous_client: AsyncClient) -> None:
        assert (await anonymous_client.post("/api/v1/customers", json={"name": "Anonymous"})).status_code == 401

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


class TestCancellation:
    """Finding a booking by name and cancelling it — the other half of the call."""

    async def test_a_caller_can_find_and_cancel_their_table(
        self,
        client: AsyncClient,
        slots: FakeBookingRepository,
        auth_headers: dict[str, str],
    ) -> None:
        slot_id = str(next(iter(slots.slots)))
        await client.post(
            "/api/v1/bookings",
            json={"guest_name": "Dmitri Volkov", "slot_id": slot_id, "party_size": 2},
            headers=auth_headers,
        )

        # "I'd like to cancel my table" — the agent has a name, not a UUID.
        found = await client.get("/api/v1/bookings", params={"guest_name": "volkov"}, headers=auth_headers)
        booking_id = found.json()["items"][0]["id"]
        cancelled = await client.delete(f"/api/v1/bookings/{booking_id}", headers=auth_headers)

        assert found.json()["total"] == 1
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"

    async def test_the_slot_is_offered_again_after_cancelling(
        self,
        client: AsyncClient,
        slots: FakeBookingRepository,
        auth_headers: dict[str, str],
    ) -> None:
        slot_id = str(next(iter(slots.slots)))
        created = await client.post(
            "/api/v1/bookings",
            json={"guest_name": "Dmitri Volkov", "slot_id": slot_id, "party_size": 2},
            headers=auth_headers,
        )
        gone = await client.get("/api/v1/booking-slots")

        await client.delete(f"/api/v1/bookings/{created.json()['id']}", headers=auth_headers)
        back = await client.get("/api/v1/booking-slots")

        assert slot_id not in [item["id"] for item in gone.json()["items"]]
        assert slot_id in [item["id"] for item in back.json()["items"]]

    async def test_cancelling_twice_is_harmless(
        self,
        client: AsyncClient,
        slots: FakeBookingRepository,
        auth_headers: dict[str, str],
    ) -> None:
        created = await client.post(
            "/api/v1/bookings",
            json={"guest_name": "Dmitri Volkov", "slot_id": str(next(iter(slots.slots))), "party_size": 2},
            headers=auth_headers,
        )
        booking_id = created.json()["id"]

        first = await client.delete(f"/api/v1/bookings/{booking_id}", headers=auth_headers)
        second = await client.delete(f"/api/v1/bookings/{booking_id}", headers=auth_headers)

        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()

    async def test_cancelling_an_unknown_booking_is_a_404(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        response = await client.delete(f"/api/v1/bookings/{uuid4()}", headers=auth_headers)

        assert response.status_code == 404
        assert response.json()["error_code"] == "entity_not_found"

    async def test_cancelling_needs_the_api_key(
        self,
        client: AsyncClient,
        anonymous_client: AsyncClient,
        slots: FakeBookingRepository,
        auth_headers: dict[str, str],
    ) -> None:
        created = await client.post(
            "/api/v1/bookings",
            json={"guest_name": "Dmitri Volkov", "slot_id": str(next(iter(slots.slots))), "party_size": 2},
            headers=auth_headers,
        )

        assert (await anonymous_client.delete(f"/api/v1/bookings/{created.json()['id']}")).status_code == 401

    async def test_rebooking_after_cancelling_needs_a_fresh_key(
        self,
        client: AsyncClient,
        slots: FakeBookingRepository,
        auth_headers: dict[str, str],
    ) -> None:
        # "Actually, book it again" in the same call. Replaying the key would
        # answer 201 with the cancelled booking and no table reserved.
        body = {"guest_name": "Dmitri Volkov", "slot_id": str(next(iter(slots.slots))), "party_size": 2}
        used = {**auth_headers, "Idempotency-Key": "call-7"}

        created = await client.post("/api/v1/bookings", json=body, headers=used)
        await client.delete(f"/api/v1/bookings/{created.json()['id']}", headers=auth_headers)

        replayed = await client.post("/api/v1/bookings", json=body, headers=used)
        rebooked = await client.post(
            "/api/v1/bookings",
            json=body,
            headers={**auth_headers, "Idempotency-Key": "call-7-attempt-2"},
        )

        assert replayed.status_code == 409
        assert replayed.json()["error_code"] == "idempotency_key_consumed"
        assert rebooked.status_code == 201
        assert rebooked.json()["id"] != created.json()["id"]
