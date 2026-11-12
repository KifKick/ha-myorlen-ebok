// Device-based discovery: a card is configured with (at most) a device_id - one
// gas meter - and finds that meter's entities through the frontend registries.

import { DOMAIN } from "./const";
import type { DeviceRegistryEntry, HomeAssistant } from "./ha-types";

export const isMeterDevice = (device: DeviceRegistryEntry): boolean =>
  (device.identifiers ?? []).some(([domain]) => domain === DOMAIN);

export const getMeterDevices = (hass: HomeAssistant): DeviceRegistryEntry[] =>
  Object.values(hass.devices ?? {})
    .filter(isMeterDevice)
    .sort((a, b) => deviceName(a).localeCompare(deviceName(b)));

/** The configured meter, or the first one when none is set. */
export const resolveDevice = (hass: HomeAssistant, deviceId?: string): DeviceRegistryEntry | undefined =>
  deviceId ? hass.devices?.[deviceId] : getMeterDevices(hass)[0];

export const deviceName = (device: DeviceRegistryEntry): string => device.name_by_user || device.name || "myORLEN";

/** `<platform>.<translation_key>` -> entity_id for every entity on the device. */
export type EntityMap = Record<string, string>;

// hass.entities is replaced (not mutated) on registry changes, so it is a
// reliable cache key; set hass() runs on every state change in the system.
const cache = new WeakMap<object, Map<string, EntityMap>>();

export const resolveEntities = (hass: HomeAssistant, deviceId: string): EntityMap => {
  // The frontend loads the registries after the states; until then, nothing.
  if (!hass.entities) return {};
  let perDevice = cache.get(hass.entities);
  if (!perDevice) {
    perDevice = new Map();
    cache.set(hass.entities, perDevice);
  }
  let map = perDevice.get(deviceId);
  if (!map) {
    map = {};
    for (const entry of Object.values(hass.entities)) {
      if (entry.device_id !== deviceId || entry.platform !== DOMAIN || !entry.translation_key) continue;
      map[`${entry.entity_id.split(".", 1)[0]}.${entry.translation_key}`] = entry.entity_id;
    }
    perDevice.set(deviceId, map);
  }
  return map;
};
