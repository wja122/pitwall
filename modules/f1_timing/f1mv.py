"""F1 MultiViewer GraphQL client — polls live timing data and normalises it."""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

import requests

_CAR_RE = re.compile(r'CAR\s+(\d+)', re.IGNORECASE)

_GQL_QUERY = """{
  f1LiveTimingState {
    DriverList
    TimingData
    SessionInfo
    LapCount
    TrackStatus
    RaceControlMessages
    SessionStatus
  }
}"""

_TRACK_STATUS_MAP = {
    '1': 'GREEN',
    '2': 'YELLOW',
    '4': 'SC',
    '5': 'RED',
    '6': 'VSC',
    '7': 'VSC_ENDING',
}

_RACE_TYPES = {'Race', 'Sprint'}


@dataclass
class SectorState:
    value: str
    purple: bool   # overall session fastest
    green: bool    # personal fastest (not overall)


@dataclass
class DriverRow:
    number: str
    tla: str
    position: int
    team_color: tuple[int, int, int]
    display_time: str    # gap, lap time, PIT, OUT, or DNF
    fastest_lap: bool    # purple box
    investigating: bool  # yellow box
    penalty: bool        # red box
    in_pit: bool
    pit_out: bool
    retired: bool
    sectors: list[SectorState]


@dataclass
class TimingState:
    session_name: str
    circuit: str
    session_type: str    # 'Race', 'Qualifying', 'Sprint', 'Practice'
    current_lap: int
    total_laps: int
    track_status: str    # GREEN | YELLOW | SC | SC_ENDING | VSC | VSC_ENDING | RED
    drivers: list[DriverRow]


