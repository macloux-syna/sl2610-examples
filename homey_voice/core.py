"""Homey transport, constrained English intents, and capability validation."""
from __future__ import annotations

import json
import math
import re
import socket
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class ControlError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HomeyClient:
    def __init__(self, address, token, timeout=8):
        url = urlsplit(address)
        if (url.scheme not in ('http', 'https') or not url.hostname
                or url.username or url.password or url.query or url.fragment
                or url.path not in ('', '/')):
            raise ControlError('Homey address must be an http(s) origin, including its port.')
        if not token or any(c.isspace() for c in token):
            raise ControlError('Set HOMEY_TOKEN to your Homey API key.')
        self.address, self.token, self.timeout = address.rstrip('/'), token, timeout
        self.opener = build_opener(NoRedirect())

    def request(self, method, path, body=None):
        data = None if body is None else json.dumps(body, allow_nan=False).encode()
        req = Request(self.address + path, data=data, method=method,
                      headers={'Authorization': 'Bearer ' + self.token,
                               'Content-Type': 'application/json', 'Accept': 'application/json'})
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except HTTPError as e:
            message = {401: 'API key rejected. Check HOMEY_TOKEN.',
                       403: 'API key lacks the required device/zone permissions.',
                       404: 'Device or endpoint not found. Refresh the device list.'}.get(e.code)
            raise ControlError(message or f'Homey returned HTTP {e.code}.') from None
        except (URLError, TimeoutError, socket.timeout, OSError):
            suffix = ' A write may have reached Homey; check its state before retrying.' if method == 'PUT' else ''
            raise ControlError('Cannot reach Homey at the configured address.' + suffix) from None
        except (ValueError, UnicodeError):
            raise ControlError('Homey returned an invalid JSON response; check the address.') from None

    def catalog(self):
        devices = self.request('GET', '/api/manager/devices/device')
        zones = self.request('GET', '/api/manager/zones/zone')
        if not isinstance(devices, dict) or not isinstance(zones, dict):
            raise ControlError('Unexpected Homey device/zone response.')
        return devices, zones

    def set_value(self, device_id, capability, value):
        path = '/api/manager/devices/device/' + quote(device_id, safe='')
        path += '/capability/' + quote(capability, safe='')
        self.request('PUT', path, {'value': value})


def normalize(text):
    return ' '.join(re.sub(r'[^\w.%+-]+', ' ', text.casefold()).split())


def target_text(text):
    text = normalize(text)
    return re.sub(r'^(?:the|my)\s+', '', text)


def spoken_number(text):
    """Common English ASR number forms; no eval or general expression parsing."""
    words = dict(zip(('zero one two three four five six seven eight nine ten eleven '
                      'twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen').split(), range(20)))
    words.update(dict(zip('twenty thirty forty fifty sixty seventy eighty ninety'.split(), range(20, 100, 10))))
    def integer(part):
        tokens = part.replace('-', ' ').split()
        if len(tokens) == 1 and tokens[0] in words:
            return words[tokens[0]]
        if tokens in (['one', 'hundred'], ['a', 'hundred']):
            return 100
        if (len(tokens) == 2 and words.get(tokens[0], 0) >= 20
                and 0 < words.get(tokens[1], 100) < 10):
            return words[tokens[0]] + words[tokens[1]]
        raise ValueError
    try:
        return float(text)
    except ValueError:
        sign = -1 if text.startswith(('minus ', 'negative ')) else 1
        text = re.sub(r'^(?:minus|negative) ', '', text)
        parts = text.split(' point ')
        value = integer(parts[0])
        if len(parts) == 2:
            digits = parts[1].split()
            if not digits or any(words.get(w, 100) > 9 for w in digits):
                raise ValueError
            value += float('0.' + ''.join(str(words[w]) for w in digits))
        elif len(parts) > 2:
            raise ValueError
        return sign * value


@dataclass(frozen=True)
class Intent:
    target: str
    capability: str | None = None
    value: bool | float | None = None


