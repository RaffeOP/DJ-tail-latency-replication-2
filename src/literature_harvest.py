"""
src/literature_harvest.py

PRISMA-2020 style harvest of peer-reviewed work from 2024 onward. Queries the
Crossref works index, removes duplicate DOIs, screens by publisher and by
topic, and writes the records and the flow counts.

Outputs:
    literature/prisma/harvested_records.csv   every record returned
    literature/prisma/screened_records.csv    records that pass screening
    literature/prisma/flow.json               counts for the PRISMA flow

No contact address is sent to the API. Requests identify the project only.
"""

import csv
import json
import re
import subprocess
import time
import urllib.parse
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
OUT_DIR = WORKSPACE / "literature" / "prisma"
CROSSREF_URL = "https://api.crossref.org/works"
USER_AGENT = "R2-allocator-study/1.0 (literature harvest; no contact)"
ROWS_PER_PAGE = 100
PAGES_PER_QUERY = 3
REQUEST_PAUSE_SECONDS = 1.0
FROM_DATE = "2024-01-01"
QUERIES = [
    "memory allocator",
    "malloc implementation performance",
    "heap allocator multithreaded",
    "remote free producer consumer allocation",
    "false sharing cache line",
    "cache coherence atomic contention",
    "TLB shootdown",
    "page reclamation madvise memory footprint",
    "allocator fragmentation",
    "tail latency memory allocation",
    "garbage collection allocation tail latency",
    "universal scalability law",
    "extreme value theory latency tail",
]
PEER_REVIEWED_PUBLISHER = re.compile(
    r"IEEE|Institute of Electrical|ACM|Association for Computing|USENIX|Springer", re.IGNORECASE)
TOPIC_TERMS = re.compile(
    r"allocat|malloc|memory management|false sharing|cache coheren|TLB|shootdown|madvise|"
    r"memory fragmentation|page reclaim|heap|tail latency", re.IGNORECASE)
CORE_TITLE_TERMS = re.compile(
    r"(?<!resource )allocator|malloc|shootdown|false sharing|cache coheren|madvise|page recycl|mmap|far memory|"
    r"memory management|memory fragmentation|reclaim", re.IGNORECASE)
ADJACENT_TITLE_TERMS = re.compile(r"TLB|heap|page table|translation|memory tiering", re.IGNORECASE)
RECORD_FIELDS = ["doi", "title", "venue", "publisher", "year", "type", "query", "passes_publisher",
                 "passes_topic", "title_relevance", "abstract"]
ABSTRACT_CHARS = 1200


def fetch_page(query: str, cursor: str) -> dict:
    params = {
        "query": query,
        "filter": f"from-pub-date:{FROM_DATE}",
        "rows": str(ROWS_PER_PAGE),
        "cursor": cursor,
        "select": "DOI,title,container-title,publisher,published,type,abstract",
    }
    url = f"{CROSSREF_URL}?{urllib.parse.urlencode(params)}"
    result = subprocess.run(["curl", "-sS", "--fail", "-m", "60", "-A", USER_AGENT, url],
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def first_text(value) -> str:
    if isinstance(value, list):
        return value[0] if value else ""
    return value or ""


def year_of(item: dict) -> str:
    parts = item.get("published", {}).get("date-parts", [[None]])
    return str(parts[0][0]) if parts and parts[0] and parts[0][0] else ""


def title_relevance(title: str) -> str:
    if CORE_TITLE_TERMS.search(title):
        return "core"
    if ADJACENT_TITLE_TERMS.search(title):
        return "adjacent"
    return "off-topic"


def to_record(item: dict, query: str) -> dict:
    title = re.sub(r"<[^>]+>", " ", first_text(item.get("title")))
    abstract = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", item.get("abstract", "") or "")).strip()
    publisher = item.get("publisher", "") or ""
    return {
        "doi": item.get("DOI", ""),
        "title": title,
        "venue": first_text(item.get("container-title")),
        "publisher": publisher,
        "year": year_of(item),
        "type": item.get("type", ""),
        "query": query,
        "passes_publisher": bool(PEER_REVIEWED_PUBLISHER.search(publisher)),
        "passes_topic": bool(TOPIC_TERMS.search(f"{title} {abstract}")),
        "title_relevance": title_relevance(title),
        "abstract": abstract[:ABSTRACT_CHARS],
    }


def harvest() -> tuple:
    records = {}
    raw_count = 0
    per_query = {}
    for query in QUERIES:
        cursor = "*"
        returned = 0
        for _ in range(PAGES_PER_QUERY):
            page = fetch_page(query, cursor)["message"]
            items = page.get("items", [])
            raw_count += len(items)
            returned += len(items)
            for item in items:
                record = to_record(item, query)
                if record["doi"] and record["doi"] not in records:
                    records[record["doi"]] = record
            cursor = page.get("next-cursor", "")
            if not items or not cursor:
                break
            time.sleep(REQUEST_PAUSE_SECONDS)
        per_query[query] = returned
        time.sleep(REQUEST_PAUSE_SECONDS)
    return list(records.values()), raw_count, per_query


def write_csv(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RECORD_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    unique, raw_count, per_query = harvest()
    screened = [r for r in unique if r["passes_publisher"] and r["passes_topic"]]
    core = [r for r in screened if r["title_relevance"] == "core"]
    flow = {
        "queries": len(QUERIES),
        "from_date": FROM_DATE,
        "records_returned": raw_count,
        "records_after_doi_deduplication": len(unique),
        "records_excluded_non_peer_reviewed_publisher": sum(1 for r in unique if not r["passes_publisher"]),
        "records_excluded_off_topic": sum(1 for r in unique if r["passes_publisher"] and not r["passes_topic"]),
        "records_passing_publisher_and_topic_screen": len(screened),
        "records_core_title_relevance": len(core),
        "records_adjacent_title_relevance": sum(1 for r in screened if r["title_relevance"] == "adjacent"),
        "records_off_topic_after_title_check": sum(1 for r in screened if r["title_relevance"] == "off-topic"),
        "returned_per_query": per_query,
    }
    write_csv(OUT_DIR / "harvested_records.csv", unique)
    write_csv(OUT_DIR / "screened_records.csv", screened)
    (OUT_DIR / "flow.json").write_text(json.dumps(flow, indent=2) + "\n")
    print(json.dumps({k: v for k, v in flow.items() if k != "returned_per_query"}, indent=2))
    print("core titles:")
    for record in core:
        print(f"  {record['year']} {record['doi']} | {record['venue'][:45]} | {record['title'][:90]}")


if __name__ == "__main__":
    main()
