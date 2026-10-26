"""Demo content for a fictional multi-business operator.

One company, three things to book: a restaurant (tables), a wellness clinic
(treatment rooms) and a workshop space let by the hour (meeting rooms). That is
what makes `resource_type` the parameter the agent services differ by rather
than decoration — the voice agent books tables, the sales agent sells
treatments, and both read this same database.

Kept apart from the seeding logic so the prose can be edited without touching
any code that talks to the database.
"""

from datetime import date, time
from decimal import Decimal

from src.app.contracts.enums import CustomerStatus, ResourceType

CUSTOMERS: tuple[tuple[str, CustomerStatus, int | None, str | None], ...] = (
    # (name, status, days since last contact, notes)
    ("Anna Petrova", CustomerStatus.ACTIVE, 3, "Prefers evening slots. Allergic to lavender oil."),
    ("Marcus Feld", CustomerStatus.ACTIVE, 11, "Corporate account, invoices go to Feld Consulting."),
    ("Priya Raman", CustomerStatus.LEAD, 1, "Enquired about the nutrition package after a webinar."),
    ("Tom Okafor", CustomerStatus.LEAD, 6, "Wants a quote for six deep tissue sessions."),
    ("Lena Ortiz", CustomerStatus.ACTIVE, 21, "Books the meeting room monthly for team workshops."),
    ("Bea Lindqvist", CustomerStatus.CHURNED, 240, "Moved abroad in the spring; keep on the newsletter."),
)

SERVICES: tuple[tuple[str, Decimal, str], ...] = (
    ("Deep Tissue Massage", Decimal("120.00"), "Sixty minutes of firm-pressure work with a licensed therapist."),
    ("Nutrition Coaching", Decimal("95.00"), "One-to-one session including a personalised meal plan review."),
    ("Physiotherapy Assessment", Decimal("140.00"), "Full movement assessment and a written rehabilitation plan."),
    ("Sports Recovery Session", Decimal("110.00"), "Post-training recovery combining stretching and compression."),
    ("Meeting Room Hire", Decimal("60.00"), "Per hour hire of the workshop room, seats ten, screen included."),
)

# The restaurant floor: (table number, seats). Several tables of each size, so a
# busy evening can still seat a second party of four at seven.
TABLES: tuple[tuple[int, int], ...] = (
    (1, 2), (2, 2), (3, 2), (4, 2),
    (5, 4), (6, 4), (7, 4), (8, 4),
    (9, 6), (10, 6),
    (11, 8),
)  # fmt: skip

# A seating lasts two hours, so no table is offered twice inside two hours: odd
# tables turn at 12, 14, 18 and 20, even ones at 13, 19 and 21. Every lunch and
# dinner hour has tables of most sizes, and they fill up independently.
_ODD_SEATINGS = (12, 14, 18, 20)
_EVEN_SEATINGS = (13, 19, 21)

# (resource type, unit, hour, minute, capacity), repeated for every day of the
# slot window (SLOT_WINDOW_DAYS in the settings) except where `slot_template_for`
# drops it: the clinic's treatment rooms keep the clinic's opening hours.
SLOT_TEMPLATE: tuple[tuple[ResourceType, int, int, int, int], ...] = (
    *(
        (ResourceType.TABLE, number, hour, 0, seats)
        for number, seats in TABLES
        for hour in (_ODD_SEATINGS if number % 2 else _EVEN_SEATINGS)
    ),
    (ResourceType.MEETING_ROOM, 1, 9, 0, 10),
    (ResourceType.MEETING_ROOM, 1, 11, 0, 10),
    (ResourceType.MEETING_ROOM, 1, 14, 0, 6),
    (ResourceType.MEETING_ROOM, 1, 16, 30, 6),
    # Capacity 1: a treatment room takes one client at a time, which is also
    # what stops a party of four being offered a massage slot.
    (ResourceType.TREATMENT_ROOM, 1, 10, 0, 1),
    (ResourceType.TREATMENT_ROOM, 1, 12, 30, 1),
    (ResourceType.TREATMENT_ROOM, 1, 15, 0, 1),
    (ResourceType.TREATMENT_ROOM, 1, 17, 30, 1),
)

# The clinic's opening hours as the "Opening hours, location and parking" document below
# states them: Monday to Friday 8-20, Saturday 9-18, closed on Sunday. The last appointment
# starts one hour before closing. Weekday numbers follow `date.weekday()`.
_CLINIC_HOURS = {weekday: (time(8), time(20)) for weekday in range(5)} | {5: (time(9), time(18))}


