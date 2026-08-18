import argparse
import csv
import difflib
import logging
import re
import sqlite3
import sys
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from pathlib import Path
import http.server
import socketserver
import threading
import json
import shutil
import subprocess
import mimetypes
import uuid
import html


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("merge_users")



CITY_SYNONYMS = {
    "gurgaon": "Gurgaon",
    "gurugram": "Gurgaon",
    "bangalore": "Bengaluru",
    "bengaluru": "Bengaluru",
    "new delhi": "New Delhi",
    "delhi ncr": "New Delhi",
    "delhi": "Delhi",
    "noida": "Noida",
    "pune": "Pune",
}

EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

DATE_FORMATS = [
    "%d-%m-%Y",
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%d %b %Y",
    "%d %B %Y",
]


def clean_str(value) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if s.lower() in ("nan", "none", ""):
        return ""
    return re.sub(r"\s+", " ", s)


def normalize_email(value) -> str:
    s = clean_str(value).lower()
    return s if EMAIL_RE.fullmatch(s) else ""


def normalize_phone(value):
    
    raw = clean_str(value)
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None, True

    if digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]

    if len(digits) == 10 and digits[0] in "6789":
        return digits, False
    return (digits if digits else None), True


def normalize_city(value) -> str:
    s = clean_str(value)
    key = s.lower().strip()
    return CITY_SYNONYMS.get(key, s.title() if s else "")


def normalize_name_for_display(value) -> str:
    s = clean_str(value)
    return " ".join(w if w.endswith(".") else w.capitalize() for w in s.split())


def normalize_name_for_match(value) -> str:
    s = clean_str(value).lower()
    s = re.sub(r"[^\w\s]", "", s)  
    return " ".join(sorted(s.split()))  


def name_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def parse_date(value):
    s = clean_str(value)
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None  


def normalize_ctc(value):
    
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None, None
    if v < 100:  
        return v, round(v * 100_000)
    return v, round(v)


def normalize_rate(value):
    
    s = clean_str(value)
    m = re.match(r"([\d.]+)\s*/\s*hr$", s, re.I)
    if m:
        hourly = float(m.group(1))
        return s, round(hourly * 8 * 22), "hourly"
    m = re.match(r"([\d.]+)\s*k\s*/\s*month$", s, re.I)
    if m:
        monthly = float(m.group(1)) * 1000
        return s, round(monthly), "monthly"
    return s, None, "unknown"




@dataclass
class Record:
    source: str
    row_index: int
    raw_row: dict
    name_raw: str = ""
    email_raw: str = ""
    phone_raw: str = ""
    city_raw: str = ""
    norm_email: str = ""
    norm_phone: str = None
    norm_city: str = ""
    norm_name_display: str = ""
    norm_name_match: str = ""
    extra: dict = field(default_factory=dict)
    user_id: int = None  


ANOMALIES = []  
def flag(source, row_index, issue_type, detail, raw_row=None):
    ANOMALIES.append(
        {
            "source_file": source,
            "row_identifier": str(row_index),
            "issue_type": issue_type,
            "detail": detail,
            "raw_row": repr(raw_row) if raw_row is not None else "",
        }
    )
    log.warning("[%s row %s] %s: %s", source, row_index, issue_type, detail)




def read_csv_rows(path: Path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=2):  
            yield i, row


def is_blank_row(row: dict) -> bool:
    return all(clean_str(v) == "" for v in row.values())


def ingest_naukri(path: Path):
    """source1: Full Name, Email, Phone, City, Experience (Years), Current CTC,
    Applied Date, Skills"""
    records = []
    for i, row in read_csv_rows(path):
        if is_blank_row(row):
            flag("naukri", i, "blank_row", "entire row empty, skipped")
            continue

        r = Record(source="naukri", row_index=i, raw_row=row)
        r.name_raw = clean_str(row.get("Full Name"))
        r.email_raw = clean_str(row.get("Email"))
        r.phone_raw = clean_str(row.get("Phone"))
        r.city_raw = clean_str(row.get("City"))

        r.norm_email = normalize_email(r.email_raw)
        if r.email_raw and not r.norm_email:
            flag("naukri", i, "malformed_email", f"unparseable email: {r.email_raw!r}")
        elif not r.email_raw:
            flag("naukri", i, "missing_email", "email field empty")

        phone, malformed = normalize_phone(r.phone_raw)
        r.norm_phone = phone
        if malformed:
            flag("naukri", i, "malformed_phone", f"could not normalize phone: {r.phone_raw!r}")

        r.norm_city = normalize_city(r.city_raw)
        r.norm_name_display = normalize_name_for_display(r.name_raw)
        r.norm_name_match = normalize_name_for_match(r.name_raw)

        ctc_raw, ctc_norm = normalize_ctc(row.get("Current CTC"))
        if ctc_raw is None:
            flag("naukri", i, "malformed_ctc", f"unparseable CTC: {row.get('Current CTC')!r}")

        applied_raw = clean_str(row.get("Applied Date"))
        applied_parsed = parse_date(applied_raw)
        if applied_raw and not applied_parsed:
            flag("naukri", i, "unparseable_date", f"Applied Date: {applied_raw!r}")

        try:
            experience = float(row.get("Experience (Years)"))
        except (TypeError, ValueError):
            experience = None
            flag("naukri", i, "malformed_experience", f"{row.get('Experience (Years)')!r}")

        r.extra = {
            "experience_years": experience,
            "current_ctc_raw": ctc_raw,
            "current_ctc_normalized_inr": ctc_norm,
            "applied_date_raw": applied_raw,
            "applied_date_parsed": applied_parsed,
            "skills_raw": clean_str(row.get("Skills")),
        }
        records.append(r)
    return records


def ingest_gig(path: Path):
    
    records = []
    expected_cols = {"email_id", "worker_name", "rate", "location", "status", "skill_tags"}

    for i, row in read_csv_rows(path):
        if is_blank_row(row):
            flag("gig", i, "blank_row", "entire row empty, skipped")
            continue

        
        if not EMAIL_RE.search(clean_str(row.get("email_id"))):
            values = list(row.values())
            email_val = next((v for v in values if EMAIL_RE.search(clean_str(v))), None)
            if email_val:
                flag(
                    "gig",
                    i,
                    "corrupted_row_recovered",
                    f"columns appear rotated (email found in wrong column); "
                    f"realigned by locating the '@' field. raw={row}",
                    raw_row=row,
                )
                status_val = next(
                    (v for v in values if clean_str(v).lower() in
                     ("active", "inactive", "paused")), ""
                )
                rate_val = next(
                    (v for v in values if re.match(r"[\d.]+\s*(/\s*hr|k\s*/\s*month)$",
                                                     clean_str(v), re.I)), ""
                )
                
                remaining = [v for v in values if v not in (email_val, status_val, rate_val)]
                skills_val = next((v for v in remaining if "," in clean_str(v)), "")
                remaining2 = [v for v in remaining if v != skills_val]
                
                location_val = next(
                    (v for v in remaining2 if clean_str(v).lower() in CITY_SYNONYMS), ""
                )
                name_val = next((v for v in remaining2 if v != location_val), "")
                if not location_val and remaining2:
                    
                    location_val, name_val = remaining2[-1], remaining2[0]
                row = {
                    "email_id": email_val,
                    "worker_name": name_val,
                    "rate": rate_val,
                    "location": location_val,
                    "status": status_val,
                    "skill_tags": skills_val,
                }
            else:
                flag("gig", i, "corrupted_row_unrecoverable", f"no email found anywhere in row, quarantined: {row}")
                continue

        r = Record(source="gig", row_index=i, raw_row=row)
        r.name_raw = clean_str(row.get("worker_name"))
        r.email_raw = clean_str(row.get("email_id"))
        r.city_raw = clean_str(row.get("location"))
        r.phone_raw = ""  

        r.norm_email = normalize_email(r.email_raw)
        if r.email_raw and not r.norm_email:
            flag("gig", i, "malformed_email", f"unparseable email: {r.email_raw!r}")
        elif not r.email_raw:
            flag("gig", i, "missing_email", "email field empty")

        r.norm_city = normalize_city(r.city_raw)
        r.norm_name_display = normalize_name_for_display(r.name_raw)
        r.norm_name_match = normalize_name_for_match(r.name_raw)

        rate_raw, rate_norm, rate_unit = normalize_rate(row.get("rate"))
        status = clean_str(row.get("status")).lower()
        if status not in ("active", "inactive", "paused", ""):
            flag("gig", i, "unrecognized_status", f"{status!r}")

        r.extra = {
            "rate_raw": rate_raw,
            "rate_normalized_monthly_inr": rate_norm,
            "rate_unit_detected": rate_unit,
            "status": status,
            "skill_tags_raw": clean_str(row.get("skill_tags")),
        }
        records.append(r)
    return records


