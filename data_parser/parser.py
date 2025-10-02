import json
import re
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TypedDict


class Coordinate(TypedDict):
    latitude: float
    longitude: float

    @classmethod
    def from_str(cls, value: str) -> "Coordinate":
        assert len(value) == 11
        matched = re.match(r'(\d{2})(\d{2})([NS])(\d{3})(\d{2})([EW])', value)
        if not matched:
            raise ValueError("Wrong coordinate format")

        lat_deg, lat_min, lat_hemi, lon_deg, lon_min, lon_hemi = matched.groups()
        
        lat = int(lat_deg) + int(lat_min)/60.0
        lon = int(lon_deg) + int(lon_min)/60.0
        
        if lat_hemi == 'S':
            lat = -lat
        if lon_hemi == 'W':
            lon = -lon

        return Coordinate(latitude=lat, longitude=lon)


class ZoneType(StrEnum):
    CENTER = "center"
    PATH = "path"
    ID = "id"


class Zone(TypedDict, total=False):
    type: ZoneType
    center: Coordinate
    radius: float
    id: str
    path: list[Coordinate]


class FlightPoint:
    def __init__(
        self,
        coordinate: Coordinate | None = None,
        date: datetime | None = None,
    ) -> None:
        self.coordinate = coordinate
        self.date = date

    def to_json_dict(self) -> dict:
        return {
            "coordinate": self.coordinate,
            "date": self.date.strftime("%Y-%m-%d %H:%M:%S") if self.date else None,
        }


class FlightInfo:
    def __init__(
        self,
        bpla_id: str | None,
        bpla_type: str,
        departure: FlightPoint,
        arrival: FlightPoint,
        duration: timedelta | None = None,
        zone: Zone | None = None,
    ) -> None:
        self.bpla_id = bpla_id
        self.bpla_type = bpla_type
        self.departure = departure
        self.arrival = arrival
        self.duration = duration
        self.zone = zone

    def to_json_dict(self) -> dict:
        return {
            "bpla_id": self.bpla_id,
            "bpla_type": self.bpla_type,
            "departure": self.departure.to_json_dict(),
            "arrival": self.arrival.to_json_dict(),
            "duration": self.duration.total_seconds() if self.duration else None,
            "zone": self.zone,
        }


def parse_flight_info(shr_msg: str, dep_msg: str | None, arr_msg: str | None) -> FlightInfo:
    """
    Parse flight information from SHR, DEP, and ARR messages.
    
    Args:
        shr_msg: SHR message string containing flight details
        dep_msg: DEP message string (can be None)
        arr_msg: ARR message string (can be None)
    
    Returns:
        FlightInfo dictionary with parsed flight data
    """
    
    # Parse SHR message
    bpla_id = _extract_bpla_id(shr_msg)
    bpla_type = _extract_bpla_type(shr_msg)
    shr_departure_coords = _extract_departure_coordinates(shr_msg)
    shr_arrival_coords = _extract_arrival_coordinates(shr_msg)
    zone = _extract_zone(shr_msg)
    
    # Parse DEP message
    dep_coords = None
    dep_date = None
    if dep_msg:
        dep_coords = _extract_dep_coordinates(dep_msg)
        dep_date = _extract_dep_datetime(dep_msg)
    
    # Parse ARR message
    arr_coords = None
    arr_date = None
    if arr_msg:
        arr_coords = _extract_arr_coordinates(arr_msg)
        arr_date = _extract_arr_datetime(arr_msg)
    
    # Determine final coordinates (prefer DEP/ARR messages over SHR)
    departure_coords = dep_coords or shr_departure_coords
    if departure_coords is not None:
        departure_coords = Coordinate.from_str(departure_coords)
    arrival_coords = arr_coords or shr_arrival_coords
    if arrival_coords is not None:
        arrival_coords = Coordinate.from_str(arrival_coords)
    
    # Calculate duration
    duration = None
    if dep_date and arr_date:
        duration = arr_date - dep_date
    
    return FlightInfo(
        bpla_id=bpla_id,
        bpla_type=bpla_type,
        departure=FlightPoint(
            coordinate=departure_coords,
            date=dep_date
        ),
        arrival=FlightPoint(
            coordinate=arrival_coords,
            date=arr_date
        ),
        duration=duration,
        zone=zone,
    )


def _extract_zone(shr_msg: str) -> Zone | None:
    zona_match = re.search(r'/ZONA\s+([^/]+)', shr_msg)
    if zona_match:
        content = zona_match.group(1)
        zone = _parse_zone_content(content)
        if zone:
            return zone

    path_coords = _extract_k_zone(shr_msg)
    if path_coords:
        return {
            "type": ZoneType.PATH,
            "path": [Coordinate.from_str(coord) for coord in path_coords],
        }

    return None