def _clinic_takes_appointment_at(day: date, start: time) -> bool:
    hours = _CLINIC_HOURS.get(day.weekday())
    if hours is None:
        return False
    opening, closing = hours
    return opening <= start <= time(closing.hour - 1, closing.minute)


def slot_template_for(day: date) -> tuple[tuple[ResourceType, int, int, int, int], ...]:
    """The slots offered on one calendar day.

    Tables and the meeting room follow SLOT_TEMPLATE every day. Treatment rooms only
    where the clinic could take the appointment: none on Sunday, and on Saturday nothing
    that starts later than an hour before the 18:00 closing.
    """
    return tuple(
        entry
        for entry in SLOT_TEMPLATE
        if entry[0] is not ResourceType.TREATMENT_ROOM or _clinic_takes_appointment_at(day, time(entry[2], entry[3]))
    )

DOCUMENTS: tuple[tuple[str, str], ...] = (
    (
        "Cancellation and rescheduling policy",
        "Appointments can be cancelled or rescheduled free of charge up to twenty-four hours before "
        "the scheduled start time. You can do this from the confirmation email, through the client "
        "portal, or by calling the front desk during opening hours.\n\n"
        "Cancellations made inside the twenty-four hour window are charged at fifty percent of the "
        "treatment price, because the therapist's time can no longer be offered to another client. "
        "Clients who do not attend and do not give notice are charged the full treatment price.\n\n"
        "We waive the late cancellation fee for illness, bereavement and travel disruption. Let the "
        "front desk know what happened and the charge is removed from your account, usually on the "
        "same working day. Repeated no-shows may require prepayment for future bookings.",
    ),
    (
        "Treatments and therapies",
        "Our deep tissue massage uses slow, firm pressure to release chronic muscle tension and "
        "scar tissue. Sessions run for sixty or ninety minutes with a licensed therapist, who will "
        "check your pressure preference before starting and adjust it at any point you ask.\n\n"
        "Physiotherapy begins with a full movement assessment. The therapist watches how you walk, "
        "bend and load each joint, then writes a rehabilitation plan with exercises you can do at "
        "home. Most plans are reviewed after three visits and adjusted as your range improves.\n\n"
        "Sports recovery sessions combine assisted stretching with compression therapy and are "
        "designed for the day after hard training. Nutrition coaching packages are sold in blocks "
        "of six sessions and include a personalised meal plan that is reviewed every month.",
    ),
    (
        "Opening hours, location and parking",
        "The clinic is open Monday to Friday from eight in the morning until eight in the evening, "
        "and on Saturday from nine until six. We are closed on Sundays and on public holidays. The "
        "last appointment of each day starts one hour before closing time.\n\n"
        "We are on the second floor of the Riverside Health Building, a four minute walk from the "
        "central tram stop. There is a lift from the ground floor lobby and step-free access from "
        "the street entrance on Mill Lane.\n\n"
        "Parking is available in the underground garage beneath the building. Clients with an "
        "appointment get two hours validated free of charge; bring your ticket to the front desk "
        "before your session and we will stamp it while you are being treated.",
    ),
    (
        "Payment, insurance and packages",
        "We accept all major credit and debit cards, bank transfer, and direct billing to corporate "
        "health insurance. Payment is taken at the end of each session unless your employer has a "
        "billing agreement with us, in which case the invoice goes to them monthly.\n\n"
        "Treatment packages are cheaper per session than booking individually, and orders of more "
        "than five sessions of the same service receive an automatic volume discount at checkout. "
        "Packages are valid for twelve months from the date of purchase.\n\n"
        "If you claim through insurance, ask the front desk for an itemised receipt after your "
        "visit. Most insurers reimburse physiotherapy and sports recovery, but very few cover "
        "nutrition coaching, so check your policy before booking a block.",
    ),
    (
        "Your first visit and how to prepare",
        "New clients receive a complimentary fifteen minute consultation before their first "
        "treatment. It is used to talk through your health goals, any injuries or medication, and "
        "which therapist is the best fit for what you want to work on.\n\n"
        "Please arrive ten minutes early for a first appointment so there is time to complete the "
        "health questionnaire without eating into your session. Wear or bring loose clothing you "
        "can move in; for physiotherapy, shorts and a t-shirt work best.\n\n"
        "Avoid a heavy meal in the hour before a massage and drink water afterwards. If you are "
        "pregnant, recovering from surgery, or being treated for a heart condition, tell us when "
        "you book so we can assign a therapist with the right qualification.",
    ),
)
