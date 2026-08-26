# selectinload vs N+1 — the SQL, captured

How to reproduce:

```bash
SQL_ECHO=1 docker compose up -d api
curl -s localhost:8000/notes?limit=50
docker compose logs api | grep "Engine SELECT"
```

Six notes, three tags each (18 tags). `GET /notes?limit=50` emits **three** queries,
and that count does not change with page size:

1. `count(*)` for the pagination total
2. one SELECT for the parent rows
3. **one** SELECT for every child row, batched with `IN (...)`

Without `.options(selectinload(AreaNote.tags))` step 3 becomes one query per note —
1+N. In async SQLAlchemy it does not even degrade gracefully: implicit lazy loading
cannot issue IO from attribute access, so it raises `MissingGreenlet` instead.

`joinedload` would also fix the count, but with a LEFT OUTER JOIN that repeats each
parent row once per child — 18 rows to build 6 objects. For a one-to-many collection
`selectinload` is the better default.

## Captured output

```
SELECT count(*) AS count_1 
FROM area_notes
[generated in 0.00007s] ()
SELECT area_notes.id, area_notes.area_name, area_notes.title, area_notes.body, area_notes.author, area_notes.version, area_notes.created_at, area_notes.updated_at 
FROM area_notes ORDER BY area_notes.id 
 LIMIT $1::INTEGER OFFSET $2::INTEGER
--
SELECT note_tags.note_id AS note_tags_note_id, note_tags.id AS note_tags_id, note_tags.label AS note_tags_label 
FROM note_tags 
WHERE note_tags.note_id IN ($1::INTEGER, $2::INTEGER, $3::INTEGER, $4::INTEGER, $5::INTEGER, $6::INTEGER)
```