def _parse_zone_content(content: str) -> Zone | None:
    tokens = [_clean_token(token) for token in content.replace('\n', ' ').split()]
    tokens = [token for token in tokens if token]
    if not tokens:
        return None

    first = tokens[0]
    if first.upper().startswith('R') and len(tokens) >= 2:
        radius = _parse_radius(first)
        center_token = next((token for token in tokens[1:] if _is_coordinate_token(token)), None)
        if radius is not None and center_token is not None:
            return {
                "type": ZoneType.CENTER,
                "center": Coordinate.from_str(center_token),
                "radius": radius,
            }

    coord_tokens = [token for token in tokens if _is_coordinate_token(token)]
    if len(coord_tokens) > 1:
        return {
            "type": ZoneType.PATH,
            "path": [Coordinate.from_str(token) for token in coord_tokens],
        }

    if len(tokens) == 1 and not _is_coordinate_token(tokens[0]):
        return {"type": ZoneType.ID, "id": tokens[0]}

    if len(coord_tokens) == 1:
        return {
            "type": ZoneType.PATH,
            "path": [Coordinate.from_str(coord_tokens[0])],
        }

    if tokens:
        return {"type": ZoneType.ID, "id": tokens[0]}

    return None


def _extract_k_zone(shr_msg: str) -> list[str] | None:
    k_lines = [line.strip() for line in shr_msg.splitlines() if line.strip().startswith('-K')]
    if not k_lines:
        return None
    if len(k_lines) > 1:
        raise ValueError("Multiple -K lines found in SHR message")

    tokens = k_lines[0].split()[1:]
    coords = [
        token
        for token in (_clean_token(token) for token in tokens)
        if _is_coordinate_token(token)
    ]

    return coords or None


def _clean_token(token: str) -> str:
    return token.strip().strip('.,/')


def _is_coordinate_token(token: str) -> bool:
    return bool(re.fullmatch(r'\d{4}[NS]\d{5}[EW]', token))


def _parse_radius(token: str) -> float | None:
    value = token.strip().upper()
    if not value.startswith('R'):
        return None

    number = value[1:].replace(',', '.')
    if not number:
        return None

    try:
        return float(number)
    except ValueError:
        return None


def _extract_bpla_id(shr_msg: str) -> str | None:
    """Extract flight ID from SHR message."""
    # Look for pattern like SHR-00725, SHR-ZZZZZ, SHR-RA0720G
    match = re.search(r'\(SHR-([A-Z0-9]+)', shr_msg)
    if match:
        bpla_id = match.group(1)
        # Filter out generic placeholders
        if bpla_id not in ['ZZZZ', 'ZZZZZ']:
            return bpla_id
    return None


def _extract_bpla_type(shr_msg: str) -> str:
    """Extract BPLA type from SHR message."""
    # Look for TYP/ pattern
    match = re.search(r'TYP/([A-Z]+)', shr_msg)
    if match:
        return match.group(1)
    return "BLA"  # default


def _extract_departure_coordinates(shr_msg: str) -> str | None:
    """Extract departure coordinates from SHR message."""
    # Look for DEP/ pattern
    match = re.search(r'DEP/(\d{4}N\d{5}E)', shr_msg)
    if match:
        return match.group(1)
    return None


def _extract_arrival_coordinates(shr_msg: str) -> str | None:
    """Extract arrival coordinates from SHR message."""
    # Look for DEST/ pattern
    match = re.search(r'DEST/(\d{4}N\d{5}E)', shr_msg)
    if match:
        return match.group(1)
    return None


def _extract_dep_coordinates(dep_msg: str) -> str | None:
    """Extract coordinates from DEP message."""
    # Look for ADEPZ pattern
    match = re.search(r'-ADEPZ (\d{4}N\d{5}E)', dep_msg)
    if match:
        return match.group(1)
    return None


def _extract_arr_coordinates(arr_msg: str) -> str | None:
    """Extract coordinates from ARR message."""
    # Look for ADARRZ pattern
    match = re.search(r'-ADARRZ (\d{4}N\d{5}E)', arr_msg)
    if match:
        return match.group(1)
    return None


def _extract_dep_datetime(dep_msg: str) -> datetime | None:
    """Extract departure datetime from DEP message."""
    date_match = re.search(r'-ADD (\d{6})', dep_msg)
    time_match = re.search(r'-ATD (\d{4})', dep_msg)
    
    if date_match and time_match:
        date_str = date_match.group(1)  # YYMMDD
        time_str = time_match.group(1)  # HHMM
        
        year = 2000 + int(date_str[:2])
        month = int(date_str[2:4])
        day = int(date_str[4:6])
        hour = int(time_str[:2])
        minute = int(time_str[2:4])
        
        return datetime(year, month, day, hour, minute)
    
    return None


