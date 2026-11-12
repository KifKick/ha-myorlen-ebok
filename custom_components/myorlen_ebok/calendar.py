"""Calendar of invoice due dates, with the payment state in the title."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import MyOrlenConfigEntry, MyOrlenCoordinator, MyOrlenData
from .entity import MyOrlenEntity
from .models import Invoice, Meter, PaymentState

PARALLEL_UPDATES = 0


def pln(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}".replace(".", ",") + " zł"


def invoice_event(data: MyOrlenData, invoice: Invoice) -> CalendarEvent | None:
    """All-day event on the due date. Only unpaid invoices say "do zapłaty",
    so a reminder filtering on it skips paid ones.
    """
    if invoice.due_date is None:
        return None
    state = invoice.state
    if state is PaymentState.PAID:
        summary = f"Orlen gaz: faktura {pln(invoice.gross_amount)} opłacona"
    elif state is PaymentState.AWAITING_BOOKING:
        summary = f"Orlen gaz: {pln(invoice.to_pay)} zapłacone, czeka na zaksięgowanie"
    else:
        summary = f"Orlen gaz: {pln(invoice.to_pay)} do zapłaty"

    lines = [
        f"Faktura: {invoice.number}",
        f"Kwota faktury: {pln(invoice.gross_amount)}",
        f"Do zapłaty: {pln(invoice.to_pay)}",
    ]
    if invoice.period_start and invoice.period_end:
        lines.append(f"Okres: {invoice.period_start:%d.%m.%Y} - {invoice.period_end:%d.%m.%Y}")
    if invoice.wear_m3:
        lines.append(f"Zużycie: {invoice.wear_m3:g} m³ ({invoice.wear_kwh or 0:g} kWh)")
    if paid_at := data.invoice_paid_at.get(invoice.number):
        lines.append(f"Zapłacono w eBOK: {dt_util.as_local(paid_at):%d.%m.%Y %H:%M}")
    if state is not PaymentState.PAID and (auto := data.automatic_payment.get(invoice.number)):
        lines.append(f"Płatność automatyczna: {auto:%d.%m.%Y}")
    if invoice.bank_account and state is PaymentState.UNPAID:
        lines.append(f"Rachunek: {invoice.bank_account}")
    lines.append(f"Status eBOK: {invoice.status or '-'}")

    return CalendarEvent(
        start=invoice.due_date,
        end=invoice.due_date + timedelta(days=1),
        summary=summary,
        description="\n".join(lines),
        uid=f"myorlen_{invoice.number}",
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MyOrlenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(MyOrlenCalendar(coordinator, meter) for meter in coordinator.data.meters)


class MyOrlenCalendar(MyOrlenEntity, CalendarEntity):
    """The meter's invoices on their due dates: unpaid, awaiting booking, paid."""

    _attr_translation_key = "invoices"

    def __init__(self, coordinator: MyOrlenCoordinator, meter: Meter) -> None:
        super().__init__(coordinator, meter, "faktury", Platform.CALENDAR)

    def _events(self) -> list[CalendarEvent]:
        data = self.coordinator.data
        events = (invoice_event(data, i) for i in data.meter_invoices(self.meter))
        return sorted((e for e in events if e), key=lambda e: e.start)

    @property
    def event(self) -> CalendarEvent | None:
        today = self.coordinator.today
        return next((e for e in self._events() if e.end > today), None)

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return [
            e
            for e in self._events()
            if dt_util.start_of_local_day(e.start) < end_date
            and dt_util.start_of_local_day(e.end) > start_date
        ]
