"""Build the retrieval corpus. Three sources, no scraping, no synthetic prose.

    doc         docs/*.md, verbatim. Real prose about real decisions.
    area_sheet  one deterministically rendered fact sheet per area.
    note        area_notes, authored by a human through the API.

Writes JSON Lines. Chunking, embedding and upsert are index_corpus.py's job -- keeping
them separate means the corpus can be inspected, diffed and committed to a fixture
without a model being involved.

## Why fact sheets are not "RAG over the database"

The sheets exist to make an area FINDABLE by a vague question -- "somewhere waterfront
with strong rental demand" matches no column in any table. They are a semantic view: a
stable, templated text surface over aggregates the platform already computes.

They are not the answer to a numeric question, and the agent layer (m15) does not treat
them as one. When the user asks for a figure, the SQL tool runs and that figure is
quoted. The numbers inside a sheet exist to ground and to cite, and each sheet carries
the row counts and the timestamp it was built from, so staleness is detectable instead
of assumed.

## Two data traps this file has to respect

1. **Rent contracts are a snapshot, not a time series.** Every contract in the DLD
   portal export was REGISTERED inside one window. The spread of contract_start_date
   makes it look historical and it is not -- plotting it produces a fake 20x hockey
   stick. The sheets therefore state a registration window and never a rent trend.
   (Same finding as models/area.py: rents_are_historical=False.)

2. **`annual_amount` is the CONTRACT total, not the per-property rent.** One contract
   can cover hundreds of properties, each carrying the full portfolio amount on its own
   row. Median rent divides by `no_of_prop`; using the raw column produces gross yields
   above 200%.

Usage:
    python build_corpus.py --docs /app/docs --out /app/corpus/corpus.jsonl
"""

import argparse
import json
import os
import sys
from fnmatch import fnmatch
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://dubai_user:dubai_pass@localhost:5432/dubai_re",
)

# An area with fewer than this many combined records produces a sheet that is mostly
# nulls -- "1 recorded sale, no median" retrieves for everything and grounds nothing.
MIN_RECORDS_FOR_SHEET = 10

# Never index these, whatever --docs points at.
#
# The real protection is the directory layout: the golden retrieval set lives in `eval/`
# and this script globs `--docs`, which is `docs/`. Nothing has to be remembered.
#
# This list is the second line, for the day someone runs `--docs .` to "index everything"
# and quietly re-poisons the evaluation. It cost one measurement to learn that a document
# containing the eval questions beats every document that answers them: the lexical arm
# returned that one file for 8 of 10 questions, and hybrid -- the shipped default -- came
# out worse than dense alone on 5 of 10.
#
# It is a deny-list of EVALUATION MATERIAL, not of self-referential prose. The design
# documents describing this retrieval layer stay in the corpus on purpose; answering
# "how does this platform deduplicate rent contracts?" is what the docs corpus is for,
# and removing them to protect a metric would delete the feature to save the number.
DENY_GLOBS = (
    "*golden*",       # any golden/eval fixture rendered as markdown
    "*GOLDEN*",
    "eval/*",         # if --docs is ever pointed at a repository root
    ".pr-bodies/*",   # PR prose: unreviewed, duplicated, and not documentation
    "market-intelligence-agent/*",  # planning directory, not shipped documentation
)


# ── SQL ─────────────────────────────────────────────────────────────────────
#
# One pass per fact family, grouped by normalised area name. 221 separate queries would
# be the obvious shape and is 221 round trips; these four are the whole corpus.
#
# Names are normalised with UPPER(TRIM(...)) before grouping for the same reason
# routers/areas.py does it: the DLD export is not internally consistent about case, and
# `Mushrif` exists under two different area_ids.