def parse(text):
    text = normalize(text.strip().rstrip('.!?'))
    text = re.sub(r'^please\s+|\s+please$', '', text)
    if re.fullmatch(
            r'(?:play|resume|pause)(?: music)?|'
            r'(?:turn )?(?:the )?volume[ -]?(?:up|down)|'
            r'turn (?:up|down) (?:the )?volume|'
            r'(?:increase|raise|decrease|lower) (?:the )?volume', text):
        raise ControlError('Include the speaker name, for example “play Living room speaker” '
                           'or “volume up on Living room speaker”.')
    m = re.fullmatch(r'(play|resume|pause)(?: music)?(?: on)? (.+)', text)
    if m:
        return Intent(target_text(m[2]), 'speaker_playing', m[1] != 'pause')
    m = re.fullmatch(r'(?:turn )?(?:the )?volume[ -]?(up|down)(?: (?:on|for))? (.+)', text)
    if not m:
        m = re.fullmatch(r'turn (up|down) (?:the )?volume (?:on |for )?(.+)', text)
    if m:
        return Intent(target_text(m[2]), 'volume_' + m[1], True)
    m = re.fullmatch(r'(?:turn )?(.+?)(?: s)? volume (up|down)', text)
    if m:
        return Intent(target_text(m[1]), 'volume_' + m[2], True)
    m = re.fullmatch(r'(increase|raise|decrease|lower) (?:the )?volume (?:on |for )?(.+)', text)
    if m:
        direction = 'up' if m[1] in ('increase', 'raise') else 'down'
        return Intent(target_text(m[2]), 'volume_' + direction, True)
    m = re.fullmatch(r'(?:turn|switch) (on|off) (.+)', text)
    if m:
        return Intent(target_text(m[2]), 'onoff', m[1] == 'on')
    m = re.fullmatch(r'(?:turn|switch) (.+) (on|off)', text)
    if m:
        return Intent(target_text(m[1]), 'onoff', m[2] == 'on')
    m = re.fullmatch(r'(?:set|dim) (.+?) (?:to|at) (.+?)\s*(%|percent|degrees(?: celsius)?|celsius)', text)
    if not m:
        m = re.fullmatch(r'(?:set|dim) (.+?) ([+-]?\d+(?:\.\d+)?)\s*(%|percent|degrees(?: celsius)?|celsius)', text)
    if m:
        try:
            number = spoken_number(m[2])
        except ValueError:
            raise ControlError('Use a number such as 50 percent or twenty one degrees.') from None
        cap = 'dim' if m[3] in ('%', 'percent') else 'target_temperature'
        if cap == 'dim':
            if not 0 <= number <= 100:
                raise ControlError('Brightness must be between 0 and 100 percent.')
            number /= 100
        return Intent(target_text(m[1]), cap, number)
    m = re.fullmatch(r'(?:status (?:of )?|what is the status of |what s the status of |check )(.+)', text)
    if m:
        return Intent(target_text(m[1]))
    raise ControlError('Try “turn on Desk lamp”, “set Desk lamp to 50 percent”, '
                       '“play Living room speaker”, “pause Living room speaker”, '
                       'or “volume up on Living room speaker”.')


def resolve(target, devices, zones, aliases=None):
    target = target_text(target)
    aliases = aliases or {}
    matches = [key for key in aliases if target_text(key) == target]
    if matches:
        ids = aliases[matches[0]]
        ids = [ids] if isinstance(ids, str) else ids
        if not isinstance(ids, list) or not ids or any(i not in devices for i in ids):
            raise ControlError('This alias references missing devices. Check aliases.json.')
        return [devices[i] for i in dict.fromkeys(ids)]
    exact = [d for d in devices.values() if target_text(d['name']) == target]
    if not exact:
        exact = [d for d in devices.values()
                 if target_text(zones.get(d.get('zone'), {}).get('name', '') + ' ' + d['name']) == target]
    if len(exact) == 1:
        return exact
    if len(exact) > 1:
        raise ControlError('That name is ambiguous. Say the room and device name or create an alias.')
    group = re.fullmatch(r'all (?:the )?lights(?: in (?:the )?(.+))?', target)
    if group:
        zone_ids = None
        if group[1]:
            zone_ids = [i for i, z in zones.items() if target_text(z['name']) == target_text(group[1])]
            if len(zone_ids) != 1:
                raise ControlError('Room not found or ambiguous. Use a unique room name.')
        result = [d for d in devices.values() if (d.get('virtualClass') or d.get('class')) == 'light'
                  and (zone_ids is None or d.get('zone') in zone_ids)]
        if result:
            return result
    raise ControlError('Device not found. Use its exact name, room + name, or an alias.')


