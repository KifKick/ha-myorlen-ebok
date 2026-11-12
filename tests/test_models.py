"""Parsing of eBOK responses."""

from __future__ import annotations

from datetime import UTC, date, datetime

from custom_components.myorlen_ebok import models
from custom_components.myorlen_ebok.models import PaymentState

from .conftest import ID_LOCAL, METER, load


def test_meters() -> None:
    (meter,) = models.parse_meters(load("ppg_list"))
    assert (meter.number, meter.id_local, meter.tariff) == (METER, ID_LOCAL, "W-1.12T")
    assert meter.reading_value == 56.0


def test_readings_newest_first() -> None:
    readings = models.parse_readings(load("readings"))
    assert readings[0].value == 56.0
    assert readings[0].date == datetime(2026, 10, 31, tzinfo=UTC)
    assert readings == sorted(readings, key=lambda r: r.date, reverse=True)


def test_invoice_states() -> None:
    invoices = models.parse_invoices(load("invoices"))
    current, previous = invoices[0], invoices[1]
    # Paid online on 10.11, not booked yet: IsPaid false, Status "Paid".
    assert current.number == "P/12345678/0010/26"
    assert current.state is PaymentState.AWAITING_BOOKING
    assert current.to_pay == 27.4
    assert current.due_date == date(2026, 11, 16)
    assert current.wear_m3 == 3.0
    assert previous.state is PaymentState.PAID
    assert models.Invoice(**{**_fields(current), "status": ""}).state is PaymentState.UNPAID


def _fields(invoice: models.Invoice) -> dict:
    return {f: getattr(invoice, f) for f in invoice.__dataclass_fields__}


def test_cost_per_m3() -> None:
    invoice = models.parse_invoices(load("invoices"))[0]
    assert round(invoice.cost_per_m3, 2) == 9.13


def test_account_data() -> None:
    (agreement,) = models.parse_agreements(load("agreements"))
    assert (agreement.meter_number, agreement.balance, agreement.active) == (METER, 0.0, True)
    payments = models.parse_payments(load("payments"))
    assert payments[0].amount == 27.4
    assert payments == sorted(payments, key=lambda p: p.date, reverse=True)
    paid_at = models.parse_invoice_payment_dates(load("account_history"))
    assert paid_at["P/12345678/0010/26"] == datetime(2026, 11, 10, 11, 9, 7, 223000, tzinfo=UTC)
    assert models.parse_automatic_payment_date(load("invoice_details")) == date(2026, 11, 15)


def test_notices_strip_html() -> None:
    (notice,) = models.parse_notices(load("alerts"))
    assert notice.title == "Phishing"
    assert notice.message.startswith("Uwaga na fałszywe wiadomości e-mail!")
    assert "<" not in notice.message


def test_bill_estimate() -> None:
    estimate = models.parse_bill_estimate(load("simulate_wear"), 57.0)
    assert (estimate.gross, estimate.net) == (19.73, 16.04)
    assert [p.description for p in estimate.parts][:2] == ["Dystrybucyjna zmienna", "Paliwo gazowe"]
    assert models.parse_bill_estimate({}, 1.0) is None


def test_monthly_usage_oldest_first() -> None:
    months = models.parse_monthly_usage(load("monthly_wear"))
    assert [(m.reading, m.usage) for m in months] == [
        (51.0, 2.0),
        (50.0, 1.0),
        (53.0, 3.0),
        (56.0, 3.0),
    ]


def test_lenient_parsing() -> None:
    assert models.parse_invoices(None) == []
    assert models.parse_invoices({"InvoicesList": [None, {"Number": None}]}) == []
    assert models.parse_float("27,40") == 27.4
    assert models.parse_float(True) is None
    assert models.parse_datetime("nope") is None


def test_reading_result() -> None:
    result = models.parse_reading_result(
        {"Code": 0, "Reading": {"Value": 57.0, "CanBeCancelled": True}}
    )
    assert (result.value, result.can_be_cancelled) == (57.0, True)