def _parse_color(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip('#').upper()
    if len(h) != 6:
        return (180, 180, 180)
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return (180, 180, 180)


def _parse_sector(s: dict) -> SectorState:
    overall = bool(s.get('OverallFastest'))
    return SectorState(
        value=s.get('Value', ''),
        purple=overall,
        green=bool(s.get('PersonalFastest')) and not overall,
    )


class F1MVClient:
    """Polls F1MV GraphQL every 500 ms and exposes a normalised TimingState."""

    def __init__(self, host: str = 'localhost', port: int = 10101) -> None:
        self._url = f'http://{host}:{port}/api/graphql'
        self._state: Optional[TimingState] = None
        self._error: Optional[str] = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # Persists across polls — OverallFastest is only true for one update
        self._fastest_lap_num: Optional[str] = None
        # RCM state — updated incrementally as new messages arrive
        self._rcm_seen: int = 0
        self._investigating: set[str] = set()   # car numbers under investigation
        self._penalty: set[str] = set()         # car numbers with an issued penalty

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name='f1mv-client'
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def get_state(self) -> tuple[Optional[TimingState], Optional[str]]:
        with self._lock:
            return self._state, self._error

    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            self._fetch()
            self._stop.wait(0.5)

    def _fetch(self) -> None:
        try:
            resp = requests.post(
                self._url,
                json={'query': _GQL_QUERY},
                timeout=3,
            )
            resp.raise_for_status()
            raw = resp.json()['data']['f1LiveTimingState']
            state = self._normalise(raw)
            with self._lock:
                self._state = state
                self._error = None
        except requests.Timeout:
            with self._lock:
                self._error = 'F1MV TIMEOUT'
        except Exception as exc:
            with self._lock:
                if self._state is None:
                    self._error = str(exc)[:28]

    def _process_rcms(self, msgs: list[dict]) -> None:
        """Incrementally consume new race control messages to track penalties."""
        for m in msgs[self._rcm_seen:]:
            subcat = m.get('SubCategory', '')
            text   = m.get('Message', '')
            nums   = _CAR_RE.findall(text)

            if subcat == 'IncidentUnderInvestigation':
                self._investigating.update(nums)
            elif subcat in ('IncidentNoFurtherAction', 'IncidentNoted'):
                self._investigating.difference_update(nums)
            elif 'PENALTY' in text.upper() and nums:
                # Penalty issued — clears investigation, marks penalty
                self._investigating.difference_update(nums)
                self._penalty.update(nums)

        self._rcm_seen = len(msgs)

    def _normalise(self, raw: dict) -> TimingState:
        # ── Session metadata ──────────────────────────────────────────
        info = raw.get('SessionInfo') or {}
        circuit = (info.get('Meeting') or {}).get('Circuit', {}).get('ShortName', '?').upper()
        session_type = info.get('Type', 'Race')
        session_name = info.get('Name', session_type).upper()

        lap = raw.get('LapCount') or {}
        current_lap = int(lap.get('CurrentLap') or 0)
        total_laps  = int(lap.get('TotalLaps') or 0)

        ts_code = str((raw.get('TrackStatus') or {}).get('Status', '1'))
        track_status = _TRACK_STATUS_MAP.get(ts_code, 'GREEN')

        # Process race control messages (SC ending, investigations, penalties)
        all_msgs = (raw.get('RaceControlMessages') or {}).get('Messages', [])
        self._process_rcms(all_msgs)

        if track_status == 'SC':
            for m in reversed(all_msgs[-10:]):
                if 'SAFETY CAR IN THIS LAP' in m.get('Message', ''):
                    track_status = 'SC_ENDING'
                    break

        # ── Drivers ───────────────────────────────────────────────────
        driver_list  = raw.get('DriverList') or {}
        timing_lines = (raw.get('TimingData') or {}).get('Lines') or {}
        is_race = session_type in _RACE_TYPES

        rows: list[DriverRow] = []
        for num, dinfo in driver_list.items():
            tl = timing_lines.get(num) or {}
            mv = tl.get('MVStatus') or {}

            position  = int(tl.get('Line') or tl.get('Position') or 99)
            tla       = dinfo.get('Tla', num)
            color     = _parse_color(dinfo.get('TeamColour', 'AAAAAA'))
            in_pit    = bool(mv.get('InPit')  or tl.get('InPit'))
            pit_out   = bool(mv.get('PitOut') or tl.get('PitOut') or mv.get('Outlap'))
            retired   = bool(mv.get('Retired') or tl.get('Retired') or mv.get('KnockedOut'))

            last_lap = tl.get('LastLapTime') or {}
            best_lap = tl.get('BestLapTime') or {}

            if retired:
                display_time = 'DNF'
            elif in_pit:
                display_time = 'PIT'
            elif pit_out:
                display_time = 'OUT'
            elif is_race:
                if position == 1:
                    display_time = last_lap.get('Value', '') or best_lap.get('Value', '')
                else:
                    display_time = tl.get('GapToLeader', '')
            else:
                display_time = best_lap.get('Value', '') or last_lap.get('Value', '')

            sectors_raw = tl.get('Sectors') or []
            sectors = [_parse_sector(s) for s in sectors_raw[:3]]
            while len(sectors) < 3:
                sectors.append(SectorState('', False, False))

            # Update persistent FL holder — OverallFastest is only true for
            # one poll cycle, so we latch it and keep it until someone else fires.
            if last_lap.get('OverallFastest'):
                self._fastest_lap_num = num

            rows.append(DriverRow(
                number=num,
                tla=tla,
                position=position,
                team_color=color,
                display_time=display_time,
                fastest_lap=False,               # resolved below
                investigating=num in self._investigating,
                penalty=num in self._penalty,
                in_pit=in_pit,
                pit_out=pit_out,
                retired=retired,
                sectors=sectors,
            ))

        # Apply persistent fastest lap to whichever driver holds it
        if self._fastest_lap_num is not None:
            for row in rows:
                if row.number == self._fastest_lap_num:
                    row.fastest_lap = True
                    break

        rows.sort(key=lambda d: d.position)

        return TimingState(
            session_name=session_name,
            circuit=circuit,
            session_type=session_type,
            current_lap=current_lap,
            total_laps=total_laps,
            track_status=track_status,
            drivers=rows,
        )