def validate(device, capability, value):
    if device.get('available') is False:
        raise ControlError(device['name'] + ' is unavailable.')
    klass = device.get('virtualClass') or device.get('class')
    permitted = {'onoff': {'light', 'socket'}, 'dim': {'light'},
                 'target_temperature': {'thermostat'}, 'speaker_playing': {'speaker'},
                 'volume_up': {'speaker'}, 'volume_down': {'speaker'}, 'volume_set': {'speaker'}}
    if klass not in permitted.get(capability, set()):
        raise ControlError('That command is not supported for this device class. '
                           'Supported devices are lights, sockets, thermostats, and speakers.')
    metadata = device.get('capabilitiesObj', {}).get(capability)
    if capability not in device.get('capabilities', []) or not isinstance(metadata, dict):
        raise ControlError(device['name'] + ' does not expose ' + capability + '.')
    if metadata.get('setable') is False:
        raise ControlError('That capability is read-only.')
    if capability in ('onoff', 'speaker_playing', 'volume_up', 'volume_down'):
        if type(value) is not bool:
            raise ControlError('Expected a boolean command value.')
        if capability in ('volume_up', 'volume_down') and value is not True:
            raise ControlError('Volume buttons must be pressed with true.')
        return
    if type(value) not in (float, int) or not math.isfinite(value):
        raise ControlError('Expected a finite number.')
    low, high = (0, 1) if capability in ('dim', 'volume_set') else (5, 35)
    low, high = metadata.get('min', low), metadata.get('max', high)
    if not low <= value <= high:
        raise ControlError(f'{device["name"]} accepts {low} to {high}.')
    if capability == 'target_temperature' and metadata.get('units', '°C') not in ('°C', 'C', 'celsius'):
        raise ControlError('This version expects a Celsius thermostat.')
    step = metadata.get('step')
    if step and not math.isclose((value - low) / step, round((value - low) / step), abs_tol=1e-6):
        raise ControlError(f'Use increments of {step} for {device["name"]}.')


def plan_action(device, intent):
    """Resolve relative volume using the capabilities this device exposes."""
    capability, value = intent.capability, intent.value
    if capability in ('volume_up', 'volume_down'):
        metadata = device.get('capabilitiesObj', {})
        native = metadata.get(capability)
        if (capability not in device.get('capabilities', [])
                or not isinstance(native, dict) or native.get('setable') is False):
            slider = metadata.get('volume_set', {})
            current = slider.get('value')
            if type(current) not in (int, float) or not math.isfinite(current):
                raise ControlError(device['name'] + ' has no usable volume button or known volume level.')
            # Check readability/state and writability before computing a new level.
            validate(device, 'volume_set', current)
            low, high = slider.get('min', 0), slider.get('max', 1)
            step = slider.get('step') or 0.01
            if type(step) not in (int, float) or not math.isfinite(step) or step <= 0:
                raise ControlError(device['name'] + ' reports an invalid volume step.')
            delta = max(1, round(0.05 / step)) * step
            if capability == 'volume_down':
                delta = -delta
            capability, value = 'volume_set', round(min(high, max(low, current + delta)), 10)
    validate(device, capability, value)
    return capability, value


class Controller:
    def __init__(self, client, aliases=None, preview=True):
        self.client, self.aliases, self.preview = client, aliases or {}, preview

    def inventory(self, pretty=False):
        devices, zones = self.client.catalog()
        if pretty:
            return '\n'.join(f'{d["name"]} · {zones.get(d.get("zone"), {}).get("name", "No room")}'
                             for d in devices.values()) or 'No devices found.'
        return '\n'.join(f'{d["name"]} | {zones.get(d.get("zone"), {}).get("name", "No room")} '
                         f'| {d["id"]} | {", ".join(d.get("capabilities", []))}' for d in devices.values()) or 'No devices found.'

    def run(self, text):
        intent = parse(text)
        devices, zones = self.client.catalog()
        selected = resolve(intent.target, devices, zones, self.aliases)
        if intent.capability is None:
            return '\n'.join(d['name'] + ': ' + ', '.join(describe(k, v.get('value'), v.get('units'))
                             for k, v in d.get('capabilitiesObj', {}).items()) for d in selected)
        # Validate the whole group before making any changes.
        actions = [(d, *plan_action(d, intent)) for d in selected]
        completed = []
        for d, capability, value in actions:
            if not self.preview:
                try:
                    self.client.set_value(d['id'], capability, value)
                except ControlError as e:
                    done = ', '.join(completed) or 'none'
                    raise ControlError(f'{e} Completed devices: {done}. Remaining devices were not attempted.') from None
            completed.append(d['name'])
        return ('Preview: ' if self.preview else 'Homey accepted: ') + '; '.join(
            d['name'] + ' → ' + describe(capability, value) for d, capability, value in actions)


def describe(capability, value, units=None):
    if value is None:
        return capability.replace('_', ' ') + ': unknown'
    if capability == 'onoff':
        return 'on' if value else 'off'
    if capability == 'speaker_playing':
        return 'playing' if value else 'paused'
    if capability in ('volume_up', 'volume_down'):
        return capability.replace('_', ' ')
    if capability == 'volume_set':
        return f'volume {value * 100:g}%'
    if capability == 'dim':
        return f'brightness {value * 100:g}%'
    if capability == 'target_temperature':
        return f'target temperature {value:g} {units or "°C"}'
    return capability.replace('_', ' ') + ': ' + str(value) + (' ' + units if units else '')