def ingest_cbnexus(path: Path):
    """source3: Name, Phone Number, City, Verified, Projects Completed
    Known corruption: header row repeated mid-file."""
    records = []
    for i, row in read_csv_rows(path):
        if is_blank_row(row):
            flag("cbnexus", i, "blank_row", "entire row empty, skipped")
            continue
        if clean_str(row.get("Name")).lower() == "name":
            flag("cbnexus", i, "duplicate_header_row", "repeated header row mid-file, skipped")
            continue

        r = Record(source="cbnexus", row_index=i, raw_row=row)
        r.name_raw = clean_str(row.get("Name"))
        r.phone_raw = clean_str(row.get("Phone Number"))
        r.city_raw = clean_str(row.get("City"))
        r.email_raw = ""  

        phone, malformed = normalize_phone(r.phone_raw)
        r.norm_phone = phone
        if malformed:
            flag("cbnexus", i, "malformed_phone", f"could not normalize phone: {r.phone_raw!r}")

        r.norm_city = normalize_city(r.city_raw)
        r.norm_name_display = normalize_name_for_display(r.name_raw)
        r.norm_name_match = normalize_name_for_match(r.name_raw)

        verified_raw = clean_str(row.get("Verified"))
        verified_map = {"y": True, "yes": True, "n": False, "no": False}
        verified = verified_map.get(verified_raw.lower())
        if verified is None:
            flag("cbnexus", i, "unrecognized_verified_flag", f"{verified_raw!r}")

        try:
            projects = int(row.get("Projects Completed"))
        except (TypeError, ValueError):
            projects = None
            flag("cbnexus", i, "malformed_projects_completed", f"{row.get('Projects Completed')!r}")

        r.extra = {
            "verified_raw": verified_raw,
            "verified": verified,
            "projects_completed": projects,
        }
        records.append(r)
    return records




FUZZY_NAME_THRESHOLD = 0.87


class UnionFind:
    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def resolve_identities(records: list[Record]):
    n = len(records)
    uf = UnionFind(n)

    email_index = {}
    phone_index = {}
    for idx, r in enumerate(records):
        if r.norm_email:
            email_index.setdefault(r.norm_email, []).append(idx)
        if r.norm_phone:
            phone_index.setdefault(r.norm_phone, []).append(idx)

    for email, idxs in email_index.items():
        for other in idxs[1:]:
            uf.union(idxs[0], other)
            log.info("MATCH (exact email): %s <-> %s on %s",
                      _tag(records[idxs[0]]), _tag(records[other]), email)

    for phone, idxs in phone_index.items():
        for other in idxs[1:]:
            uf.union(idxs[0], other)
            log.info("MATCH (exact phone): %s <-> %s on %s",
                      _tag(records[idxs[0]]), _tag(records[other]), phone)

    
    def group_identifiers(root):
        emails, phones = set(), set()
        for idx in range(n):
            if uf.find(idx) == root:
                if records[idx].norm_email:
                    emails.add(records[idx].norm_email)
                if records[idx].norm_phone:
                    phones.add(records[idx].norm_phone)
        return emails, phones

    for i in range(n):
        for j in range(i + 1, n):
            a, b = records[i], records[j]
            if uf.find(i) == uf.find(j):
                continue  # already linked
            if not a.norm_name_match or not b.norm_name_match:
                continue
            if not a.norm_city or a.norm_city != b.norm_city:
                continue

            sim = name_similarity(a.norm_name_match, b.norm_name_match)
            if sim < FUZZY_NAME_THRESHOLD:
                continue

           
            emails_i, phones_i = group_identifiers(uf.find(i))
            emails_j, phones_j = group_identifiers(uf.find(j))
            email_conflict = emails_i and emails_j and not (emails_i & emails_j) and (emails_i != emails_j)
            phone_conflict = phones_i and phones_j and not (phones_i & phones_j) and (phones_i != phones_j)

            if email_conflict or phone_conflict:
                flag(
                    f"{a.source}+{b.source}",
                    f"{a.row_index}/{b.row_index}",
                    "possible_duplicate_conflicting_identifiers",
                    f"Same/similar name ({a.name_raw!r} vs {b.name_raw!r}, "
                    f"similarity={sim:.2f}) and same city ({a.norm_city}), "
                    f"but conflicting {'email' if email_conflict else 'phone'} "
                    f"({a.norm_email or a.norm_phone} != {b.norm_email or b.norm_phone}). "
                    f"NOT auto-merged -- kept as separate identities, flagged for manual review.",
                )
                continue

            uf.union(i, j)
            flag(
                f"{a.source}+{b.source}",
                f"{a.row_index}/{b.row_index}",
                "fuzzy_match_merged",
                f"Merged on fuzzy name match ({a.name_raw!r} vs {b.name_raw!r}, "
                f"similarity={sim:.2f}) + matching city ({a.norm_city}). "
                f"Low-confidence -- recommend spot-checking.",
            )

    groups = {}
    for idx in range(n):
        root = uf.find(idx)
        groups.setdefault(root, []).append(idx)
    return list(groups.values())


def _tag(r: Record) -> str:
    return f"{r.source}#{r.row_index}({r.name_raw!r})"




def pick_canonical_name(recs: list[Record]) -> str:
    candidates = [r.norm_name_display for r in recs if r.norm_name_display]
    if not candidates:
        return ""
    return max(candidates, key=lambda n: (("." not in n), len(n)))


def pick_first(values):
    for v in values:
        if v:
            return v
    return None