def _extract_arr_datetime(arr_msg: str) -> datetime | None:
    """Extract arrival datetime from ARR message."""
    date_match = re.search(r'-ADA (\d{6})', arr_msg)
    time_match = re.search(r'-ATA (\d{4})', arr_msg)
    
    if date_match and time_match:
        date_str = date_match.group(1)  # YYMMDD
        time_str = time_match.group(1)  # HHMM
        
        year = 2000 + int(date_str[:2])
        month = int(date_str[2:4])
        day = int(date_str[4:6])
        hour = int(time_str[:2])
        minute = int(time_str[2:4])
        
        return datetime(year, month, day, hour, minute)
    
    return None


# Test the parser with the provided examples
if __name__ == "__main__":
    def print_result(label: str, info: FlightInfo) -> None:
        print(label)
        print(json.dumps(info.to_json_dict(), indent=2))
        print()

    # Test case 1
    shr1 = """(SHR-00725
-ZZZZ0600
-M0000/M0005 /ZONA R0,5 4408N04308E/
-ZZZZ0700
-DEP/4408N04308E DEST/4408N04308E DOF/250124 OPR/ГУ М4С РОССИИ ПО
СТАВРОПОЛЬСКОМУ КРАЮ REG/00724,REG00725 STS/SAR TYP/BLA RMK/WR655 В
ЗОНЕ ВИЗУАЛЬНОГО ПОЛЕТА СОГЛАСОВАНО С ЕСОРВД РОСТОВ ПОЛЕТ БЛА В
ВП-С-М4С МОНИТОРИНГ ПАВОДКООПАСНЫХ У4АСТКОВ РАЗРЕШЕНИЕ 10-37/9425
15.11.2024 АДМИНИСТРАЦИЯ МИНЕРАЛОВОДСКОГО МУНИЦИПАЛЬНОГО ОКРУГА
ОПЕРАТОР ЛЯХОВСКАЯ +79283000251 ЛЯПИН +79620149012 SID/7772251137)"""

    dep1 = """-TITLE IDEP
-SID 7772187998
-ADD 250201
-ATD 0705
-ADEP ZZZZ
-ADEPZ 5957N02905E
-PAP 0"""

    arr1 = None

    result1 = parse_flight_info(shr1, dep1, arr1)
    print_result("Test 1 Result:", result1)

    # Test case 2
    shr2 = """(SHR-ZZZZZ
-ZZZZ0600
-M0045/M0140 /ZONA WR1825/
-ZZZZ1000
-DEP/5659N05248E DEST/5659N05248E DOF/250217 EET/USSV0001 OPR/ООО
АЭРОСКАН REG/00I0164 TYP/BLA RMK/ВР1825 КИЯИК ОПЕРАТОРЫ БВС СЕМЕНОВ
89168168252 СКОБЕЛЕВ 89630260730 ПОЛЕТЫ НАД НАСЕЛЕННЫМИ ПУНКТАМИ НЕ
ПРОИЗВОДЯТСЯ ПОЛЕТ В РАЙОНЕ 250 1200М AGL 450 1400М AMSL SID/7772337468)"""

    dep2 = """-TITLE IDEP
-SID 7772337468
-ADD 250217
-ATD 0600"""

    arr2 = """-TITLE IARR
-SID 7772337468
-ADA 250217
-ATA 1501"""

    result2 = parse_flight_info(shr2, dep2, arr2)
    print_result("Test 2 Result:", result2)

    # Test case 3
    shr3 = """(SHR-RA0720G
-ZZZZ0400
-K0001M0040
-DEP/5200N08554E DLE/5200N08554E0700 DOF/250315 OPR/ЯВЦЕВ ВЯ4ЕСЛАВ
ГЕННАДЬЕВИ4 ORGN/+79136976996 REG/RA0720G TYP/SHAR RMK/ПРИВЯЗНОЙ
АЭРОСТАТ ВЫСОТА ПОДЬЕМА 40 М ПРОДОЛЖИТЕЛЬНОСТЬ 7 4АСОВ 00 МИН
89136976996 ЯВЦЕВ ВЯ4ЕСЛАВ ГЕННАДЬЕВИ4 SID/7772393765)"""

    dep3 = """-TITLE IDEP
-SID 7772393765
-ADD 250315
-ATD 0400
-ADEP ZZZZ
-ADEPZ 5200N08554E
-PAP 0
-REG RA0720G"""

    arr3 = """-TITLE IARR
-SID 7772393765
-ADA 250315
-ATA 1106
-ADARR ZZZZ
-ADARRZ 5200N08554E
-PAP 0
-REG RA0720G"""

    result3 = parse_flight_info(shr3, dep3, arr3)
    print_result("Test 3 Result:", result3)

    # Test case 4
    shr4 = """(SHR-KPATH
-ZZZZ0000
-K0000M0000 1234N01234E 1235N01235E 1236N01236E
-ZZZZ0100
-DEP/1234N01234E DEST/1236N01236E DOF/250101 TYP/BLA)"""

    result4 = parse_flight_info(shr4, None, None)
    print_result("Test 4 Result:", result4)