SALES_SQL = """
    SELECT UPPER(TRIM(area_name_en))                     AS norm,
           MIN(area_name_en)                             AS area_name_en,
           COUNT(*)                                      AS tx_count,
           MIN(EXTRACT(YEAR FROM instance_date))::int    AS first_year,
           MAX(EXTRACT(YEAR FROM instance_date))::int    AS last_year,
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY actual_worth)
               FILTER (WHERE actual_worth > 0)           AS median_price,
           COUNT(*) FILTER (WHERE reg_type_en ILIKE '%off%plan%')  AS offplan,
           COUNT(*) FILTER (WHERE reg_type_en ILIKE '%existing%')   AS existing,
           MODE() WITHIN GROUP (ORDER BY property_usage_en)  AS dominant_usage,
           MODE() WITHIN GROUP (ORDER BY property_type_en)   AS dominant_type
      FROM raw_transactions
     WHERE area_name_en IS NOT NULL
     GROUP BY 1
"""

# Median AED per m2 per year. Two years per area are used (latest and the one before)
# so the sheet can state a year-on-year move rather than a level with no context.
YEAR_MEDIAN_SQL = """
    SELECT norm, yr, med_sqm, cnt FROM (
        SELECT UPPER(TRIM(area_name_en))                  AS norm,
               EXTRACT(YEAR FROM instance_date)::int      AS yr,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY meter_sale_price) AS med_sqm,
               COUNT(*)                                   AS cnt,
               ROW_NUMBER() OVER (
                   PARTITION BY UPPER(TRIM(area_name_en))
                   -- must match the GROUP BY expression exactly, cast included:
                   -- the window runs after grouping, so an uncast EXTRACT here is
                   -- read as a bare reference to an ungrouped column.
                   ORDER BY EXTRACT(YEAR FROM instance_date)::int DESC
               ) AS rn
          FROM raw_transactions
         WHERE area_name_en IS NOT NULL
           AND instance_date IS NOT NULL
           AND meter_sale_price > 0
         GROUP BY 1, 2
    ) t
    WHERE rn <= 2
    ORDER BY norm, yr DESC
"""

# no_of_prop guard: COALESCE to 1 and GREATEST to 1 so a null or a zero cannot turn a
# portfolio contract into a division error or an absurd per-property rent.
RENTS_SQL = """
    SELECT UPPER(TRIM(area_name_en))                      AS norm,
           MIN(area_name_en)                              AS area_name_en,
           COUNT(*)                                       AS rent_count,
           PERCENTILE_CONT(0.5) WITHIN GROUP (
               ORDER BY annual_amount / GREATEST(COALESCE(no_of_prop, 1), 1)
           ) FILTER (WHERE annual_amount > 0)              AS median_annual_rent,
           MIN(load_timestamp)::date                       AS registered_from,
           MAX(load_timestamp)::date                       AS registered_to,
           MODE() WITHIN GROUP (ORDER BY ejari_property_type_en) AS dominant_type
      FROM raw_rent_contracts
     WHERE area_name_en IS NOT NULL
     GROUP BY 1
"""

# Adjacency from the real polygons, not from a name list. ST_Touches over the GiST
# index; the same relation the /communities/{name}/adjacent endpoint serves.
NEIGHBOURS_SQL = """
    SELECT a.community_name_norm AS norm,
           ARRAY_AGG(b.community_name_en ORDER BY b.community_name_en) AS neighbours
      FROM communities a
      JOIN communities b
        ON a.id <> b.id
       AND ST_Touches(a.geom, b.geom)
     GROUP BY 1
"""

# The column is `area_name`, not `area_name_en` -- area_notes is the ORM-managed table
# from alembic 0001, not one of the DLD raw tables. Tags are folded in because they are
# short identity strings ('off-plan', 'yield-watch') and therefore exactly what the
# lexical arm of retrieval is good at and the dense arm is not.
NOTES_SQL = """
    SELECT n.id, n.area_name, n.title, n.body, n.updated_at,
           COALESCE(
               (SELECT STRING_AGG(t.label, ', ' ORDER BY t.label)
                  FROM note_tags t WHERE t.note_id = n.id),
               ''
           ) AS tags
      FROM area_notes n
     ORDER BY n.id
"""


def fmt_int(value) -> str:
    return f"{int(value):,}"


def fmt_aed(value) -> str:
    return f"AED {int(round(float(value))):,}"


