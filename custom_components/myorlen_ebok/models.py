"""eBOK data and its parsing.

Pure functions over the JSON eBOK returns, so they can be tested without Home
Assistant. Parsing is lenient: a missing or changed field leaves a value empty
rather than failing the update.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
import re
from typing import Any

# --- conversions -----------------------------------------------------------------


def parse_datetime(value: Any) -> datetime | None:
    """ISO date as an aware datetime; eBOK omits the offset on some UTC fields."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_float(value: Any) -> float | None:
    """A number, also from a string with a decimal comma."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def _items(data: Any, key: str) -> Iterable[dict[str, Any]]:
    values = data.get(key) if isinstance(data, dict) else None
    return (v for v in values or [] if isinstance(v, dict))


def _str(value: Any) -> str:
    return "" if value is None else str(value)


# --- meters and readings ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Meter:
    """A gas collection point (PPG) with its meter."""

    number: str  # meter / PPG number, 20+ digits
    id_local: str  # short id eBOK uses to link invoices to the meter
    tariff: str | None
    agreement_number: str | None
    reading_value: float | None
    reading_date: datetime | None


def parse_meters(data: Any) -> list[Meter]:
    """/crm/get-ppg-list."""
    return [
        Meter(
            number=_str(raw.get("MeterNumber") or raw.get("IdPPG")),
            id_local=_str(raw.get("IdLocal")),
            tariff=raw.get("Tariff"),
            agreement_number=raw.get("ContractNumber"),
            reading_value=parse_float(raw.get("ReadingValue")),
            reading_date=parse_datetime(raw.get("ReadingDateUtc")),
        )
        for raw in _items(data, "PpgList")
        if raw.get("MeterNumber") or raw.get("IdPPG")
    ]


@dataclass(frozen=True, slots=True)
class Reading:
    """A meter reading, submitted by the customer or estimated by Orlen."""

    value: float
    date: datetime
    wear: float | None
    type: str  # "Receiver" (customer), estimates, ...
    status: str


def parse_readings(data: Any) -> list[Reading]:
    """/crm/get-all-ppg-readings-for-meter, newest first."""
    readings = []
    for raw in _items(data, "MeterReadings"):
        value, when = parse_float(raw.get("Value")), parse_datetime(raw.get("ReadingDateUtc"))
        if value is None or when is None:
            continue
        readings.append(
            Reading(
                value=value,
                date=when,
                wear=parse_float(raw.get("Wear")),
                type=_str(raw.get("Type")),
                status=_str(raw.get("Status")),
            )
        )
    return sorted(readings, key=lambda r: r.date, reverse=True)


# --- invoices --------------------------------------------------------------------


class PaymentState(StrEnum):
    """Where an invoice stands with its payment."""

    UNPAID = "unpaid"
    # Paid (e.g. online in eBOK) but not on the bank statement yet: eBOK keeps
    # IsPaid false and AmountToPay unchanged, with Status "Paid".
    AWAITING_BOOKING = "awaiting_booking"
    PAID = "paid"  # booked, Status "Posted"


@dataclass(frozen=True, slots=True)
class Invoice:
    """An invoice (or credit note) of one meter."""

    number: str
    meter_id_local: str
    issue_date: date | None
    due_date: date | None
    period_start: date | None
    period_end: date | None
    gross_amount: float | None
    to_pay: float
    wear_m3: float | None
    wear_kwh: float | None
    is_paid: bool
    status: str
    bank_account: str | None
    is_credit_note: bool

    @property
    def state(self) -> PaymentState:
        """Payment state; IsPaid only turns true once the payment is booked."""
        if self.is_paid:
            return PaymentState.PAID
        if self.status.strip().casefold() == "paid":
            return PaymentState.AWAITING_BOOKING
        return PaymentState.UNPAID

    @property
    def cost_per_m3(self) -> float | None:
        """Gross price per m³ of the whole invoice (fixed charges included)."""
        if not self.gross_amount or not self.wear_m3:
            return None
        return self.gross_amount / self.wear_m3


def _local_date(value: Any) -> date | None:
    """eBOK sends calendar dates as midnight with a UTC marker; keep the day."""
    parsed = parse_datetime(value)
    return parsed.date() if parsed else None


def parse_invoices(data: Any) -> list[Invoice]:
    """/crm/get-invoices-v2, newest first."""
    invoices = [
        Invoice(
            number=_str(raw.get("Number")),
            meter_id_local=_str(raw.get("IdPP")),
            issue_date=_local_date(raw.get("Date")),
            due_date=_local_date(raw.get("PayingDeadlineDate")),
            period_start=_local_date(raw.get("StartDate")),
            period_end=_local_date(raw.get("EndDate")),
            gross_amount=parse_float(raw.get("GrossAmount")),
            to_pay=parse_float(raw.get("AmountToPay")) or 0.0,
            wear_m3=parse_float(raw.get("WearM3")) or parse_float(raw.get("Wear")) or None,
            wear_kwh=parse_float(raw.get("WearKWH")),
            is_paid=bool(raw.get("IsPaid")),
            status=_str(raw.get("Status")),
            bank_account=raw.get("Iban") or None,
            is_credit_note=bool(raw.get("IsCreditNote")),
        )
        for raw in _items(data, "InvoicesList")
        if raw.get("Number")
    ]
    return sorted(invoices, key=lambda i: i.issue_date or date.min, reverse=True)


def parse_automatic_payment_date(data: Any) -> date | None:
    """/crm/get-invoice-details: when eBOK collects the payment itself."""
    invoice = data.get("Invoice") if isinstance(data, dict) else None
    return _local_date(invoice.get("AutomaticPaymentDate")) if isinstance(invoice, dict) else None


# --- account ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Agreement:
    """A gas agreement with its balance."""

    number: str
    meter_number: str
    active: bool
    balance: float | None
    tariff: str | None
    start_date: date | None
    end_date: date | None


def parse_agreements(data: Any) -> list[Agreement]:
    """/crm/get-agreements."""
    return [
        Agreement(
            number=_str(raw.get("AgreementNumber")),
            meter_number=_str(raw.get("PpNumber")),
            active=bool(raw.get("Active")),
            balance=parse_float(raw.get("Saldo")),
            tariff=raw.get("Tariff"),
            start_date=_local_date(raw.get("StartDate")),
            end_date=_local_date(raw.get("EndDate")),
        )
        for raw in _items(data, "Agreements")
    ]


@dataclass(frozen=True, slots=True)
class Payment:
    """A payment booked on the account."""

    date: date
    amount: float
    document: str


def parse_payments(data: Any) -> list[Payment]:
    """/crm/get-client-payments, newest first."""
    payments = []
    for raw in _items(data, "Payments"):
        when, amount = _local_date(raw.get("DocumentDate")), parse_float(raw.get("Value"))
        if when is None or amount is None:
            continue
        payments.append(Payment(date=when, amount=amount, document=_str(raw.get("DocumentNumber"))))
    return sorted(payments, key=lambda p: p.date, reverse=True)


_INVOICE_PAYMENT = re.compile(r"Numer faktury:\s*(?P<number>\S+?),")


def parse_invoice_payment_dates(data: Any) -> dict[str, datetime]:
    """/crm/get-account-history: when each invoice was paid in eBOK.

    The history says "Zapłata za fakturę" with the invoice number in free text;
    it is the only place that dates a payment before it is booked.
    """
    paid: dict[str, datetime] = {}
    for raw in _items(data, "HistoryList"):
        if "zapłata" not in _str(raw.get("Type")).casefold():
            continue
        match = _INVOICE_PAYMENT.search(_str(raw.get("Description")))
        when = parse_datetime(raw.get("Date"))
        if match and when:
            number = match["number"]
            paid[number] = max(when, paid.get(number, when))
    return paid


@dataclass(frozen=True, slots=True)
class Notice:
    """A notice on the eBOK dashboard (outage, phishing warning, ...)."""

    id: str
    title: str
    message: str
    date: datetime | None


_TAGS = re.compile(r"<[^>]+>")


def parse_notices(data: Any) -> list[Notice]:
    """/cms/get-alert-list, HTML stripped."""
    notices = []
    for raw in _items(data, "AlertList"):
        if raw.get("Id") is None:
            continue
        text = _TAGS.sub(" ", _str(raw.get("Content"))).replace("&nbsp;", " ")
        notices.append(
            Notice(
                id=_str(raw["Id"]),
                title=_str(raw.get("Title")),
                message=" ".join(text.split()),
                date=parse_datetime(raw.get("DateCreatedUtc")),
            )
        )
    return notices


# --- usage -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BillPart:
    """One line of a simulated bill."""

    description: str
    date_from: date | None
    date_to: date | None
    kwh: float | None
    net: float | None
    gross: float | None


@dataclass(frozen=True, slots=True)
class BillEstimate:
    """eBOK's bill calculator result for a meter reading."""

    reading: float
    net: float | None
    gross: float | None
    parts: tuple[BillPart, ...]