SCHEMA = """
CREATE TABLE users (
    user_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name           TEXT NOT NULL,
    primary_email        TEXT,
    primary_phone        TEXT,
    city                TEXT,
    source_count         INTEGER NOT NULL,
    matched_sources       TEXT NOT NULL,      -- comma-separated: naukri,gig,cbnexus
    match_confidence      TEXT NOT NULL,      -- exact / fuzzy / single_source
    created_at           TEXT NOT NULL
);

CREATE TABLE user_emails (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL REFERENCES users(user_id),
    email     TEXT NOT NULL,
    source    TEXT NOT NULL
);

CREATE TABLE user_phones (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL REFERENCES users(user_id),
    phone     TEXT NOT NULL,
    source    TEXT NOT NULL
);

CREATE TABLE user_skills (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL REFERENCES users(user_id),
    skill     TEXT NOT NULL,
    source    TEXT NOT NULL
);

CREATE TABLE naukri_applications (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id                INTEGER NOT NULL REFERENCES users(user_id),
    source_row             INTEGER NOT NULL,
    name_raw               TEXT,
    email_raw              TEXT,
    phone_raw              TEXT,
    city_raw               TEXT,
    experience_years        REAL,
    current_ctc_raw          REAL,
    current_ctc_normalized_inr INTEGER,
    applied_date_raw         TEXT,
    applied_date_parsed       TEXT,
    skills_raw              TEXT
);

CREATE TABLE gig_worker_profiles (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id                   INTEGER NOT NULL REFERENCES users(user_id),
    source_row                INTEGER NOT NULL,
    name_raw                  TEXT,
    email_raw                 TEXT,
    city_raw                  TEXT,
    rate_raw                  TEXT,
    rate_normalized_monthly_inr INTEGER,
    rate_unit_detected          TEXT,
    status                    TEXT,
    skill_tags_raw              TEXT
);

CREATE TABLE cbnexus_contacts (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL REFERENCES users(user_id),
    source_row          INTEGER NOT NULL,
    name_raw            TEXT,
    phone_raw           TEXT,
    city_raw             TEXT,
    verified_raw          TEXT,
    verified             INTEGER,
    projects_completed     INTEGER
);

CREATE TABLE data_quality_issues (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file      TEXT NOT NULL,
    row_identifier    TEXT NOT NULL,
    issue_type       TEXT NOT NULL,
    detail           TEXT NOT NULL,
    raw_row          TEXT,
    logged_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audio_submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(user_id),
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    stored_filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    duration_seconds REAL,
    sample_rate_hz INTEGER,
    bitrate_kbps REAL,
    loudness_db REAL,
    quality_estimate TEXT,
    file_size_bytes INTEGER NOT NULL,
    submitted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audio_data_quality_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audio_submission_id INTEGER,
    issue_type TEXT NOT NULL,
    detail TEXT NOT NULL,
    logged_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audio_user ON audio_submissions(user_id);
CREATE INDEX IF NOT EXISTS idx_audio_phone ON audio_submissions(phone);
CREATE INDEX IF NOT EXISTS idx_audio_submitted_at ON audio_submissions(submitted_at);

CREATE INDEX idx_users_email ON users(primary_email);
CREATE INDEX idx_users_phone ON users(primary_phone);
CREATE INDEX idx_user_emails_user ON user_emails(user_id);
CREATE INDEX idx_user_phones_user ON user_phones(user_id);
"""


def build_database(db_path: Path, groups, records: list[Record]):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    # Ensure audio_submissions table exists for legacy DBs
    conn.execute("CREATE TABLE IF NOT EXISTS audio_submissions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER REFERENCES users(user_id), name TEXT NOT NULL, phone TEXT NOT NULL, original_filename TEXT NOT NULL, stored_filename TEXT NOT NULL, file_path TEXT NOT NULL, duration_seconds REAL, sample_rate_hz INTEGER, bitrate_kbps REAL, loudness_db REAL, quality_estimate TEXT, file_size_bytes INTEGER NOT NULL, submitted_at TEXT NOT NULL)")
    cur = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()

    for group in groups:
        recs = [records[i] for i in group]
        sources = sorted(set(r.source for r in recs))
        emails = sorted(set(r.norm_email for r in recs if r.norm_email))
        phones = sorted(set(r.norm_phone for r in recs if r.norm_phone))

        if len(sources) == 1:
            confidence = "single_source"
        elif any(r.norm_email for r in recs) or any(r.norm_phone for r in recs):
            confidence = "exact"
        else:
            confidence = "fuzzy"

        full_name = pick_canonical_name(recs)
        city = pick_first([r.norm_city for r in recs])

        cur.execute(
            """INSERT INTO users
               (full_name, primary_email, primary_phone, city, source_count,
                matched_sources, match_confidence, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                full_name,
                emails[0] if emails else None,
                phones[0] if phones else None,
                city,
                len(sources),
                ",".join(sources),
                confidence,
                now,
            ),
        )
        user_id = cur.lastrowid

        for e in emails:
            src = next(r.source for r in recs if r.norm_email == e)
            cur.execute(
                "INSERT INTO user_emails (user_id, email, source) VALUES (?, ?, ?)",
                (user_id, e, src),
            )
        for p in phones:
            src = next(r.source for r in recs if r.norm_phone == p)
            cur.execute(
                "INSERT INTO user_phones (user_id, phone, source) VALUES (?, ?, ?)",
                (user_id, p, src),
            )

        skill_set = set()
        for r in recs:
            raw_skills = r.extra.get("skills_raw") or r.extra.get("skill_tags_raw") or ""
            for s in raw_skills.split(","):
                s = s.strip().lower()
                if s and s not in skill_set:
                    skill_set.add(s)
                    cur.execute(
                        "INSERT INTO user_skills (user_id, skill, source) VALUES (?, ?, ?)",
                        (user_id, s, r.source),
                    )

        for r in recs:
            if r.source == "naukri":
                cur.execute(
                    """INSERT INTO naukri_applications
                       (user_id, source_row, name_raw, email_raw, phone_raw, city_raw,
                        experience_years, current_ctc_raw, current_ctc_normalized_inr,
                        applied_date_raw, applied_date_parsed, skills_raw)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        user_id, r.row_index, r.name_raw, r.email_raw, r.phone_raw, r.city_raw,
                        r.extra.get("experience_years"), r.extra.get("current_ctc_raw"),
                        r.extra.get("current_ctc_normalized_inr"), r.extra.get("applied_date_raw"),
                        r.extra.get("applied_date_parsed"), r.extra.get("skills_raw"),
                    ),
                )
            elif r.source == "gig":
                cur.execute(
                    """INSERT INTO gig_worker_profiles
                       (user_id, source_row, name_raw, email_raw, city_raw, rate_raw,
                        rate_normalized_monthly_inr, rate_unit_detected, status, skill_tags_raw)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        user_id, r.row_index, r.name_raw, r.email_raw, r.city_raw,
                        r.extra.get("rate_raw"), r.extra.get("rate_normalized_monthly_inr"),
                        r.extra.get("rate_unit_detected"), r.extra.get("status"),
                        r.extra.get("skill_tags_raw"),
                    ),
                )
            elif r.source == "cbnexus":
                cur.execute(
                    """INSERT INTO cbnexus_contacts
                       (user_id, source_row, name_raw, phone_raw, city_raw,
                        verified_raw, verified, projects_completed)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        user_id, r.row_index, r.name_raw, r.phone_raw, r.city_raw,
                        r.extra.get("verified_raw"),
                        None if r.extra.get("verified") is None else int(r.extra["verified"]),
                        r.extra.get("projects_completed"),
                    ),
                )

    for a in ANOMALIES:
        cur.execute(
            """INSERT INTO data_quality_issues
               (source_file, row_identifier, issue_type, detail, raw_row, logged_at)
               VALUES (?,?,?,?,?,?)""",
            (a["source_file"], a["row_identifier"], a["issue_type"], a["detail"], a["raw_row"], now),
        )

    conn.commit()
    conn.close()