def render_area_sheet(name, sales, years, rents, neighbours) -> str:
    """Render one area as a paragraph of plain English.

    Deterministic and templated on purpose. A model-written summary would be more
    fluent and would also be unverifiable: there would be no way to say whether a
    sentence came from the data or from the model. Every number below traces to one
    aggregate in one of the queries above.
    """
    parts: list[str] = [f"**{name}.**"]

    if sales and sales["tx_count"]:
        span = ""
        if sales["first_year"] and sales["last_year"]:
            span = f" between {sales['first_year']} and {sales['last_year']}"
        parts.append(f"{fmt_int(sales['tx_count'])} recorded sales{span}.")

        if sales["median_price"]:
            parts.append(f"Median recorded sale value {fmt_aed(sales['median_price'])}.")

        if years:
            latest = years[0]
            if latest["med_sqm"]:
                sentence = (
                    f"Median price per m2 in {latest['yr']} was "
                    f"{fmt_aed(latest['med_sqm'])} across "
                    f"{fmt_int(latest['cnt'])} sales"
                )
                if len(years) > 1 and years[1]["med_sqm"]:
                    prior = years[1]
                    change = (
                        float(latest["med_sqm"]) - float(prior["med_sqm"])
                    ) / float(prior["med_sqm"]) * 100
                    direction = "up" if change >= 0 else "down"
                    sentence += (
                        f", {direction} {abs(change):.1f}% from {fmt_aed(prior['med_sqm'])} "
                        f"in {prior['yr']}"
                    )
                parts.append(sentence + ".")

        total_reg = (sales["offplan"] or 0) + (sales["existing"] or 0)
        if total_reg:
            off = (sales["offplan"] or 0) / total_reg * 100
            parts.append(
                f"{100 - off:.0f}% of sales are existing property and {off:.0f}% off-plan."
            )
        if sales["dominant_usage"]:
            parts.append(
                f"Predominantly {str(sales['dominant_usage']).lower()} use, mostly "
                f"{str(sales['dominant_type'] or 'unspecified').lower()} units."
            )
    else:
        parts.append("No recorded sales transactions.")

    if rents and rents["rent_count"]:
        # Deliberately "registered", not "signed" or "active in year X". See trap 1.
        window = ""
        if rents["registered_from"] and rents["registered_to"]:
            window = (
                f", registered between {rents['registered_from']} and "
                f"{rents['registered_to']}"
            )
        sentence = f"{fmt_int(rents['rent_count'])} rent contracts on record{window}"
        if rents["median_annual_rent"]:
            sentence += (
                f", median annual rent per property "
                f"{fmt_aed(rents['median_annual_rent'])}"
            )
        parts.append(sentence + ".")
        parts.append(
            "Rent figures are a point-in-time snapshot of registered contracts, not a "
            "time series, and cannot be read as a rental trend."
        )
    else:
        parts.append("No rent contracts on record.")

    if neighbours:
        shown = neighbours[:6]
        listed = ", ".join(shown)
        more = f" and {len(neighbours) - len(shown)} others" if len(neighbours) > 6 else ""
        parts.append(f"Shares a boundary with {listed}{more}.")

    # No wall-clock timestamp in the returned text, deliberately.
    #
    # content_hash is a sha256 over exactly this string, and the incremental index
    # treats a changed hash as a changed document. Embedding the generation time made
    # all 175 sheets look new on every single build: measured as "175 to embed, 175
    # stale removed" on a run where no underlying row had changed. Generation time is
    # provenance, not content -- it lives in the record's meta and in the
    # doc_chunks.generated_at column, neither of which is hashed.
    return " ".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--docs", default="/app/docs", help="Directory of markdown docs")
    ap.add_argument("--out", default="/app/corpus/corpus.jsonl")
    ap.add_argument(
        "--skip-db",
        action="store_true",
        help="Docs only. Useful for testing the chunker without a database.",
    )
    ap.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help=(
            "Skip documents whose path matches GLOB. Repeatable. Applied on top of the "
            "built-in deny-list, never instead of it."
        ),
    )
    args = ap.parse_args()

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    records: list[dict] = []

    docs_dir = Path(args.docs)
    if not docs_dir.is_dir():
        print(f"ERROR: docs directory not found: {docs_dir}", file=sys.stderr)
        return 1

    patterns = list(DENY_GLOBS) + list(args.exclude)
    excluded: list[str] = []
    for path in sorted(docs_dir.glob("*.md")):
        # Match on the name AND on the path as given, so `eval/*` catches a file the
        # caller reached by pointing --docs at a parent, and `*golden*` catches it by
        # name wherever it sits.
        subject = (path.name, str(path), str(path.resolve()))
        hit = next(
            (g for g in patterns if any(fnmatch(s, g) for s in subject)),
            None,
        )
        if hit:
            excluded.append(f"{path.name} ({hit})")
            continue
        records.append(
            {
                "source_type": "doc",
                "source_id": f"docs/{path.name}",
                "text": path.read_text(encoding="utf-8"),
                "meta": {"bytes": path.stat().st_size},
            }
        )
    print(f"docs        : {len(records)} files")
    if excluded:
        # Printed, not silent. An exclusion nobody can see is how a corpus loses a
        # document for three milestones before anyone notices.
        print(f"excluded    : {len(excluded)} -> {', '.join(excluded)}")

    if args.skip_db:
        write(records, args.out)
        return 0

    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(SALES_SQL)
            sales = {r["norm"]: r for r in cur.fetchall()}

            cur.execute(YEAR_MEDIAN_SQL)
            years: dict[str, list[dict]] = {}
            for row in cur.fetchall():
                years.setdefault(row["norm"], []).append(row)

            cur.execute(RENTS_SQL)
            rents = {r["norm"]: r for r in cur.fetchall()}

            cur.execute(NEIGHBOURS_SQL)
            neighbours = {r["norm"]: r["neighbours"] for r in cur.fetchall()}

            sheets = 0
            skipped = 0
            for norm in sorted(set(sales) | set(rents)):
                s = sales.get(norm)
                r = rents.get(norm)
                total = (s["tx_count"] if s else 0) + (r["rent_count"] if r else 0)
                if total < MIN_RECORDS_FOR_SHEET:
                    skipped += 1
                    continue
                name = (s or r)["area_name_en"]
                records.append(
                    {
                        "source_type": "area_sheet",
                        "source_id": name,
                        "text": render_area_sheet(
                            name, s, years.get(norm, []), r,
                            neighbours.get(norm, []),
                        ),
                        "meta": {
                            "area_name_en": name,
                            "tx_count": int(s["tx_count"]) if s else 0,
                            "rent_count": int(r["rent_count"]) if r else 0,
                            "generated_at": generated_at,
                        },
                    }
                )
                sheets += 1
            print(
                f"area sheets : {sheets} rendered, {skipped} skipped "
                f"(< {MIN_RECORDS_FOR_SHEET} combined records)"
            )

            # area_notes is created by alembic, not init.sql. After a volume rebuild it
            # is absent until `alembic upgrade head` runs -- a missing notes table is a
            # migration state, not a corpus failure.
            try:
                cur.execute(NOTES_SQL)
                notes = cur.fetchall()
            except psycopg2.errors.UndefinedTable:
                conn.rollback()
                notes = []
                print("notes       : area_notes table absent - run `alembic upgrade head`")

            for note in notes:
                body = (note["body"] or "").strip()
                if not body:
                    continue
                title = (note["title"] or "").strip()
                tags = (note["tags"] or "").strip()
                header = " ".join(x for x in (title, f"[{tags}]" if tags else "") if x)
                records.append(
                    {
                        "source_type": "note",
                        "source_id": str(note["id"]),
                        "text": f"{header}\n\n{body}" if header else body,
                        "meta": {
                            "area_name": note["area_name"],
                            "note_id": note["id"],
                            "tags": tags,
                            "updated_at": str(note["updated_at"]),
                        },
                    }
                )
            if notes:
                print(f"notes       : {len(notes)} analyst notes")

    write(records, args.out)
    return 0


def write(records: list[dict], out_path: str) -> None:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"\nwrote {len(records)} documents -> {out}")


if __name__ == "__main__":
    raise SystemExit(main())
