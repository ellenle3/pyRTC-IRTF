from dataclasses import dataclass, field
import math
import os
import struct
import time
from constants import *
from typing import List, Tuple, Optional

ERR_NONE = 0
ERR_FILE_READ = -1

@dataclass
class IrcatRecord:
    ra: float = 0.0
    dec: float = 0.0
    rapm: float = 0.0
    decpm: float = 0.0
    mag: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    magD: List[str] = field(default_factory=lambda: ['-', '-', '-', '-'])
    name: str = ""
    catID: int = 0

class NomadRecord:
    SIZE = 88  # True C struct size in bytes
    FORMAT = "<22i"  # 22 x 32-bit signed integers


def clip_range(min_val: float, val: float, max_val: float) -> float:
    return max(min_val, min(val, max_val))


def in_range(low: float, val: float, high: float) -> bool:
    return low <= val <= high


def dranrm(angle: float) -> float:
    return angle % D2PI
    
def angular_distance(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """
    Computes exact great-circle angular distance (in radians) between
    two points (ra1, dec1) and (ra2, dec2) using the Haversine formula.
    """
    ddec = dec2 - dec1
    dra = ra2 - ra1
    a = (math.sin(ddec / 2.0) ** 2) + math.cos(dec1) * math.cos(dec2) * (math.sin(dra / 2.0) ** 2)
    return 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))


def nomad_read_record(fp, zone: int, rec_no: int) -> Optional[IrcatRecord]:
    raw_bytes = fp.read(NomadRecord.SIZE) # 88 bytes
    if len(raw_bytes) < NomadRecord.SIZE:
        return None

    # Unpack 22 32-bit signed integers (<22i)
    unpacked = struct.unpack(NomadRecord.FORMAT, raw_bytes)

    # 1. Coordinates & Proper Motion (Fields 0..3)
    ra_val, spd_val, pm_ra_val, pm_spd_val = unpacked[0:4]

    rec = IrcatRecord()
    rec.ra = ra_val * 0.001 * DAS2R                      # RA in radians
    rec.dec = (spd_val * 0.001 * DAS2R) - (90.0 * DD2R)  # Dec in radians
    rec.rapm = pm_ra_val * 0.0001 / 15.0                 # RA pm in sec/yr
    rec.decpm = pm_spd_val * 0.0001                      # Dec pm in arcsec/yr

    # 2. Magnitudes (Fields 10..13)
    # Adjust field indices 10, 11, 12, 13 if your nomad.h has V/B/R/J in a slightly different order
    b_mag = unpacked[10]
    v_mag = unpacked[11]
    r_mag = unpacked[12]
    j_mag = unpacked[13]

    if 0 < v_mag < 30000:
        rec.mag[0] = v_mag * 0.001
        rec.magD[0] = 'V'

    if 0 < b_mag < 30000:
        rec.mag[1] = b_mag * 0.001
        rec.magD[1] = 'B'

    if 0 < r_mag < 30000:
        rec.mag[2] = r_mag * 0.001
        rec.magD[2] = 'R'

    if 0 < j_mag < 30000:
        rec.mag[3] = j_mag * 0.001
        rec.magD[3] = 'J'

    rec.name = f"NOMAD1_{zone:05d}-{rec_no:07d}"
    rec.catID = rec_no

    return rec


def nomad_acc_search(ra: float, nomad_root: str, file_id: int) -> int:
    rec_no = 1
    zone = file_id // 10
    acc_filename = os.path.join(nomad_root, f"{zone:03d}", f"m{file_id:04d}.acc")

    if not os.path.exists(acc_filename):
        return rec_no

    try:
        with open(acc_filename, "rt") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                try:
                    acc_ra = float(parts[0]) * DH2R
                    acc_rec_no = int(parts[1])
                except ValueError:
                    break

                if ra < acc_ra:
                    break

                if not in_range(0, acc_rec_no, 1500000):
                    break

                rec_no = acc_rec_no
    except OSError:
        pass

    return rec_no


