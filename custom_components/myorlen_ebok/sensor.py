"""Sensors of a gas meter: reading, payments, balance and costs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import Platform, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import RECENT_INVOICES, RECENT_PAYMENTS
from .coordinator import MyOrlenConfigEntry, MyOrlenCoordinator, MyOrlenData
from .entity import MyOrlenEntity
from .models import Invoice, Meter, PaymentState

PARALLEL_UPDATES = 0

PLN = "PLN"


def unpaid(data: MyOrlenData, meter: Meter) -> list[Invoice]:
    """Invoices still to pay, oldest due first; payments awaiting booking excluded."""
    return sorted(
        (i for i in data.meter_invoices(meter) if i.state is PaymentState.UNPAID and i.to_pay > 0),
        key=lambda i: i.due_date or date.max,
    )


def awaiting_booking(data: MyOrlenData, meter: Meter) -> list[Invoice]:
    return [i for i in data.meter_invoices(meter) if i.state is PaymentState.AWAITING_BOOKING]


def invoice_attributes(data: MyOrlenData, invoice: Invoice) -> dict[str, Any]:
    return {
        "number": invoice.number,
        "issue_date": invoice.issue_date,
        "due_date": invoice.due_date,
        "period_start": invoice.period_start,
        "period_end": invoice.period_end,
        "gross_amount": invoice.gross_amount,
        "to_pay": invoice.to_pay,
        "usage_m3": invoice.wear_m3,
        "usage_kwh": invoice.wear_kwh,
        "state": invoice.state.value,
        "status": invoice.status,
        "paid_at": data.invoice_paid_at.get(invoice.number),
        "automatic_payment_date": data.automatic_payment.get(invoice.number),
    }


def _to_pay_attrs(data: MyOrlenData, meter: Meter) -> dict[str, Any]:
    pending = awaiting_booking(data, meter)
    return {
        "invoices": [i.number for i in unpaid(data, meter)],
        "awaiting_booking": round(float(sum(i.to_pay for i in pending)), 2),
        "awaiting_booking_invoices": [i.number for i in pending],
    }


def _next_due(data: MyOrlenData, meter: Meter) -> Invoice | None:
    invoices = unpaid(data, meter)
    return invoices[0] if invoices else None


def _last_invoice(data: MyOrlenData, meter: Meter) -> Invoice | None:
    invoices = data.meter_invoices(meter)
    return invoices[0] if invoices else None


def _last_invoice_attrs(data: MyOrlenData, meter: Meter) -> dict[str, Any]:
    last = _last_invoice(data, meter)
    if last is None:
        return {}
    return {
        **invoice_attributes(data, last),
        "recent": [
            {
                "number": i.number,
                "due_date": i.due_date,
                "gross_amount": i.gross_amount,
                "state": i.state.value,
            }
            for i in data.meter_invoices(meter)[:RECENT_INVOICES]
        ],
    }


def _reading_attrs(data: MyOrlenData, meter: Meter) -> dict[str, Any]:
    reading = data.latest_reading(meter)
    if reading is None:
        return {"tariff": meter.tariff}
    return {
        "reading_date": reading.date,
        "usage": reading.wear,
        "reading_type": reading.type,
        "reading_status": reading.status,
        "tariff": meter.tariff,
    }


def _balance_attrs(data: MyOrlenData, meter: Meter) -> dict[str, Any]:
    agreement = data.agreement(meter)
    if agreement is None:
        return {}
    return {
        "agreement": agreement.number,
        "agreement_start": agreement.start_date,
        "agreement_end": agreement.end_date,
        "tariff": agreement.tariff,
    }


def _payment_attrs(data: MyOrlenData, meter: Meter) -> dict[str, Any]:
    if not data.payments:
        return {}
    return {
        "date": data.payments[0].date,
        "document": data.payments[0].document,
        "recent": [{"date": p.date, "amount": p.amount} for p in data.payments[:RECENT_PAYMENTS]],
    }


def _estimate_attrs(data: MyOrlenData, meter: Meter) -> dict[str, Any]:
    estimate = data.bill_estimates.get(meter.number)
    if estimate is None:
        return {}
    return {
        "net": estimate.net,
        "reading": estimate.reading,
        "parts": [
            {
                "description": p.description,
                "date_from": p.date_from,
                "date_to": p.date_to,
                "kwh": p.kwh,
                "net": p.net,
                "gross": p.gross,
            }
            for p in estimate.parts
        ],
    }


def _date_of(invoice: Invoice | None) -> date | None:
    return invoice.due_date if invoice else None


def _reading_date(data: MyOrlenData, meter: Meter) -> datetime | None:
    reading = data.latest_reading(meter)
    return reading.date if reading else None


@dataclass(frozen=True, kw_only=True)
class MyOrlenSensorDescription(SensorEntityDescription):
    """Value and attributes from the update data."""

    value_fn: Callable[[MyOrlenData, Meter], Any]
    attrs_fn: Callable[[MyOrlenData, Meter], dict[str, Any]] = lambda _d, _m: {}


SENSORS: tuple[MyOrlenSensorDescription, ...] = (
    MyOrlenSensorDescription(
        key="odczyt",
        translation_key="reading",
        device_class=SensorDeviceClass.GAS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        value_fn=lambda d, m: r.value if (r := d.latest_reading(m)) else m.reading_value,
        attrs_fn=_reading_attrs,
    ),
    MyOrlenSensorDescription(
        key="data_odczytu",
        translation_key="reading_date",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_reading_date,
    ),
    MyOrlenSensorDescription(
        key="do_zaplaty",
        translation_key="to_pay",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=PLN,
        suggested_display_precision=2,
        value_fn=lambda d, m: round(float(sum(i.to_pay for i in unpaid(d, m))), 2),
        attrs_fn=_to_pay_attrs,
    ),
    MyOrlenSensorDescription(
        key="termin_platnosci",
        translation_key="due_date",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda d, m: _date_of(_next_due(d, m)),
        attrs_fn=lambda d, m: invoice_attributes(d, i) if (i := _next_due(d, m)) else {},
    ),
    MyOrlenSensorDescription(
        key="ostatnia_faktura",
        translation_key="last_invoice",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=PLN,
        suggested_display_precision=2,
        value_fn=lambda d, m: i.gross_amount if (i := _last_invoice(d, m)) else None,
        attrs_fn=_last_invoice_attrs,
    ),
    MyOrlenSensorDescription(
        key="cena_m3",
        translation_key="cost_per_m3",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=f"{PLN}/{UnitOfVolume.CUBIC_METERS}",
        suggested_display_precision=2,
        value_fn=lambda d, m: next(
            (i.cost_per_m3 for i in d.meter_invoices(m) if i.cost_per_m3), None
        ),
    ),
    MyOrlenSensorDescription(
        key="saldo",
        translation_key="balance",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=PLN,
        suggested_display_precision=2,
        value_fn=lambda d, m: a.balance if (a := d.agreement(m)) else None,
        attrs_fn=_balance_attrs,
    ),
    MyOrlenSensorDescription(
        key="ostatnia_wplata",
        translation_key="last_payment",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=PLN,
        suggested_display_precision=2,
        value_fn=lambda d, m: d.payments[0].amount if d.payments else None,
        attrs_fn=_payment_attrs,
    ),
    MyOrlenSensorDescription(
        key="szacowany_rachunek",
        translation_key="bill_estimate",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=PLN,
        suggested_display_precision=2,
        value_fn=lambda d, m: e.gross if (e := d.bill_estimates.get(m.number)) else None,
        attrs_fn=_estimate_attrs,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MyOrlenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        MyOrlenSensor(coordinator, meter, description)
        for meter in coordinator.data.meters
        for description in SENSORS
    )


class MyOrlenSensor(MyOrlenEntity, SensorEntity):
    """A sensor computed from the update data."""

    entity_description: MyOrlenSensorDescription

    def __init__(
        self,
        coordinator: MyOrlenCoordinator,
        meter: Meter,
        description: MyOrlenSensorDescription,
    ) -> None:
        super().__init__(coordinator, meter, description.key, Platform.SENSOR)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data, self.meter)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.entity_description.attrs_fn(self.coordinator.data, self.meter)