# === AUDIO/WEB APP HELPERS ===
AUDIO_EXTENSIONS = {'.wav', '.mp3', '.m4a', '.aac', '.ogg', '.webm', '.flac'}
MAX_AUDIO_BYTES = 25 * 1024 * 1024

def ensure_audio_storage(db_path: Path) -> Path:
    audio_dir = db_path.parent / 'audio_uploads'
    audio_dir.mkdir(parents=True, exist_ok=True)
    return audio_dir

def find_user_for_audio(conn, name: str, phone: str):
    phone_norm, _ = normalize_phone(phone)
    if phone_norm:
        row = conn.execute('SELECT user_id FROM users WHERE primary_phone = ? LIMIT 1', (phone_norm,)).fetchone()
        if row:
            return row[0]
        row = conn.execute('SELECT user_id FROM user_phones WHERE phone = ? LIMIT 1', (phone_norm,)).fetchone()
        if row:
            return row[0]
    name_norm = normalize_name_for_match(name)
    if name_norm:
        for row in conn.execute('SELECT user_id, full_name FROM users').fetchall():
            if normalize_name_for_match(row[1]) == name_norm:
                return row[0]
    return None

def extract_audio_metadata(file_path: Path):
    """Extract duration, sample rate, bitrate and loudness; also provide a rough quality estimate.
    ffprobe/ffmpeg are used when installed. WAV files have a standard-library fallback.
    """
    metadata = {
        'duration_seconds': None,
        'sample_rate_hz': None,
        'bitrate_kbps': None,
        'loudness_db': None,
        'quality_estimate': 'unknown',
    }
    ffprobe = shutil.which('ffprobe')
    if ffprobe:
        try:
            result = subprocess.run(
                [ffprobe, '-v', 'error', '-show_entries', 'format=duration,bit_rate:stream=sample_rate,bit_rate', '-of', 'json', str(file_path)],
                capture_output=True, text=True, timeout=30, check=True,
            )
            data = json.loads(result.stdout or '{}')
            streams = data.get('streams') or []
            fmt = data.get('format') or {}
            audio_stream = next((s for s in streams if s.get('sample_rate')), streams[0] if streams else {})
            duration = fmt.get('duration')
            sample_rate = audio_stream.get('sample_rate')
            bitrate = audio_stream.get('bit_rate') or fmt.get('bit_rate')
            metadata['duration_seconds'] = round(float(duration), 3) if duration is not None else None
            metadata['sample_rate_hz'] = int(sample_rate) if sample_rate else None
            metadata['bitrate_kbps'] = round(float(bitrate) / 1000, 2) if bitrate else None
            sr = metadata['sample_rate_hz'] or 0
            br = metadata['bitrate_kbps'] or 0
            metadata['quality_estimate'] = 'good' if sr >= 44100 and br >= 96 else ('acceptable' if sr >= 16000 and br >= 32 else 'low')

            ffmpeg = shutil.which('ffmpeg')
            if ffmpeg:
                loud = subprocess.run(
                    [ffmpeg, '-hide_banner', '-i', str(file_path), '-filter_complex', 'ebur128=peak=true', '-f', 'null', '-'],
                    capture_output=True, text=True, timeout=90,
                )
                combined = (loud.stdout or '') + '\n' + (loud.stderr or '')
                values = re.findall(r'I:\s*(-?\d+(?:\.\d+)?)\s*LUFS', combined)
                if values:
                    metadata['loudness_db'] = round(float(values[-1]), 2)
            return metadata
        except (subprocess.SubprocessError, ValueError, json.JSONDecodeError, OSError) as exc:
            log.warning('Audio metadata extraction with ffprobe failed: %s', exc)

    if file_path.suffix.lower() == '.wav':
        try:
            import wave
            with wave.open(str(file_path), 'rb') as wav:
                frames = wav.getnframes()
                rate = wav.getframerate()
                width = wav.getsampwidth()
                channels = wav.getnchannels()
                duration = frames / rate if rate else None
                bitrate = rate * width * 8 * channels / 1000 if rate else None
                metadata['duration_seconds'] = round(duration, 3) if duration is not None else None
                metadata['sample_rate_hz'] = rate or None
                metadata['bitrate_kbps'] = round(bitrate, 2) if bitrate else None
                metadata['quality_estimate'] = 'good' if rate >= 44100 else ('acceptable' if rate >= 16000 else 'low')
        except (OSError, EOFError, ValueError) as exc:
            log.warning('WAV metadata extraction failed: %s', exc)
    return metadata

def export_n8n_flow(repo_dir: Path):
    """Export a real n8n-importable workflow template for the required no-code task."""
    flow = {
        'name': 'TalentGraph Duplicate Alert',
        'nodes': [
            {
                'parameters': {'httpMethod': 'POST', 'path': 'talentgraph-duplicate-check', 'responseMode': 'lastNode'},
                'id': '1', 'name': 'New Person Webhook', 'type': 'n8n-nodes-base.webhook', 'typeVersion': 2, 'position': [-700, 0]
            },
            {
                'parameters': {'jsCode': "const body = $json.body || $json; return [{json:{name:String(body.name||''),email:String(body.email||''),phone:String(body.phone||''),city:String(body.city||'')}}];"},
                'id': '2', 'name': 'Normalize Input', 'type': 'n8n-nodes-base.code', 'typeVersion': 2, 'position': [-460, 0]
            },
            {
                'parameters': {'operation': 'executeQuery', 'query': "SELECT user_id, full_name, primary_email, primary_phone, city FROM users WHERE lower(primary_email)=lower('{{ $json.email }}') OR primary_phone='{{ $json.phone }}' OR lower(full_name)=lower('{{ $json.name }}') LIMIT 20;"},
                'id': '3', 'name': 'Check TalentGraph SQLite', 'type': 'n8n-nodes-base.sqlite', 'typeVersion': 2, 'position': [-180, 0]
            },
            {
                'parameters': {'conditions': {'options': {'caseSensitive': False}, 'conditions': [{'leftValue': '={{ $items().length }}', 'rightValue': 0, 'operator': {'type': 'number', 'operation': 'gt'}}]}},
                'id': '4', 'name': 'Duplicate Found?', 'type': 'n8n-nodes-base.if', 'typeVersion': 2, 'position': [80, 0]
            },
            {
                'parameters': {'assignments': {'assignments': [{'id': '1', 'name': 'alert', 'value': "Duplicate candidate found in TalentGraph for {{$json.full_name || 'unknown person'}}", 'type': 'string'}]}},
                'id': '5', 'name': 'Duplicate Alert', 'type': 'n8n-nodes-base.set', 'typeVersion': 3.4, 'position': [320, -100]
            },
            {
                'parameters': {'respondWith': 'json', 'responseBody': "={{ {status:'duplicate', alert:$json.alert, user_id:$json.user_id} }}"},
                'id': '6', 'name': 'Return Duplicate', 'type': 'n8n-nodes-base.respondToWebhook', 'typeVersion': 1.1, 'position': [560, -100]
            },
            {
                'parameters': {'respondWith': 'json', 'responseBody': "={{ {status:'new_person', message:'No duplicate found'} }}"},
                'id': '7', 'name': 'Return New Person', 'type': 'n8n-nodes-base.respondToWebhook', 'typeVersion': 1.1, 'position': [320, 100]
            }
        ],
        'connections': {
            'New Person Webhook': {'main': [[{'node': 'Normalize Input', 'type': 'main', 'index': 0}]]},
            'Normalize Input': {'main': [[{'node': 'Check TalentGraph SQLite', 'type': 'main', 'index': 0}]]},
            'Check TalentGraph SQLite': {'main': [[{'node': 'Duplicate Found?', 'type': 'main', 'index': 0}]]},
            'Duplicate Found?': {'main': [[{'node': 'Duplicate Alert', 'type': 'main', 'index': 0}], [{'node': 'Return New Person', 'type': 'main', 'index': 0}]]},
            'Duplicate Alert': {'main': [[{'node': 'Return Duplicate', 'type': 'main', 'index': 0}]]}
        },
        'active': False,
        'settings': {'executionOrder': 'v1'},
        'pinData': {},
        'versionId': str(uuid.uuid4())
    }
    path = repo_dir / 'n8n_talentgraph_duplicate_alert.json'
    path.write_text(json.dumps(flow, indent=2), encoding='utf-8')
    return path