def parse_bill_estimate(data: Any, reading: float) -> BillEstimate | None:
    """/crm/simulate-wear."""
    if not isinstance(data, dict):
        return None
    parts = tuple(
        BillPart(
            description=_str(raw.get("Description")),
            date_from=_local_date(raw.get("DateFrom")),
            date_to=_local_date(raw.get("DateTo")),
            kwh=parse_float(raw.get("CountKwh")),
            net=parse_float(raw.get("Netto")),
            gross=parse_float(raw.get("Brutto")),
        )
        for raw in _items(data, "Parts")
    )
    gross = parse_float(data.get("BruttoTotal"))
    if gross is None and not parts:
        return None
    return BillEstimate(
        reading=reading, net=parse_float(data.get("NettoTotal")), gross=gross, parts=parts
    )


@dataclass(frozen=True, slots=True)
class MonthlyUsage:
    """Consumption of one month, closed by a meter reading."""

    reading_date: datetime
    reading: float
    usage: float


def parse_monthly_usage(data: Any) -> list[MonthlyUsage]:
    """/crm/get-monthly-wear-chart-data, oldest first."""
    chart = data.get("ChartData") if isinstance(data, dict) else None
    months = []
    for entries in chart.values() if isinstance(chart, dict) else ():
        for raw in entries if isinstance(entries, list) else ():
            if not isinstance(raw, dict):
                continue
            when = parse_datetime(raw.get("ReadingDateUtc"))
            reading, usage = parse_float(raw.get("Value")), parse_float(raw.get("Wear"))
            if when and reading is not None and usage is not None:
                months.append(MonthlyUsage(reading_date=when, reading=reading, usage=usage))
    return sorted(months, key=lambda m: m.reading_date)


# --- reading submission ----------------------------------------------------------

READING_ERRORS: dict[int, str] = {
    1: "Orlen odrzucił wartość jako nieprawidłową",
    1031: "Orlen odrzucił wartość jako nieprawidłową",
    1032: "Odczyt za ten okres został już podany",
    1040: (
        "Wartość jest niższa od poprzedniego odczytu; jeśli licznik wymieniono "
        "lub się przekręcił, powtórz z meter_reset: true"
    ),
    1072: "Orlen wymaga dodatkowego potwierdzenia odczytu na stronie eBOK",
}


@dataclass(frozen=True, slots=True)
class ReadingResult:
    """An accepted reading as echoed back by eBOK."""

    value: float | None
    added_at: datetime | None
    can_be_cancelled: bool


def parse_reading_result(data: Any) -> ReadingResult:
    """/crm/add-ppg-reading-v2 (Code 0)."""
    reading = data.get("Reading") if isinstance(data, dict) else None
    reading = reading if isinstance(reading, dict) else {}
    return ReadingResult(
        value=parse_float(reading.get("Value")),
        added_at=parse_datetime(reading.get("ReadingDateAddedUtc")),
        can_be_cancelled=bool(reading.get("CanBeCancelled")),
    )