def nomad_search_box(
    maximum: int,
    ra_beg: float,
    ra_end: float,
    dec_beg: float,
    dec_end: float,
    nomad_root: str,
    file_id: int,
    enable_mag_limit: bool,
    mag_limit: float,
    debug: bool = False
) -> Tuple[List[IrcatRecord], int]:
    t_start = time.time()
    found_records: List[IrcatRecord] = []
    zone = file_id // 10
    rc = ERR_NONE

    rec_no = nomad_acc_search(max(0.0, ra_beg), nomad_root, file_id)
    cat_filename = os.path.join(nomad_root, f"{zone:03d}", f"m{file_id:04d}.cat")

    if not os.path.exists(cat_filename):
        return found_records, ERR_FILE_READ

    try:
        with open(cat_filename, "rb") as fp:
            fp.seek((rec_no - 1) * NomadRecord.SIZE)

            while len(found_records) < maximum:
                ircat = nomad_read_record(fp, zone, rec_no)
                if ircat is None:
                    break

                if ircat.ra > ra_end:
                    break

                if not (in_range(ra_beg, ircat.ra, ra_end) and in_range(dec_beg, ircat.dec, dec_end)):
                    pass
                elif enable_mag_limit and (
                    ircat.magD[:3] == ['-', '-', '-'] or
                    (ircat.magD[0] == 'V' and ircat.mag[0] >= mag_limit) or
                    (ircat.magD[1] == 'B' and ircat.mag[1] >= mag_limit) or
                    (ircat.magD[2] == 'R' and ircat.mag[2] >= mag_limit)
                ):
                    pass
                else:
                    found_records.append(ircat)

                rec_no += 1
    except OSError:
        rc = ERR_FILE_READ

    t_elapsed = time.time() - t_start
    if debug:
        print(f"nomad_search_box() ra {ra_beg*DR2H:.3f} {ra_end*DR2H:.3f} "
              f"dec {dec_beg*DR2D:.3f} {dec_end*DR2D:.3f} file_id={file_id:04d} "
              f"found={len(found_records)}, max={maximum} esec={t_elapsed:.3f}")

    return found_records, rc

def nomad_search_pos(
    ra: float,
    dec: float,
    radius: float,
    nomad_root: str,
    maximum: int = 1000,
    enable_mag_limit: bool = False,
    mag_limit: float = 0.0,
    debug: bool = False
) -> Tuple[List[IrcatRecord], int]:
    """
    Main entry point: Searches stars around (ra, dec) within radius (all in radians).
    Results are sorted by angular proximity to (ra, dec), closest first.
    """
    records: List[IrcatRecord] = []

    dec_beg = clip_range(-DPIBY2, dec - radius, DPIBY2)
    dec_end = clip_range(-DPIBY2, dec + radius, DPIBY2)

    cos_dec = math.cos(clip_range(-89.9 * DD2R, dec, 89.9 * DD2R))
    dist = radius / cos_dec
    ra_beg = ra - dist
    ra_end = ra + dist

    dec_beg_i = int((90.0 + (dec_beg * DR2D)) * 10)
    dec_end_i = int((90.0 + (dec_end * DR2D)) * 10)

    if debug:
        print(f"nomad_search_pos(): rad={radius*DR2AS:.0f}as dist={dist*DR2AS:.0f}as "
              f"{dist*DR2D:.3f}deg Dec: {90.0+dec_beg*DR2D:.3f}-{90.0+dec_end*DR2D:.3f} "
              f"{dec_beg_i:04d}-{dec_end_i:04d}")

    # Pass a high maximum (e.g. 100,000) to sub-searches so we gather all stars in the 
    # search box before sorting, ensuring we don't accidentally omit a closer star.
    fetch_limit = 100000

    for dec_i in range(dec_beg_i, dec_end_i + 1):
        # Primary search box
        box_recs, _ = nomad_search_box(
            fetch_limit, ra_beg, ra_end, dec_beg, dec_end, nomad_root, dec_i,
            enable_mag_limit, mag_limit, debug
        )
        records.extend(box_recs)

        # Wrap-around > 24 hrs
        if ra_end > D2PI:
            box_recs, _ = nomad_search_box(
                fetch_limit, 0.0, dranrm(ra_end), dec_beg, dec_end, nomad_root, dec_i,
                enable_mag_limit, mag_limit, debug
            )
            records.extend(box_recs)

        # Wrap-around < 0 hrs
        if ra_beg < 0.0:
            box_recs, _ = nomad_search_box(
                fetch_limit, dranrm(ra_beg), D2PI, dec_beg, dec_end, nomad_root, dec_i,
                enable_mag_limit, mag_limit, debug
            )
            records.extend(box_recs)

    # Add separation to records
    for star in records:
        star.separation = angular_distance(ra, dec, star.ra, star.dec)
    
    # Sort results by true angular separation (closest first)
    #records.sort(key=lambda star: angular_distance(ra, dec, star.ra, star.dec))
    records.sort(key=lambda star: star.separation)

    # Put V < 16 stars at the top, sorted by distance, if within 20" of the guide box
    records_bright = []
    records_faint = []
    for star in records:
        if (star.magD[0] == "V" and star.mag[0] < 16 and star.separation < 20 * DR2AS):
            records_bright.append(star)
        else:
            records_faint.append(star)
    records = records_bright + records_faint
    
    # Truncate to maximum requested records
    records = records[:maximum]

    return records, ERR_NONE