def write_submission_docs(repo_dir: Path):
    quality = repo_dir / 'DATA_QUALITY_REPORT.md'
    if not quality.exists():
        quality.write_text('''# TalentGraph Data Quality Report\n\nThis report documents the checks implemented by `merge_users.py`.\n\n## Issues checked and treatment\n\n| Issue | Detection | Treatment |\n|---|---|---|\n| Blank rows | Row contains no usable values | Skipped and logged |\n| Missing/malformed email | Email validation | Missing or invalid value logged; valid values normalized to lowercase |\n| Malformed phone | Phone digit/length validation | Valid Indian 10-digit numbers normalized; bad values logged |\n| Duplicate CBNexus header | Name column equals `Name` inside data | Row skipped and logged |\n| Corrupted Gig row | Email appears in the wrong column | Row is realigned using detectable email/status/rate/location fields and logged |\n| Unrecoverable Gig row | No email can be found | Row quarantined/skipped and logged |\n| Invalid CTC | Numeric conversion fails | Value kept as unavailable and issue logged |\n| Invalid date | Supported date formats fail | Original value retained and issue logged |\n| Invalid experience | Numeric conversion fails | Stored as unavailable and issue logged |\n| Invalid Gig status | Value is outside active/inactive/paused | Kept and issue logged |\n| Invalid CBNexus verification | Value outside yes/no forms | Stored as unknown and issue logged |\n| Invalid project count | Integer conversion fails | Stored as unavailable and issue logged |\n| Conflicting identifiers | Similar name + same city but different known identifiers | Not auto-merged; manual review flag created |\n| Fuzzy identity match | Similar normalized names + same city | Merged and logged as low-confidence fuzzy match |\n\nAll runtime issues are also written to the SQLite `data_quality_issues` table.\n\n> The exact row-level findings depend on the three source CSV files supplied to the script; run `python3 merge_users.py` to populate the table.\n''', encoding='utf-8')

    stretch = repo_dir / 'STRETCH.md'
    if not stretch.exists():
        stretch.write_text('''# Task 5 — 5,000 Worker Weekend Launch Plan\n\n## What breaks first\n\n1. Local audio disk/storage.\n2. Upload bandwidth and request timeouts.\n3. Synchronous metadata extraction under concurrency.\n4. Duplicate submissions caused by retries.\n5. SQLite write concurrency.\n6. Lack of retry handling and observability.\n\n## Changes before launch\n\n- Move audio from local disk to S3-compatible object storage.\n- Move production metadata from SQLite to managed PostgreSQL.\n- Use signed direct-to-storage uploads.\n- Put audio processing behind a queue and worker pool.\n- Add idempotency keys and file hashes to prevent duplicate submissions.\n- Enforce file size, duration and supported-format limits.\n- Add authentication and rate limiting.\n- Add retry/dead-letter handling for failed jobs.\n- Monitor upload errors, queue depth, storage, CPU and processing latency.\n- Add backups and lifecycle/retention policies.\n- Load-test with thousands of concurrent uploads before launch.\n\n## Cost\n\nStorage and bandwidth will be major variable costs, followed by metadata-processing compute. Object storage with lifecycle rules is preferable to keeping recordings on the application server.\n''', encoding='utf-8')
    return quality, stretch

