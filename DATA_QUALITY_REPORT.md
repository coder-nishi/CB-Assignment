# TalentGraph Data Quality Report

`merge_users.py` checks all three source files and records runtime findings in the SQLite `data_quality_issues` table.

## Checks and treatment

| Problem | Detection | Action |
|---|---|---|
| Blank row | All fields empty | Skip and log |
| Missing/malformed email | Email format validation | Normalize valid emails; log invalid/missing values |
| Malformed phone | Digit/length validation | Normalize valid Indian numbers; log invalid values |
| Repeated CBNexus header | Name equals `Name` in a data row | Skip and log |
| Corrupted Gig row | Email appears in an unexpected column | Recover fields by pattern and log |
| Unrecoverable Gig row | No email can be detected | Quarantine/skip and log |
| Invalid CTC | Numeric conversion fails | Store unavailable value and log |
| Invalid date | Supported date formats fail | Preserve raw value and log |
| Invalid experience | Numeric conversion fails | Store unavailable value and log |
| Invalid Gig status | Not active/inactive/paused | Preserve value and log |
| Invalid verification flag | Not yes/no/y/n | Store unknown and log |
| Invalid project count | Integer conversion fails | Store unavailable and log |
| Conflicting identifiers | Similar name + same city but different known identifiers | Do not auto-merge; flag for review |
| Fuzzy match | Similar normalized name + same city | Merge and log as fuzzy/low confidence |

## Exact findings

The exact row numbers and values are generated from the supplied CSVs each time the pipeline runs and are available in the `data_quality_issues` table and dashboard count.
