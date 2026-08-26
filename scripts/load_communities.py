"""Load Dubai community boundaries from the DLD Community.kml export into PostGIS.

Replaces the hardcoded AREA_COORDS centroid dictionary that used to live in
api/routers/map_data.py with real polygon geometry, so centroids can be derived
with ST_Centroid and point-in-polygon queries become possible.

Usage:
    python load_communities.py /path/to/Community.kml

The KML is an ArcGIS export: attributes are an HTML table inside the Placemark's
<description> CDATA rather than proper <SimpleField> elements, so they are pulled
out with a regex. Geometry is a plain Polygon per Placemark (no MultiGeometry,
no interior rings), stored as MultiPolygon for schema uniformity.
"""

import os
import re
import sys
import xml.etree.ElementTree as ET

import psycopg2
from psycopg2.extras import execute_batch

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://dubai_user:dubai_pass@localhost:5432/dubai_re",
)

KML_NS = "{http://www.opengis.net/kml/2.2}"

# <th>CNAME_E</th><td>JABAL ALI FIRST</td> inside the description CDATA
ATTR_RE = re.compile(r"<th>([^<]+)</th>\s*<td>([^<]*)</td>", re.S)


def parse_attributes(description: str) -> dict[str, str]:
    """Pull the ArcGIS attribute table out of the description CDATA."""
    return {k.strip(): v.strip() for k, v in ATTR_RE.findall(description or "")}


def coords_to_ring(text: str) -> str | None:
    """KML 'lon,lat,alt lon,lat,alt ...' -> WKT ring 'lon lat, lon lat, ...'.

    KML is lon,lat which is already X,Y for EPSG:4326 — no axis swap needed.
    """
    points = []
    for token in text.split():
        parts = token.split(",")
        if len(parts) < 2:
            continue
        lon, lat = parts[0], parts[1]
        points.append(f"{float(lon)} {float(lat)}")

    if len(points) < 4:
        return None
    # A WKT polygon ring must be explicitly closed.
    if points[0] != points[-1]:
        points.append(points[0])
    return ",".join(points)


def parse_kml(path: str) -> list[tuple[str, str, str | None, str]]:
    """Return (name_en, name_norm, comm_num, wkt) per Placemark that has geometry."""
    tree = ET.parse(path)
    root = tree.getroot()

    rows: list[tuple[str, str, str | None, str]] = []
    skipped = 0

    for placemark in root.iter(f"{KML_NS}Placemark"):
        desc_el = placemark.find(f"{KML_NS}description")
        attrs = parse_attributes(desc_el.text if desc_el is not None else "")

        name = attrs.get("CNAME_E") or attrs.get("LABEL_E")
        if not name:
            skipped += 1
            continue

        rings = []
        for outer in placemark.iter(f"{KML_NS}outerBoundaryIs"):
            coord_el = outer.find(f".//{KML_NS}coordinates")
            if coord_el is None or not coord_el.text:
                continue
            ring = coords_to_ring(coord_el.text)
            if ring:
                rings.append(f"(({ring}))")

        if not rings:
            skipped += 1
            continue

        wkt = f"MULTIPOLYGON({','.join(rings)})"
        rows.append((name, name.strip().upper(), attrs.get("COMM_NUM"), wkt))

    if skipped:
        print(f"  Skipped {skipped} placemark(s) with no name or no geometry")
    return rows


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    path = sys.argv[1]
    print(f"Parsing {path}")
    rows = parse_kml(path)
    print(f"  Parsed {len(rows)} communities with geometry")
    if not rows:
        print("  Nothing to load")
        return 1

    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            execute_batch(
                cur,
                """
                INSERT INTO communities
                    (community_name_en, community_name_norm, community_number, geom)
                VALUES
                    (%s, %s, %s, ST_Multi(ST_GeomFromText(%s, 4326)))
                ON CONFLICT (community_name_norm) DO UPDATE SET
                    community_name_en = EXCLUDED.community_name_en,
                    community_number  = EXCLUDED.community_number,
                    geom              = EXCLUDED.geom,
                    loaded_at         = NOW()
                """,
                rows,
                page_size=50,
            )
            conn.commit()

            cur.execute("SELECT COUNT(*) FROM communities")
            total = cur.fetchone()[0]

            # How much of the transaction data these polygons actually cover —
            # the number worth quoting, not the raw polygon count.
            cur.execute(
                """
                SELECT COUNT(DISTINCT t.area_name_en)
                FROM raw_transactions t
                JOIN communities c
                  ON UPPER(TRIM(t.area_name_en)) = c.community_name_norm
                """
            )
            matched = cur.fetchone()[0]

            cur.execute(
                "SELECT COUNT(DISTINCT area_name_en) FROM raw_transactions "
                "WHERE area_name_en IS NOT NULL"
            )
            distinct_areas = cur.fetchone()[0]

        print(f"\n  communities table: {total} rows")
        print(f"  transaction areas matched: {matched}/{distinct_areas}")
        return 0
    except Exception as exc:  # noqa: BLE001 - surface the failure to the operator
        conn.rollback()
        print(f"  FAILED: {exc}")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