DASHBOARD_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TalentGraph — SQL + Audio Dashboard</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;background:#f5f7fb;color:#172033}header{background:#172033;color:white;padding:28px 40px}h1{margin:0 0 6px}.sub{opacity:.8}main{max-width:1200px;margin:28px auto;padding:0 20px}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.card,.panel{background:white;border-radius:14px;padding:20px;box-shadow:0 3px 14px rgba(0,0,0,.07)}.number{font-size:30px;font-weight:700;margin-top:8px}.panel{margin-top:20px;overflow:auto}h2{margin-top:0}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:11px;border-bottom:1px solid #e8ebf0;font-size:14px}th{background:#f7f8fa}.badge{display:inline-block;padding:4px 8px;border-radius:8px;background:#eef2ff}.search{display:flex;gap:10px;margin-bottom:8px}.search input,.upload input{flex:1;padding:12px;border:1px solid #d9dee8;border-radius:9px;font-size:15px}.search button,.upload button{padding:12px 18px;border:0;border-radius:9px;background:#172033;color:#fff;cursor:pointer}.search-help{font-size:13px;color:#596273;margin:0 0 16px}.person-details{display:none}.detail-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}.detail-item{background:#f7f8fa;padding:12px;border-radius:10px}.detail-item strong{display:block;margin-bottom:5px;color:#596273}.source-box{margin-top:16px;padding:14px;background:#f7f8fa;border-radius:10px}.source-box h3{margin-top:0}.not-found{display:none;padding:12px;background:#fff1f1;border-radius:9px;color:#a22}.results-list{display:none;margin-top:16px}.result-card{background:#f7f8fa;border:1px solid #e4e7ec;border-radius:10px;padding:14px;margin-bottom:10px;cursor:pointer}.result-card:hover{border-color:#172033}.result-card strong{display:block;font-size:16px;margin-bottom:6px}.result-meta{font-size:13px;color:#596273;line-height:1.6}.result-button{margin-top:8px;padding:8px 12px;border:0;border-radius:7px;background:#172033;color:#fff;cursor:pointer}.upload{display:grid;grid-template-columns:1fr 1fr;gap:12px;align-items:end}.upload .full{grid-column:1/-1}.audio-player{min-width:220px}@media(max-width:800px){.cards,.upload{grid-template-columns:1fr}.detail-grid{grid-template-columns:1fr}}
</style></head><body>
<header><h1>TalentGraph SQL + Audio Dashboard</h1><div class="sub">Merged applicant, gig-worker and CBNexus data with audio collection</div></header><main>
<div class="cards"><div class="card">Unique Users<div class="number">{{USERS}}</div></div><div class="card">Source Records<div class="number">{{RECORDS}}</div></div><div class="card">Data Issues<div class="number">{{ISSUES}}</div></div><div class="card">Audio Submissions<div class="number">{{AUDIO_COUNT}}</div></div></div>
<div class="panel"><h2>Audio Collection</h2><p class="search-help">Enter the worker name and phone number, choose an audio recording, then submit it. The server stores the audio and extracts duration, sample rate, bitrate, loudness and a rough quality estimate.</p><form class="upload" action="/upload-audio" method="post" enctype="multipart/form-data"><label>Name<br><input name="name" required placeholder="Worker name"></label><label>Phone<br><input name="phone" required placeholder="Phone number"></label><label class="full">Audio file<br><input name="audio" type="file" accept="audio/*,.wav,.mp3,.m4a,.aac,.ogg,.webm,.flac" required></label><button class="full" type="submit">Submit Audio</button></form></div>
<div class="panel"><h2>Search a Person</h2><div class="search"><input id="personSearch" list="peopleList" type="text" placeholder="Search by name, city, email, phone, skill, or source..."><datalist id="peopleList">{{PERSON_OPTIONS}}</datalist><button onclick="searchPerson()">Search</button></div><p class="search-help">Search by any partial name, city, email, phone/contact number, skill, or source. A city search shows every matching person.</p><div id="notFound" class="not-found"></div><div id="matchNotice" class="search-help" style="display:none"></div><div id="resultsList" class="results-list"><h3>Matching People</h3><div id="resultsContainer"></div></div><div id="personDetails" class="person-details"><h2 id="detailName"></h2><div class="detail-grid"><div class="detail-item"><strong>Email</strong><span id="detailEmail"></span></div><div class="detail-item"><strong>Phone</strong><span id="detailPhone"></span></div><div class="detail-item"><strong>City</strong><span id="detailCity"></span></div><div class="detail-item"><strong>Sources</strong><span id="detailSources"></span></div><div class="detail-item"><strong>Match Confidence</strong><span id="detailMatch"></span></div><div class="detail-item"><strong>Source Count</strong><span id="detailSourceCount"></span></div></div><div class="source-box"><h3>Naukri Details</h3><div id="naukriDetails">No Naukri record</div></div><div class="source-box"><h3>Gig Worker Details</h3><div id="gigDetails">No Gig Worker record</div></div><div class="source-box"><h3>CBNexus Details</h3><div id="cbDetails">No CBNexus record</div></div><div class="source-box"><h3>Skills</h3><div id="skillsDetails">No skills recorded</div></div></div></div>
<div class="panel"><h2>Audio Submissions</h2><table><thead><tr><th>Worker</th><th>Phone</th><th>Duration</th><th>Sample Rate</th><th>Bitrate</th><th>Loudness</th><th>Quality</th><th>Submitted</th><th>Play</th></tr></thead><tbody>{{AUDIO_ROWS}}</tbody></table></div>
<div class="panel"><h2>People in SQL Database</h2><table><thead><tr><th>ID</th><th>Name</th><th>Email</th><th>Phone</th><th>City</th><th>Sources</th><th>Match</th></tr></thead><tbody>{{ROWS}}</tbody></table></div>
<script>
const people={{PEOPLE_JSON}};
function showPersonDetails(person){document.getElementById('notFound').style.display='none';document.getElementById('resultsList').style.display='none';document.getElementById('personDetails').style.display='block';document.getElementById('detailName').textContent=person.name;document.getElementById('detailEmail').textContent=person.email||'—';document.getElementById('detailPhone').textContent=person.phone||'—';document.getElementById('detailCity').textContent=person.city||'—';document.getElementById('detailSources').textContent=person.sources||'—';document.getElementById('detailMatch').textContent=person.match||'—';document.getElementById('detailSourceCount').textContent=person.source_count??'—';document.getElementById('naukriDetails').innerHTML=person.naukri||'No Naukri record';document.getElementById('gigDetails').innerHTML=person.gig||'No Gig Worker record';document.getElementById('cbDetails').innerHTML=person.cb||'No CBNexus record';document.getElementById('skillsDetails').textContent=person.skills||'No skills recorded'}
function esc(v){return String(v??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#039;')}
function searchPerson(){const q=document.getElementById('personSearch').value.trim().toLowerCase(),err=document.getElementById('notFound'),list=document.getElementById('resultsList'),box=document.getElementById('resultsContainer'),notice=document.getElementById('matchNotice');document.getElementById('personDetails').style.display='none';err.style.display='none';list.style.display='none';notice.style.display='none';box.innerHTML='';if(!q){err.textContent='Please enter a search value.';err.style.display='block';return}const matches=people.filter(p=>[p.name,p.email,p.phone,p.city,p.sources,p.match,p.skills,p.naukri_text,p.gig_text,p.cb_text].filter(Boolean).join(' ').toLowerCase().includes(q));if(!matches.length){err.textContent='No person found for "'+document.getElementById('personSearch').value+'".';err.style.display='block';return}if(matches.length===1){showPersonDetails(matches[0]);return}list.style.display='block';notice.style.display='block';notice.textContent=matches.length+' people matched this search. Select a person to see full details.';box.innerHTML=matches.map(p=>{const i=people.indexOf(p);return '<div class="result-card" onclick="showPersonDetails(people['+i+'])"><strong>'+esc(p.name||'Unnamed')+'</strong><div class="result-meta">Email: '+esc(p.email||'—')+'<br>Phone: '+esc(p.phone||'—')+'<br>City: '+esc(p.city||'—')+'<br>Sources: '+esc(p.sources||'—')+'<br>Skills: '+esc(p.skills||'—')+'</div><button class="result-button" onclick="event.stopPropagation();showPersonDetails(people['+i+'])">View Full Details</button></div>'}).join('')}
document.getElementById('personSearch').addEventListener('keydown',e=>{if(e.key==='Enter')searchPerson()});
</script></main></body></html>"""



def create_dashboard(db_path: Path):
    """Start the local TalentGraph dashboard, including person search and audio collection."""
    audio_dir = ensure_audio_storage(db_path).resolve()

    class DashboardHandler(http.server.BaseHTTPRequestHandler):
        def send_text(self, status, text):
            body = text.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.startswith('/audio/'):
                filename = self.path.split('/audio/', 1)[1].split('?', 1)[0]
                candidate = (audio_dir / Path(filename).name).resolve()
                if candidate.parent != audio_dir or not candidate.is_file():
                    self.send_error(404, 'Audio file not found')
                    return
                mime = mimetypes.guess_type(candidate.name)[0] or 'application/octet-stream'
                data = candidate.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Content-Disposition', 'inline')
                self.end_headers()
                self.wfile.write(data)
                return

            if self.path not in ('/', '/index.html'):
                self.send_error(404)
                return

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            users = cur.execute('SELECT * FROM users ORDER BY user_id').fetchall()
            issues = cur.execute('SELECT COUNT(*) FROM data_quality_issues').fetchone()[0]
            naukri_count = cur.execute('SELECT COUNT(*) FROM naukri_applications').fetchone()[0]
            gig_count = cur.execute('SELECT COUNT(*) FROM gig_worker_profiles').fetchone()[0]
            cb_count = cur.execute('SELECT COUNT(*) FROM cbnexus_contacts').fetchone()[0]
            matched = cur.execute('SELECT COUNT(*) FROM users WHERE source_count > 1').fetchone()[0]
            audio_rows_db = cur.execute('SELECT * FROM audio_submissions ORDER BY id DESC').fetchall()
            naukri_rows = cur.execute('SELECT * FROM naukri_applications ORDER BY id').fetchall()
            gig_rows = cur.execute('SELECT * FROM gig_worker_profiles ORDER BY id').fetchall()
            cb_rows = cur.execute('SELECT * FROM cbnexus_contacts ORDER BY id').fetchall()
            skill_rows = cur.execute('SELECT user_id, skill, source FROM user_skills ORDER BY id').fetchall()

            by_user_naukri = {}
            for r in naukri_rows: by_user_naukri.setdefault(r['user_id'], []).append(r)
            by_user_gig = {}
            for r in gig_rows: by_user_gig.setdefault(r['user_id'], []).append(r)
            by_user_cb = {}
            for r in cb_rows: by_user_cb.setdefault(r['user_id'], []).append(r)
            by_user_skills = {}
            for r in skill_rows: by_user_skills.setdefault(r['user_id'], []).append(r)

            def format_naukri(uid):
                items = by_user_naukri.get(uid, [])
                return '<br>'.join('Name: {}<br>Email: {}<br>Phone: {}<br>City: {}<br>Experience: {} years<br>CTC: {}<br>Applied: {}<br>Skills: {}'.format(html.escape(str(r['name_raw'] or '—')), html.escape(str(r['email_raw'] or '—')), html.escape(str(r['phone_raw'] or '—')), html.escape(str(r['city_raw'] or '—')), html.escape(str(r['experience_years'] if r['experience_years'] is not None else '—')), html.escape(str(r['current_ctc_raw'] if r['current_ctc_raw'] is not None else '—')), html.escape(str(r['applied_date_parsed'] or r['applied_date_raw'] or '—')), html.escape(str(r['skills_raw'] or '—'))) for r in items)
            def format_gig(uid):
                items = by_user_gig.get(uid, [])
                return '<br>'.join('Name: {}<br>Email: {}<br>City: {}<br>Rate: {}<br>Monthly Equivalent: {}<br>Status: {}<br>Skills: {}'.format(html.escape(str(r['name_raw'] or '—')), html.escape(str(r['email_raw'] or '—')), html.escape(str(r['city_raw'] or '—')), html.escape(str(r['rate_raw'] or '—')), html.escape(str(r['rate_normalized_monthly_inr'] if r['rate_normalized_monthly_inr'] is not None else '—')), html.escape(str(r['status'] or '—')), html.escape(str(r['skill_tags_raw'] or '—'))) for r in items)
            def format_cb(uid):
                items = by_user_cb.get(uid, [])
                return '<br>'.join('Name: {}<br>Phone: {}<br>City: {}<br>Verified: {}<br>Projects Completed: {}'.format(html.escape(str(r['name_raw'] or '—')), html.escape(str(r['phone_raw'] or '—')), html.escape(str(r['city_raw'] or '—')), html.escape(str(r['verified_raw'] or '—')), html.escape(str(r['projects_completed'] if r['projects_completed'] is not None else '—'))) for r in items)
            def format_skills(uid):
                values=[]
                for r in by_user_skills.get(uid, []):
                    value=f"{r['skill']} ({r['source']})"
                    if value not in values: values.append(value)
                return ', '.join(values)

            people=[]
            for u in users:
                people.append({'id':u['user_id'],'name':u['full_name'] or 'Unnamed','email':u['primary_email'] or '','phone':u['primary_phone'] or '','city':u['city'] or '','sources':u['matched_sources'] or '','match':u['match_confidence'] or '','source_count':u['source_count'],'naukri':format_naukri(u['user_id']),'gig':format_gig(u['user_id']),'cb':format_cb(u['user_id']),'skills':format_skills(u['user_id']),'naukri_text':' '.join(str(v or '') for row in by_user_naukri.get(u['user_id'],[]) for v in row),'gig_text':' '.join(str(v or '') for row in by_user_gig.get(u['user_id'],[]) for v in row),'cb_text':' '.join(str(v or '') for row in by_user_cb.get(u['user_id'],[]) for v in row)})

            rows=''.join('<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td><span class="badge">{}</span></td><td>{}</td></tr>'.format(u['user_id'],html.escape(str(u['full_name'] or '—')),html.escape(str(u['primary_email'] or '—')),html.escape(str(u['primary_phone'] or '—')),html.escape(str(u['city'] or '—')),html.escape(str(u['matched_sources'] or '—')),html.escape(str(u['match_confidence'] or '—'))) for u in users)
            person_options=''.join('<option value="{}"></option>'.format(html.escape(str(p['name']), quote=True)) for p in people)
            audio_html=[]
            for a in audio_rows_db:
                duration=f"{a['duration_seconds']:.2f} sec" if a['duration_seconds'] is not None else '—'
                rate=f"{a['sample_rate_hz']/1000:.1f} kHz" if a['sample_rate_hz'] else '—'
                bitrate=f"{a['bitrate_kbps']:.2f} kbps" if a['bitrate_kbps'] is not None else '—'
                loud=f"{a['loudness_db']:.2f} dB/LUFS" if a['loudness_db'] is not None else '—'
                submitted=html.escape(str(a['submitted_at'] or '—'))
                filename=html.escape(str(a['stored_filename']), quote=True)
                audio_html.append('<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td><span class="badge">{}</span></td><td>{}</td><td><audio class="audio-player" controls preload="none" src="/audio/{}"></audio></td></tr>'.format(html.escape(str(a['name'])),html.escape(str(a['phone'])),duration,rate,bitrate,loud,html.escape(str(a['quality_estimate'] or 'unknown')),submitted,filename))
            people_json=json.dumps(people,ensure_ascii=False).replace('</','<\\/')
            page=DASHBOARD_HTML.replace('{{USERS}}',str(len(users))).replace('{{RECORDS}}',str(naukri_count+gig_count+cb_count)).replace('{{ISSUES}}',str(issues)).replace('{{MATCHED}}',str(matched)).replace('{{AUDIO_COUNT}}',str(len(audio_rows_db))).replace('{{AUDIO_ROWS}}',''.join(audio_html) or '<tr><td colspan="9">No audio submissions yet.</td></tr>').replace('{{ROWS}}',rows).replace('{{PERSON_OPTIONS}}',person_options).replace('{{PEOPLE_JSON}}',people_json)
            conn.close()
            body=page.encode('utf-8')
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)

        def do_POST(self):
            if self.path != '/upload-audio': self.send_error(404); return
            try:
                import cgi
                content_length=int(self.headers.get('Content-Length','0'))
                if content_length<=0 or content_length>MAX_AUDIO_BYTES+1024*1024:
                    self.send_text(400,'Invalid or oversized upload.')
                    return
                form=cgi.FieldStorage(fp=self.rfile,headers=self.headers,environ={'REQUEST_METHOD':'POST','CONTENT_TYPE':self.headers.get('Content-Type',''),'CONTENT_LENGTH':str(content_length)},keep_blank_values=True)
                name=clean_str(form.getfirst('name'))
                phone=clean_str(form.getfirst('phone'))
                audio=form['audio'] if 'audio' in form else None
                if not name or not phone or not audio or not getattr(audio,'filename',None): self.send_text(400,'Name, phone and audio are required.'); return
                original=Path(audio.filename).name
                ext=Path(original).suffix.lower()
                if ext not in AUDIO_EXTENSIONS: self.send_text(400,'Unsupported audio format. Use WAV, MP3, M4A, AAC, OGG, WEBM or FLAC.'); return
                data=audio.file.read(MAX_AUDIO_BYTES+1)
                if len(data)>MAX_AUDIO_BYTES: self.send_text(400,'Audio file exceeds the 25 MB limit.'); return
                stored=f"{uuid.uuid4().hex}_{original}"
                destination=audio_dir/stored
                destination.write_bytes(data)
                metadata=extract_audio_metadata(destination)
                conn=sqlite3.connect(db_path)
                user_id=find_user_for_audio(conn,name,phone)
                conn.execute('INSERT INTO audio_submissions (user_id,name,phone,original_filename,stored_filename,file_path,duration_seconds,sample_rate_hz,bitrate_kbps,loudness_db,quality_estimate,file_size_bytes,submitted_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',(user_id,name,phone,original,stored,str(destination),metadata['duration_seconds'],metadata['sample_rate_hz'],metadata['bitrate_kbps'],metadata['loudness_db'],metadata['quality_estimate'],len(data),datetime.now(timezone.utc).isoformat()))
                conn.commit(); conn.close()
                self.send_response(303); self.send_header('Location','/'); self.end_headers()
            except Exception as exc:
                log.exception('Audio upload failed')
                self.send_text(500,f'Audio upload failed: {exc}')

        def log_message(self, format, *args): return

    class ReusableTCPServer(socketserver.TCPServer): allow_reuse_address=True
    server=None
    for port_candidate in [8765,*range(8766,8776)]:
        try: server=ReusableTCPServer(('127.0.0.1',port_candidate),DashboardHandler); port=port_candidate; break
        except OSError: continue
    if server is None: raise RuntimeError('Could not find an available local dashboard port (8765-8775).')
    url=f'http://127.0.0.1:{port}'
    log.info('Dashboard running at %s',url); webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: log.info('Stopping dashboard...')
    finally: server.server_close()
def write_submission_docs(repo_dir: Path):
    quality = repo_dir / 'DATA_QUALITY_REPORT.md'
    quality.write_text('''# TalentGraph Data Quality Report\n\n`merge_users.py` checks all three source files and records runtime findings in the SQLite `data_quality_issues` table.\n\n## Checks and treatment\n\n| Problem | Detection | Action |\n|---|---|---|\n| Blank row | All fields empty | Skip and log |\n| Missing/malformed email | Email format validation | Normalize valid emails; log invalid/missing values |\n| Malformed phone | Digit/length validation | Normalize valid Indian numbers; log invalid values |\n| Repeated CBNexus header | Name equals `Name` in a data row | Skip and log |\n| Corrupted Gig row | Email appears in an unexpected column | Recover fields by pattern and log |\n| Unrecoverable Gig row | No email can be detected | Quarantine/skip and log |\n| Invalid CTC | Numeric conversion fails | Store unavailable value and log |\n| Invalid date | Supported date formats fail | Preserve raw value and log |\n| Invalid experience | Numeric conversion fails | Store unavailable value and log |\n| Invalid Gig status | Not active/inactive/paused | Preserve value and log |\n| Invalid verification flag | Not yes/no/y/n | Store unknown and log |\n| Invalid project count | Integer conversion fails | Store unavailable and log |\n| Conflicting identifiers | Similar name + same city but different known identifiers | Do not auto-merge; flag for review |\n| Fuzzy match | Similar normalized name + same city | Merge and log as fuzzy/low confidence |\n\n## Exact findings\n\nThe exact row numbers and values are generated from the supplied CSVs each time the pipeline runs and are available in the `data_quality_issues` table and dashboard count.\n''',encoding='utf-8')
    (repo_dir/'STRETCH.md').write_text('''# Task 5 — 5,000 Worker Weekend Launch Plan\n\n## What breaks first\n\n1. Local audio storage.\n2. Upload bandwidth and request timeouts.\n3. Synchronous metadata extraction under concurrency.\n4. Duplicate submissions after retries.\n5. SQLite concurrent writes.\n6. Missing monitoring and failure recovery.\n\n## Before launch\n\n- Move audio to S3-compatible object storage.\n- Move production metadata to managed PostgreSQL.\n- Use signed direct uploads.\n- Process metadata asynchronously with a queue and worker pool.\n- Add idempotency keys and file hashes.\n- Enforce file size, duration and format limits.\n- Add authentication and rate limiting.\n- Add retries and a dead-letter state.\n- Monitor errors, queue depth, storage, CPU and processing latency.\n- Back up the database and define storage retention.\n- Load-test thousands of concurrent uploads before launch.\n\n## Cost\n\nStorage and bandwidth are major variable costs, followed by metadata-processing compute. Object storage with lifecycle policies is preferable to local server disk.\n''',encoding='utf-8')
    return quality, repo_dir/'STRETCH.md'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--naukri", default=Path("data/source1_naukri_applicants.csv"), type=Path)
    ap.add_argument("--gig", default=Path("data/source2_gig_workers.csv"), type=Path)
    ap.add_argument("--cbnexus", default=Path("data/source3_cbnexus_contacts.csv"), type=Path)
    ap.add_argument("--db", default=Path("db/users.db"), type=Path)
    args = ap.parse_args()

    
    base_dir = Path(__file__).resolve().parent
    for attr in ("naukri", "gig", "cbnexus"):
        path = getattr(args, attr)
        if not path.is_absolute():
            setattr(args, attr, base_dir / path)
    if not args.db.is_absolute():
        args.db = base_dir / args.db

    missing = [str(p) for p in (args.naukri, args.gig, args.cbnexus) if not p.is_file()]
    if missing:
        ap.error(
            "Input CSV file(s) not found: " + ", ".join(missing) +
            ". Put the three CSV files inside the project's data/ folder, "
            "or run the script with --naukri, --gig and --cbnexus paths."
        )

    log.info("Reading %s (naukri applicants)...", args.naukri)
    naukri = ingest_naukri(args.naukri)
    log.info("Reading %s (gig workers)...", args.gig)
    gig = ingest_gig(args.gig)
    log.info("Reading %s (cbnexus contacts)...", args.cbnexus)
    cbnexus = ingest_cbnexus(args.cbnexus)

    all_records = naukri + gig + cbnexus
    log.info("Total raw records ingested: %d (naukri=%d, gig=%d, cbnexus=%d)",
              len(all_records), len(naukri), len(gig), len(cbnexus))

    log.info("Resolving identities across sources...")
    groups = resolve_identities(all_records)
    log.info("Resolved %d raw records into %d unique users", len(all_records), len(groups))

    merged = sum(1 for g in groups if len(g) > 1)
    log.info("%d users were confirmed present in more than one source record", merged)

    log.info("Writing database to %s...", args.db)
    build_database(args.db, groups, all_records)

    log.info("Done. %d data-quality anomalies logged (see data_quality_issues table).",
              len(ANOMALIES))
    db_path = args.db.resolve()
    log.info("Database created at: %s", db_path)

    try:
        flow_path = export_n8n_flow(base_dir)
        quality_path, stretch_path = write_submission_docs(base_dir)
        log.info("n8n workflow exported to: %s", flow_path)
        log.info("Data-quality report written to: %s", quality_path)
        log.info("Stretch plan written to: %s", stretch_path)
    except OSError as exc:
        log.warning("Could not write submission support files: %s", exc)

    log.info("Opening dashboard in your browser...")
    create_dashboard(db_path)


if __name__ == "__main__":
    sys.exit(main())

