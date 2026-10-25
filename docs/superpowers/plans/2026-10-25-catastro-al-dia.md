# Catastro al día (lane A of wasichai/srtm-backend#202) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load the catastro by entregas (upsert with history), carry the link to rentas, the titulares, and the
predio type; give srtm a change feed; turn Ica's comparison workbook into an entrega.

**Architecture:** The model grows in `model/model.json` (applied by `apply.py`). The loaders gain an upsert mode that
diffs the file against Core and writes only what changed, through the record API, with `X-Change-Reason` = the
entrega's code, so wasichai's `audit_log` holds each ficha's history. The Kotlin service adds keys to
`GET /valuaciones`, two new read endpoints (`/titulares`, `/cambios`), and two new engine motivos. `/cambios` reads
`audit_log` in-process.

**Tech Stack:** Kotlin + Spring WebFlux on wasichai 1.3.0 (`RecordService`, `CurrentUser`, `MetadataService`,
`WasichaiSchemas`, `DatabaseClient`, `AuditDiff`), JUnit 5, ktlint. Python 3.11 stdlib for `model/`, tested against
`fake_core.py`.

**Spec:** `/private/tmp/claude-502/-Users-jorge-IdeaProjects-srtm-backend/882b0f7f-a674-480b-a7cb-90fd30468dca/scratchpad/e202/`:
`contratos.md` (binding interfaces 1–4 and global constraints), `c1.md` (#23), `c2.md` (#24), `c3.md` (#25),
`c4.md` (#26), `c5.md` (#27), `c10-comentario.md` (#10). Converter column names come from
`/private/tmp/claude-502/-Users-jorge-IdeaProjects-srtm-backend/6e11dcd9-41e5-4cb7-adc5-ac4dd5dbd9c0/scratchpad/cmp-ica/convertir_catastro.py`
(code only; open no data file in that directory).

Shorthand used below:

```bash
W=/Users/jorge/IdeaProjects/catastro-backend-e202
PRUEBAS=/private/tmp/claude-502/-Users-jorge-IdeaProjects-srtm-backend/882b0f7f-a674-480b-a7cb-90fd30468dca/scratchpad/e202/pruebas-remotas.sh
# integration: $PRUEBAS $W testdb-catastro integrationTest --tests '<pattern>'
```

## Rulings

- Ruling: `motivo` and `llave` both carry the code (`SIN_LEVANTAMIENTO`, `PREDIO_RUSTICO`) — contract 1/4 says
  `motivo = "<code>"` literally, and srtm reads both — a person reads a code instead of a sentence; one-line change.
- Ruling: `SIN_LEVANTAR` is checked first, then `RUSTICO`, then the existing order (área, arancel…) — an empty ficha
  would otherwise say `AREA_TERRENO_FALTANTE` — a rústico sin levantar shows the wrong one of two motivos.
- Ruling: #23 keeps `valuacion-v2`, and #27 moves to `valuacion-v3` — no stored ficha has an estado before #23
  loads one, so no existing figure changes; the contract puts v3 on #27 — a v2 corrida could show
  `SIN_LEVANTAMIENTO`, which is harmless.
- Ruling: `POST /valuacion` gets `tipoPredio` only (no `estadoLevantamiento`) — insumos sueltos are a DJ's declared
  data, never an unsurveyed ficha — srtm would need one more optional key later.
- Ruling: `entrega_catastral` = `codigo` TEXT required+unique, `fecha_corte` DATE required, `fuente` ENUM
  `fuente_entrega` [`BARRIDO`, `INSPECCION`, `LICENCIA`, `GIS`, `OTRA`], `archivo_sha256` TEXT, `descripcion`
  TEXT, `altas`/`cambios`/`sin_cambio`/`ausentes` INTEGER — an entrega without a date is useless (LTM art. 10);
  an enum keeps the analytics clean — adding a source is one `apply.py` run.
- Ruling: the entrega code must match `^[A-Za-z0-9._:-]{1,64}$` — it travels in a header (`X-Change-Reason`), which
  carries ISO-8859-1 at best — a code with accents is refused with exit 2.
- Ruling: the loader creates the `entrega_catastral` record (shared `model/entregas.py`) on the first run that
  writes, with the summary of that run, and never updates it; a run with nothing to write writes nothing; the same
  code with a different `archivo_sha256` exits 2 — this makes "loading the same entrega twice changes nothing"
  literally true and stops one code from naming two deliveries — a summary reflects the first run only.
- Ruling: `archivo_sha256` = sha256 of the bytes of every input file, in CLI order (fichas, pisos, obras, titulares;
  for lotes, the geojson) — a corrected pisos file is another delivery — two runs with the same files in another
  order look like different files.
- Ruling: with `--entrega`, `--dry-run` logs in and reads Core (GET only) to report; without `--entrega` it stays
  offline as today — the spec asks the dry-run to report alta/cambio/ausente, which needs Core — a dry-run needs
  credentials.
- Ruling: a column the file has, with an empty cell, clears the field; a column the file lacks is not compared —
  the entrega is the truth for what it brings, which is how ADR-013 removes earlier estimates — an inspección file
  with an empty `uso` column clears uso; the dry-run shows it first.
- Ruling: updates are `PATCH` (JSON merge, only the changed keys, `null` clears); deletes are `DELETE`; both with
  `X-Change-Reason` — no read-modify-write of whole records, and geometries are untouched — none known.
- Ruling: `predio_catastral.entrega` = the last entrega that changed the ficha or one of its children; a `sin cambio`
  ficha keeps its previous entrega — otherwise each full re-delivery writes N audit rows and floods `/cambios` — the
  field does not say "last entrega that included it".
- Ruling: with `--entrega`, `--pisos` is optional; `--reemplazar-pisos` needs `--pisos` (exit 2 otherwise); a ficha
  in the file without piso rows loses all its pisos under `--reemplazar-pisos` — a GIS or inspección delivery may
  bring only fichas — a demolition must be loaded with the flag on purpose.
- Ruling: add `--reemplazar-obras`, same rule for obras — an obra with a corrected year has a new key and would be
  valued twice — one more flag to document.
- Ruling: without `--entrega`, `import_fichas.py` keeps today's create-only behaviour — Perené's runbook and tests
  depend on it — two modes to document.
- Ruling: values are compared normalized by the model.json type (DECIMAL by `Decimal`, INTEGER by `int`, BOOLEAN,
  DATE as ISO text, the rest as text; `None` equals absent) — Core answers `180.5` where the file says `180.50` —
  a missed type shows a false `cambio`.
- Ruling: `fecha_levantamiento` accepts `YYYY-MM-DD` or an xlsx serial day number; anything else is a problem (exit
  2) — those are the two forms csv/xlsx produce — a `DD/MM/YYYY` file needs converting first.
- Ruling: report lines are Spanish and fixed: `alta <cod>`, `cambio <cod>: <campo> <antes> → <después>`,
  `cambio <cod> piso <p>/<s>: …`, `cambio <cod> obra <codigo_vu>/<anio>: …`, `sin cambio <cod>`, `ausente <cod>`,
  `ausente <cod> piso <p>/<s>`, `vacío` for null, and a final `entrega <codigo>: <a> altas, <c> cambios, <s> sin
  cambio, <z> ausentes`; printed on dry-run and real run — one format to grep — cosmetic.
- Ruling: `import_lotes.py --actualizar-geometria` treats a polygon as changed when ring count, vertex count or any
  vertex differs by more than 1e-6° (~10 cm); it PATCHes only `geometries` (plus `entrega` when `--entrega` is
  given, which creates the entrega like `import_fichas`) — Core stores 32718 and answers 4326, so exact equality
  never holds — a sub-10 cm survey correction is ignored.
- Ruling: enum `vinculo_metodo` = [`CODIGO_RENTAS`, `LLAVE_HU_MZ_LOTE`, `GEOMETRICO`, `MANUAL`]; `cuc` and
  `codigo_referencia_catastral` get single-field indexes `[["cuc"], ["codigo_referencia_catastral"]]` — contract 1
  values; the spec says "indexados" — none.
- Ruling: `titular_catastral` carries a required, indexed `codigo_municipal` TEXT besides its required `predio`
  relation; `tipo_documento`, `numero_documento`, `nombre`, `condicion` TEXT; `porcentaje` DECIMAL — contract 2 pages
  by `codigo_municipal` then id, and Core sorts by one field of the object itself (`ORDER BY col, id`) — a predio
  renamed later leaves stale codes on its titulares.
- Ruling: `condicion` and `tipo_documento` are TEXT, not ENUM — the vocabulary differs between municipalities —
  analytics normalizes them.
- Ruling: a titular's key is (predio, `numero_documento` or `""`, `nombre` collapsed and upper-cased); a key repeated
  in the file is loaded once and counted as a warning, not an error — Ica's ~3 000 predios at 200 % are duplicated
  titulares and must still load — two homonyms without a document collapse into one.
- Ruling: a filler document is `^0+$` only; it is sent empty and reported by codigo and row — the spec names
  `000000000` — other fillers (`99999999`) pass as data.
- Ruling: the porcentaje check skips predios whose titulares all lack porcentaje; otherwise it reports sums that
  differ from 100 by more than 0.01 (empty = 0); it is a warning (exit 0) — a sole owner usually has no porcentaje —
  none.
- Ruling: the loader never deletes titulares; with `--entrega` it creates missing ones and PATCHes changed
  `tipo_documento`/`porcentaje`/`condicion` — the spec asks for no deletion — a titular who sold stays until removed
  by hand.
- Ruling: titular report lines carry codigo, row number and field names only, never values — Ley 29733 and c3 —
  none.
- Ruling: `/titulares` answers `{page, size, total, items}` with `total` = titulares the caller may read, `size`
  default 200 — same as valuaciones — none.
- Ruling: the integration helpers of `ValuacionesApiTest` move to an abstract `catastro.CatastroApiTest` — three test
  classes need them — a refactor commit to review.
- Ruling: `/cambios` reads `${schemas.metadata}.audit_log` with `DatabaseClient` in-process, after checking `READ` on
  `predio_catastral`, `construccion`, `obra_complementaria`, `titular_catastral` and `entrega_catastral` with
  `CurrentUser.requirePermission` — `GET /api/audit`/`AuditQueryService.page` demand an organization-wide READ
  (SRTM_LECTOR's is per object), it orders newest first, and `asPlatform` throws inside a request — couples catastro
  to wasichai's `audit_log` columns; recorded in ADR-014 and pinned by `CambiosApiTest`.
- Ruling: cursor = base64url (no padding) of `c1\n<occurred_at ISO>\n<id>`, order `(occurred_at, id)` ascending,
  rows strictly after it; a cursor that does not decode is a 422 on `desde` — stable and opaque like wasichai's —
  rows committed late with an earlier `occurred_at` are skipped (covered by srtm's weekly full run, ADR-014).
- Ruling: `campos`: CREATE = the non-null fields of `after_state`; UPDATE = `AuditDiff.changes(before, after)`
  fields; DELETE = `[]`; always restricted to the object's field names, in definition order — names only, no
  values — a field hidden from the caller still shows its name.
- Ruling: `codigoMunicipal` of a predio row comes from its own state; of a construccion/obra from its `predio` id,
  resolved through the latest audit state of that predio record (so a deleted predio still resolves); of a titular
  from its own `codigo_municipal`; unresolvable → `null`, the item stays — no live read can resolve a deleted predio —
  srtm gets a null code and must tolerate it.
- Ruling: `entrega` = `reason` only when an `entrega_catastral` with that `codigo` exists; only operations `CREATE`,
  `UPDATE`, `DELETE` are listed — contract 3 — none.
- Ruling: no ADR for rústicos; the README version table gets the v3 row — c5 only cites ADR-004/005 — none.
- Ruling: an unknown `tipoPredio` in `POST /valuacion` is a 422 on `tipoPredio` — same as every other field — none.
- Ruling: ADR numbers: ADR-013 entregas, ADR-014 cambios — next free numbers — renumbering.
- Ruling (#10): the converter reads the three `*_catastro` sheets only; `titulares_catastro` column defaults are
  `cod_predio`, `tipo_documento_catastro`, `numero_documento_catastro`, `nombre_catastro`,
  `porcentaje_catastro`, `condicion_catastro` (the pattern of `construccion_catastro`), overridable with
  `--map-titulares`; optional predio columns `cuc_catastro` and `urbanizacion_catastro`; a missing required column
  exits 2 naming it — the only known names are those in the old script — the operator passes `--map-titulares`.
- Ruling (#10): the vínculo comes from a csv exported from the gpkg (`ogr2ogr -f CSV`), columns `cod_predio_rentas`
  and `vinculo_metodo` (`--map-vinculos`), values matched case-insensitively to the enum or through `--metodo
  TEXTO=ENUM`; unknown → exit 2; without `--vinculos`, `vinculo_metodo` is empty — stdlib cannot read a gpkg's
  geometry and the column names are unknown — one ogr2ogr step more.
- Ruling (#10): a ficha is not loaded when `codigo_unidad_catastro` is empty, or (with `--vinculos`) when its code has
  no vínculo row — "los lotes sin vínculo no se cargan" — none.
- Ruling (#10): `codigo_referencia_catastral` = `codigo_unidad_catastro` as it comes; sector/manzana/lote = its parts
  3/4/5 split on `-` (the old script) — it has the CRC's shape — a re-run with a fix updates it.
- Ruling (#10): estado = `SIN_LEVANTAR` when área ≤ 0 or empty, no construccion row, no titular row and (when the
  column exists) empty urbanización; `PARCIAL` when área ≤ 0/empty but something else exists; `COMPLETO` otherwise;
  `fecha_levantamiento` empty — c10's definition; the libro has no date — `COMPLETO` overstates a bare lot.
- Ruling (#10): `uso` and `id_aranc` are written as present, empty columns — so an upsert clears the VPS's estimated
  values (c10, ADR-013) — none.
- Ruling (#10): material code `1/2/3` → `CONCRETO/LADRILLO/ADOBE`, estado `1..4` → `MUY BUENO/BUENO/REGULAR/MALO`
  (README's reading of Ica's codes); a model option passes; anything else goes empty and is counted — the catastro
  sheet's spelling is unknown — the counts show it.
- Ruling (#10): a nivel without digits is dropped and counted; secciones number in sheet order within (predio, piso);
  a repeated `cod_predio_rentas` keeps the first ficha and is counted — stable and visible — none.
- Ruling (#10): the converter refuses a `--salida` inside the repository (exit 2) — the output holds personal data —
  none.
- Ruling (#10): reloading the VPS from the converter's output is a manual operation for the user, not a task — the
  global constraints forbid touching shared environments — none.

## Global Constraints

- One branch and one PR per issue, stacked in this lane; each PR closes its issue (`Closes
  wasichai/catastro-backend#N`). The controller pushes and opens the PR; implementers only commit.
- Conventional commits in Spanish (`feat(model): …`, `fix(valuacion): …`); commitlint caps body lines at 100
  characters, wrap at about 95.
- Code comments follow the surrounding density and style (English).
- Kotlin: TDD. Unit tests `./gradlew test --tests '…'`; integration tests ONLY through
  `$PRUEBAS $W testdb-catastro integrationTest --tests '<pattern>'`. Never Testcontainers, never local Docker.
- Python: `cd model && python3 -m unittest -v test_<x>`, stdlib only, against `fake_core`.
- Model changes only through `model/model.json` + `model/roles.json` and `python3 apply.py --validate-only`; never
  SQL; new fields optional unless the issue says otherwise.
- NEVER read or process real municipal data; synthetic fixtures only.
- Do not touch the dev DB, the VPS app stacks or any other worktree.
- Each issue updates the docs it names (README, ADR) in the same branch.
- Contract 1: every `/valuaciones` item always carries `estadoLevantamiento`, `fechaLevantamiento`, `entrega`,
  `vinculoMetodo`, `vinculoRevisado`, `cuc`, `codigoReferenciaCatastral` (null when no data).
- Contract 2: `GET /api/catastro/titulares?page=&size=`, `size` 1–500, 422 on a bad parameter, items
  `{codigoMunicipal, tipoDocumento, numeroDocumento, nombre, porcentaje, condicion}`, SRTM_LECTOR.
- Contract 3: `GET /api/catastro/cambios?desde=&size=`, `size` 1–500 default 200, `{items, cursor, hayMas}`, oldest
  first; nothing new → empty items, same cursor, `hayMas = false`.
- Contract 4: `tipoPredio: "URBANO" | "RUSTICO"` optional in `POST /valuacion`; `predio_catastral.tipo_predio` ENUM
  optional; `motivo = "PREDIO_RUSTICO"`; version `valuacion-v3`.

## Review Focus

- A run that failed half way, re-run with the same files: it completes without duplicates and leaves the entrega's
  summary as first recorded (test in Task 5).
- Core answering a number in another spelling than the file (`180.5` vs `180.50`, `86` vs `86.0`): `sin cambio`, no
  PATCH (test in Task 4).
- A later entrega whose file lacks a column: that field is untouched, never cleared (test in Task 4).
- Paging `/cambios` with a small `size` across rows written close together (ties on `occurred_at` are ordered by
  `id`): `size=1` gives exactly the items of `size=500`, none repeated or skipped (test in Task 15).
- Personal data in loader output: no titular name or document ever appears on stdout/stderr (tests in Tasks 11
  and 19).

---

## Issue #23: entregas del levantamiento

Branch: `feat/entregas-levantamiento` (already checked out; based on `main`).

### Task 1: Model for entregas and the ficha's levantamiento state

**Files:**
- Modify: `model/model.json` (two enums, object `entrega_catastral` appended last to `objects`, two
  `predio_catastral` fields, one relationship)
- Modify: `model/roles.json` (READ on `entrega_catastral`; description lists it)
- Modify: `model/apply.py` (docstring counts: 6 objects, 3 relationships)
- Test: `model/test_model.py`

**Interfaces:**
- Produces: enums `estado_levantamiento` = `["SIN_LEVANTAR", "PARCIAL", "COMPLETO"]`, `fuente_entrega` =
  `["BARRIDO", "INSPECCION", "LICENCIA", "GIS", "OTRA"]`; object `entrega_catastral` fields in order `codigo`
  (TEXT, required, unique), `fecha_corte` (DATE, required), `fuente` (ENUM `fuente_entrega`), `archivo_sha256`,
  `descripcion` (TEXT), `altas`, `cambios`, `sin_cambio`, `ausentes` (INTEGER); `predio_catastral` appends
  `fecha_levantamiento` (DATE), `estado_levantamiento` (ENUM, no default); relationship
  `predio_catastral_entrega` (source `predio_catastral`, target `entrega_catastral`, fieldName `entrega`, not
  required).

- [ ] **Step 1: Write the failing tests** in `test_model.py`

```python
# OBJETOS gains "entrega_catastral": ([codigo, fecha_corte, fuente, archivo_sha256, descripcion, altas, cambios,
#   sin_cambio, ausentes], {"codigo", "fecha_corte"}, {"codigo"}); predio_catastral's list ends
#   [..., "lote_geom", "fecha_levantamiento", "estado_levantamiento"]
def test_the_levantamiento_state_has_no_default(self):
    f = {x["name"]: x for x in self.objects["predio_catastral"]["fields"]}
    self.assertEqual(self.model["enums"]["estado_levantamiento"], ["SIN_LEVANTAR", "PARCIAL", "COMPLETO"])
    self.assertEqual((f["estado_levantamiento"]["type"], f["fecha_levantamiento"]["type"]), ("ENUM", "DATE"))
    self.assertNotIn("default", f["estado_levantamiento"])
def test_a_predio_points_to_its_entrega(self):
    r = {x["name"]: x for x in self.model["relationships"]}["predio_catastral_entrega"]
    self.assertEqual((r["source"], r["target"], r["fieldName"], r.get("required", False)),
                     ("predio_catastral", "entrega_catastral", "entrega", False))
# test_children_hang_from_a_required_predio: check only construccion_predio and obra_complementaria_predio
```

- [ ] **Step 2: Run and see them fail:** `cd model && python3 -m unittest -v test_model test_apply_roles` → FAIL
  (`entrega_catastral` missing; `test_el_lector_de_srtm_lee_cada_objeto…` fails once the object exists without its
  READ).
- [ ] **Step 3: Edit `model.json` and `roles.json`** as in Interfaces; descriptions in Spanish like the others.
- [ ] **Step 4: Verify:** `cd model && python3 apply.py --validate-only && python3 -m unittest -v test_model
  test_apply_roles && cd .. && yarn format:check` → all OK.
- [ ] **Step 5: Commit** `feat(model): entrega_catastral y el estado del levantamiento de cada ficha`

### Task 2: Writes with a reason: client, fake Core, parallel writer

**Files:**
- Modify: `model/core_client.py`, `model/fake_core.py`, `model/tabular.py`
- Create: `model/test_core_client.py`

**Interfaces:**
- Produces: `Client.post(path, body, reason=None)`, `Client.patch(path, body, reason=None)`,
  `Client.delete(path, reason=None)`; `_call` sends `X-Change-Reason: <reason>` when given. `FakeCore` handles
  `PATCH /api/objects/{o}/records/{id}` (merge `attributes`, `null` deletes the key, merge `geometries`, 404 unknown
  id, `fail_on_update` → 400) and appends `(method, path, reason)` to a new list `FakeCore.reasons` (the
  `requests` 4-tuples stay as they are). `tabular.write_all(client, ops, workers, reason) -> dict` where an op is
  `(key, fila, method, object_name, record_id, attributes)`; POST returns `key -> new id`; the first refusal raises
  `LoadError` and cancels the rest (as `post_all`).

- [ ] **Step 1: Failing tests** in `test_core_client.py`

```python
def test_patch_merges_and_null_clears(self):
    r = self.core.add_record("predio_catastral", {"codigo_municipal": "A", "uso": "010101", "lote": "1"})
    self.client.patch(f"/api/objects/predio_catastral/records/{r['id']}", {"attributes": {"uso": None, "lote": "2"}})
    self.assertEqual(r["attributes"], {"codigo_municipal": "A", "lote": "2"})
def test_the_reason_travels_in_its_header(self):
    self.client.post("/api/objects/predio_catastral/records", {"attributes": {"codigo_municipal": "B"}}, reason="E-1")
    self.assertEqual(self.core.reasons[-1], ("POST", "/api/objects/predio_catastral/records", "E-1"))
def test_write_all_posts_patches_and_deletes_with_the_reason(self): ...  # 3 ops → 3 reasons "E-1", ids for the POST key
def test_write_all_stops_at_the_first_refusal(self): ...  # fail_on_update → LoadError with its fila
```

- [ ] **Step 2:** `cd model && python3 -m unittest -v test_core_client` → FAIL (`patch` missing).
- [ ] **Step 3: Implement** the signatures above.
- [ ] **Step 4:** `cd model && python3 -m unittest -v` → all pass (old tests untouched).
- [ ] **Step 5: Commit** `feat(model): escrituras con X-Change-Reason y PATCH en el cliente de core`

### Task 3: Read the levantamiento columns of a ficha

**Files:**
- Modify: `model/import_fichas.py` (`FICHA_COLUMNS`, `fichas_from`, new `parse_date`, new `present_fields`)
- Test: `model/test_import_fichas.py` (class `ParseTests`)

**Interfaces:**
- Produces: `FICHA_COLUMNS` gains `"estado_levantamiento": "estado_levantamiento"`,
  `"fecha_levantamiento": "fecha_levantamiento"`; `fichas_from(rows, mapping, enums)` (new `enums` parameter;
  update its callers) parses estado with `enum_option(…, enums["estado_levantamiento"])`;
  `parse_date(value) -> (iso_text | None, error | None)`; `present_fields(rows, mapping, fields) -> set[str]` = the
  fields whose mapped column is in the header (`rows[0]`), empty set for no rows.

- [ ] **Step 1: Failing tests**

```python
def test_estado_and_fecha_levantamiento(self):
    rows = read_table(write_csv(self, "cod_pre,estado_levantamiento,fecha_levantamiento\nA,sin_levantar,2026-09-30\n"
                                      "B,,46000\nC,LEVANTADO,30/09/2026\n"))
    fichas, problems = imf.fichas_from(rows, parse_map([], imf.FICHA_COLUMNS), ENUMS)
    self.assertEqual(fichas[0][1]["estado_levantamiento"], "SIN_LEVANTAR")
    self.assertEqual(fichas[0][1]["fecha_levantamiento"], "2026-09-30")
    self.assertEqual(fichas[1][1]["fecha_levantamiento"], "2025-12-09")   # xlsx serial 46000
    self.assertIsNone(fichas[1][1]["estado_levantamiento"])               # no default
    self.assertEqual(len(problems), 2, problems)                          # C: estado and fecha
def test_present_fields_reads_the_header(self):
    rows = read_table(write_csv(self, "cod_pre,uso\nA,\n"))
    self.assertEqual(imf.present_fields(rows, parse_map([], imf.FICHA_COLUMNS), ["uso", "lote"]), {"uso"})
```

- [ ] **Step 2:** `cd model && python3 -m unittest -v test_import_fichas` → FAIL.
- [ ] **Step 3: Implement.** `parse_date`: ISO via `datetime.date.fromisoformat`; an integer/`N.0` text as days after
  1899-12-30.
- [ ] **Step 4:** `cd model && python3 -m unittest -v test_import_fichas test_isolated` → PASS.
- [ ] **Step 5: Commit** `feat(model): import_fichas lee el estado y la fecha del levantamiento`

### Task 4: The entrega's plan: diff a file against Core

**Files:**
- Create: `model/entregas.py`, `model/test_entregas.py`

**Interfaces:**
- Consumes: `fichas_from` / `pisos_from` / `obras_from` tuples, `piso_key`, `obra_key`, `relation_id` from
  `import_fichas` (move `piso_key`, `obra_key`, `relation_id` into `entregas.py` and import them back in
  `import_fichas.py` to avoid a cycle).
- Produces:
  - `CODIGO = re.compile(r"[A-Za-z0-9._:-]{1,64}")`; `check_codigo(codigo) -> str | None` (error text).
  - `sha256_of(paths: list[str]) -> str`.
  - `field_types(model_path) -> dict[str, dict[str, str]]` (object → field → type).
  - `same(a, b, ftype) -> bool`; `diff(core_attrs, wanted, present, types) -> dict[str, tuple]` (field → (antes,
    después)), only over `present`.
  - `@dataclass CoreState(predios, construcciones, obras, titulares)` (lists of Core records);
    `read_core(client, titulares=False) -> CoreState`.
  - `@dataclass Present(fichas: set, pisos: set, obras: set, titulares: set)`.
  - `@dataclass Plan(lines: list[str], counts: dict, predio_ops: list, child_ops: list, touched: set[str])`, property
    `writes -> int`; ops are `write_all` tuples, child ops carry `codigo` in the key and no `predio` (apply fills it).
  - `plan_entrega(core: CoreState, fichas, pisos, obras, present: Present, types, *, with_pisos: bool,
    reemplazar_pisos: bool, reemplazar_obras: bool) -> Plan`; `counts` keys `altas`, `cambios`, `sin_cambio`,
    `ausentes` (per ficha). `touched` = codes of altas and cambios (own fields or children).

- [ ] **Step 1: Failing tests** in `test_entregas.py` (pure: build `CoreState` by hand, no server)

```python
def test_a_new_ficha_is_an_alta(self): ...                 # lines == ["alta A", …]; one POST predio op
def test_another_decimal_spelling_is_sin_cambio(self):
    core = state(predios=[rec("A", area_terreno=180.5)])
    plan = plan_of(core, fichas=[ficha("A", area_terreno="180.50")], present={"area_terreno"})
    self.assertIn("sin cambio A", plan.lines); self.assertEqual(plan.writes, 0)
def test_a_changed_field_reports_antes_and_despues(self):
    self.assertIn("cambio A: uso 010101 → 020100", plan.lines)
    self.assertEqual(plan.predio_ops[0][5], {"uso": "020100"})        # PATCH body: only the change
def test_an_absent_column_is_untouched_an_empty_cell_clears(self):
    # present={"uso"}: uso "" → PATCH {"uso": None}, line "cambio A: uso 010101 → vacío"; lote not compared
def test_a_ficha_core_has_and_the_file_lacks_is_ausente_and_kept(self):
    self.assertIn("ausente Z", plan.lines); self.assertEqual(plan.counts["ausentes"], 1)
    self.assertFalse(any(op[2] == "DELETE" for op in plan.child_ops + plan.predio_ops))
def test_a_corrected_piso_is_a_patch_by_its_key(self):
    self.assertIn("cambio A piso 2/1: area_construida 86 → 90", plan.lines)
def test_a_new_seccion_is_a_post_and_a_missing_piso_is_listed(self):
    # Core has piso 3/1, file lacks it, no flag → "ausente A piso 3/1", no DELETE
def test_reemplazar_pisos_deletes_only_in_fichas_the_file_brings(self):
    # ficha A in file without piso rows → its two pisos DELETE; ficha Z (ausente) keeps its pisos
def test_reemplazar_obras_deletes_an_obra_whose_year_changed(self): ...  # new key POST + old key DELETE
def test_a_ficha_whose_only_change_is_a_piso_is_a_cambio_and_touched(self):
    self.assertEqual((plan.counts["cambios"], plan.touched), (1, {"A"}))
def test_without_pisos_file_pisos_are_not_compared(self): ...  # with_pisos=False → no piso lines or ops
def test_the_summary_line(self):
    self.assertEqual(plan.lines[-1], "entrega E-1: 1 altas, 1 cambios, 1 sin cambio, 1 ausentes")
```

(`plan_entrega` takes the code for the summary line through a keyword `codigo`.)

- [ ] **Step 2:** `cd model && python3 -m unittest -v test_entregas` → FAIL (module missing).
- [ ] **Step 3: Implement** `entregas.py` as in Interfaces. Lines in file order of fichas, children lines right after
  their ficha, ausentes after all fichas, summary last.
- [ ] **Step 4:** `cd model && python3 -m unittest -v test_entregas test_import_fichas` → PASS.
- [ ] **Step 5: Commit** `feat(model): el plan de una entrega compara el archivo con core`

### Task 5: `import_fichas.py --entrega`: upsert through the API, and ADR-013

**Files:**
- Modify: `model/entregas.py` (`find_entrega`, `ensure_entrega`, `apply_plan`, `EntregaError`)
- Modify: `model/import_fichas.py` (CLI, `main`)
- Modify: `README.md` (new section «Entregas» under «Modelo y carga»; the fichas paragraph points to it)
- Create: `docs/adr/0013-el-levantamiento-llega-por-entregas.md`; Modify: `docs/adr/README.md` (index)
- Test: `model/test_import_fichas.py` (new class `EntregaLoadTests`)

**Interfaces:**
- Consumes: Task 2 `write_all`, `Client.patch/delete(reason=)`; Task 4 `plan_entrega`, `read_core`, `sha256_of`,
  `check_codigo`.
- Produces:
  - `find_entrega(client, codigo) -> record | None` (list filtered by `codigo`).
  - `ensure_entrega(client, codigo, *, fecha_corte, fuente, descripcion, sha, counts) -> str` (id): POSTs the
    record with reason = codigo when missing; returns the existing id when its `archivo_sha256 == sha`; raises
    `EntregaError` otherwise.
  - `apply_plan(client, plan, entrega_id, reason, workers) -> None`: predio ops first (adds `entrega` to every
    predio POST/PATCH), then a `PATCH {entrega}` for each `touched` code without a predio op, then child DELETEs,
    then child POST/PATCH with `predio` filled from the predio ids.
  - CLI: `--entrega CODIGO`, `--fecha-corte YYYY-MM-DD`, `--fuente <fuente_entrega>`, `--descripcion TEXT`,
    `--reemplazar-pisos`, `--reemplazar-obras`. With `--entrega`: `--fecha-corte` and `--fuente` required, `--pisos`
    optional. Exit 2 for: bad codigo, missing/invalid `--fecha-corte`/`--fuente`, a `--reemplazar-*` without
    `--entrega` or without its file, an entrega with that code and another sha. Done line:
    `done: entrega <codigo>: <a> altas, <c> cambios, <s> sin cambio, <z> ausentes`.

- [ ] **Step 1: Failing tests** (`EntregaLoadTests`, FakeCore, the module's FICHAS/PISOS/OBRAS fixtures)

```python
def entrega(self, *extra): return self.cli("--entrega", "E-1", "--fecha-corte", "2026-10-01", "--fuente", "BARRIDO", *extra)
def writes(self): return [r for r in self.core.requests if r[0] in ("POST", "PATCH", "DELETE") and "records" in r[1]]
def test_first_load_creates_the_fichas_and_the_entrega(self):
    code, out, err = self.entrega("--obras", self.obras); self.assertEqual(code, 0, err)
    e = self.core.records["entrega_catastral"][0]["attributes"]
    self.assertEqual((e["codigo"], e["altas"], e["cambios"], e["fuente"]), ("E-1", 2, 0, "BARRIDO"))
    self.assertTrue(all(p["attributes"]["entrega"] == self.core.records["entrega_catastral"][0]["id"]
                        for p in self.core.records["predio_catastral"]))
def test_the_same_entrega_twice_changes_nothing(self):
    self.entrega("--obras", self.obras); before = len(self.writes())
    code, out, _ = self.entrega("--obras", self.obras)
    self.assertEqual((code, len(self.writes())), (0, before))
    self.assertIn("sin cambio 120302-0001", out)
def test_a_corrected_piso_is_patched_and_reported(self):
    # second entrega E-2 with piso 2 area 90 → out has "cambio 120302-0001 piso 2/1: area_construida 86 → 90";
    # the PATCH body is {"attributes": {"area_construida": "90"}}; the predio's entrega becomes E-2's id
def test_an_absent_ficha_is_listed_not_deleted(self): ...   # Core-only predio → "ausente X", still in records
def test_reemplazar_pisos_deletes_the_pisos_the_entrega_no_longer_brings(self): ...
def test_every_write_carries_the_entrega_as_reason(self):
    self.entrega()
    writes = [x for x in self.core.reasons if x[0] in ("POST", "PATCH", "DELETE") and "/records" in x[1]]
    self.assertTrue(writes); self.assertEqual({r for _, _, r in writes}, {"E-1"})
def test_dry_run_reports_and_writes_nothing(self):
    code, out, _ = self.entrega("--dry-run"); self.assertEqual((code, self.writes()), (0, []))
    self.assertIn("alta 120302-0001", out)
def test_same_codigo_another_file_exits_2(self): ...         # change PISOS after the first run → 2, no writes
def test_a_run_that_failed_half_way_is_completed_and_keeps_the_summary(self):
    self.core.fail_record_after = {"construccion": 1}; self.assertEqual(self.entrega()[0], 1)
    self.core.fail_record_after = {}; code, _, err = self.entrega(); self.assertEqual(code, 0, err)
    self.assertEqual(len(self.core.records["construccion"]), 3)
    self.assertEqual(self.core.records["entrega_catastral"][0]["attributes"]["altas"], 2)
def test_reemplazar_without_entrega_or_pisos_exits_2(self): ...
def test_a_bad_codigo_or_fuente_exits_2(self): ...           # "E 1", "--fuente CENSO"
```

- [ ] **Step 2:** `cd model && python3 -m unittest -v test_import_fichas` → FAIL.
- [ ] **Step 3: Implement** the CLI flow: parse and validate (exit 2) → login → `find_entrega` + sha check → `read_core`
  → `plan_entrega` → print `plan.lines` → stop if `--dry-run` or `plan.writes == 0` → `ensure_entrega` →
  `apply_plan`. `LoadError`/`CoreError` → exit 1 as today.
- [ ] **Step 4: Docs.** README «Entregas»: what an entrega is, the flags, the report format, the idempotence rule,
  ausentes are never deleted, `--reemplazar-pisos/-obras`, a full example (`--dry-run` first). ADR-013 (template of
  `docs/adr/README.md`, «aceptada · 2026-10-25»): **Contexto** (c1: loaders only create; ~9 800 empty fichas in Ica
  counted as «coincide» when loaded with rentas' area); **Alternativas** (load by SQL: skips permissions and the
  audit log; fill gaps from rentas: makes the brecha compare rentas with itself; delete ausentes automatically: a
  partial delivery would erase the catastro); **Decisión** (the two bullets of c1's ADR-013, plus: the reason of
  each write is the entrega's code, the predio points to the last entrega that changed it); **Consecuencias**
  (history lives in wasichai's `audit_log`; ausentes are a manual decision; estimates are analysis scenarios,
  srtm#205).
- [ ] **Step 5: Verify:** `cd model && python3 -m unittest -v && cd .. && yarn format:check` → PASS.
- [ ] **Step 6: Commit** `feat(model): import_fichas --entrega carga por upsert con la historia en el audit log`

### Task 6: `import_lotes.py --actualizar-geometria`

**Files:**
- Modify: `model/import_lotes.py`, `README.md` (Lotes paragraph)
- Test: `model/test_import_lotes.py`

**Interfaces:**
- Consumes: `entregas.check_codigo`, `find_entrega`, `ensure_entrega`, `sha256_of`; `Client.patch(reason=)`.
- Produces: `same_polygon(a, b, tolerance=1e-6) -> bool`; `load(client, lotes, workers, *, actualizar=False,
  entrega_id=None, reason=None) -> (updated, already, not_found)`; flags `--actualizar-geometria`, `--entrega`,
  `--fecha-corte`, `--fuente` (the last two required with `--entrega`). With `--actualizar-geometria` a predio whose
  polygon differs gets `PATCH {"attributes": {"entrega": id}?, "geometries": {"lote_geom": polygon}}`; without it,
  behaviour is today's.

- [ ] **Step 1: Failing tests**

```python
def test_a_moved_polygon_is_replaced_only_with_the_flag(self):
    # Core has SQUARE on A; feature brings SQUARE shifted 1e-4 → without flag "0 updated, 1 skipped"; with flag "1 updated"
    # and a PATCH (not a PUT) whose body has no attributes but the entrega
def test_a_polygon_within_tolerance_is_the_same(self): ...   # shift 1e-7 → 0 updated
def test_the_entrega_is_the_reason_and_the_predio_points_to_it(self): ...
def test_same_polygon_compares_rings_and_vertices(self): ...
```

- [ ] **Step 2:** `cd model && python3 -m unittest -v test_import_lotes` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** `cd model && python3 -m unittest -v test_import_lotes test_isolated` → PASS.
- [ ] **Step 5: Commit** `feat(model): import_lotes --actualizar-geometria reemplaza el polígono que cambió`

### Task 7: The engine's `SIN_LEVANTAMIENTO` and the entrega keys in `/valuaciones`

**Files:**
- Modify: `src/main/kotlin/catastro/valuacion/Valorizacion.kt` (`Insumos`, `calcular`)
- Modify: `src/main/kotlin/catastro/valuacion/Fichas.kt` (`ENTREGA_CATASTRAL`, `PredioCatastral`, new
  `EntregaCatastral`)
- Modify: `src/main/kotlin/catastro/valuacion/Valuaciones.kt` (`ItemValuacion`)
- Modify: `src/main/kotlin/catastro/valuacion/ValuacionesService.kt`
- Modify: `src/main/kotlin/catastro/Registros.kt` (`porIds`)
- Modify: `README.md` (API item keys and their example; the motivos list gains a «Motivos» table naming every llave,
  `SIN_LEVANTAMIENTO` first)
- Test: `src/test/kotlin/catastro/valuacion/ValorizacionTest.kt`, create
  `src/test/kotlin/catastro/valuacion/ItemValuacionJsonTest.kt`, modify
  `src/test/kotlin/catastro/valuacion/ValuacionesApiTest.kt`

**Interfaces:**
- Produces:
  - `Insumos(..., val levantamiento: String? = null, val tipoPredio: String? = null)` (both appended with defaults;
    `tipoPredio` is used in Task 17).
  - In `Valorizacion`: `const val SIN_LEVANTAMIENTO = "SIN_LEVANTAMIENTO"`; `calcular` first line:
    `if (i.levantamiento == "SIN_LEVANTAR") falta(SIN_LEVANTAMIENTO, SIN_LEVANTAMIENTO)`.
  - `PredioCatastral` gains `entrega: String?` (relation id), `fechaLevantamiento: String?` (Core answers DATE as ISO
    text), `estadoLevantamiento: String?`. `data class EntregaCatastral(val id: String, val codigo: String? = null)`.
  - `ItemValuacion` appends `estadoLevantamiento: String?`, `fechaLevantamiento: String?`, `entrega: String?` (the
    codigo) after `loteGeom`.
  - `Registros.porIds(objectName: String, type: Class<T>, ids: Collection<UUID>): List<T>` (chunks of
    `PageRequest.MAX_SIZE`, `RecordQuery(ids = chunk, count = false)`).
  - `ValuacionesService.pagina` reads the page's entregas once with `porIds(ENTREGA_CATASTRAL, …)`.

- [ ] **Step 1: Failing unit tests**

```kotlin
@Test fun `una ficha sin levantar no se valoriza ni se estima`() {
    val v = sinValor(insumos(areaTerreno = null, arancelM2 = null).copy(levantamiento = "SIN_LEVANTAR"))
    assertEquals("SIN_LEVANTAMIENTO", v.llave); assertEquals("SIN_LEVANTAMIENTO", v.motivo)
}
@Test fun `una ficha parcial o completa se valoriza como siempre`() {
    assertEquals(bd("9100.00"), valorizada(insumos().copy(levantamiento = "PARCIAL")).autoavaluo)
}
// ItemValuacionJsonTest
@Test fun `las llaves del levantamiento vienen siempre, nulas sin dato`() {
    val json = JsonMapper.builder().build().writeValueAsString(item(/* every nullable null */))
    listOf("estadoLevantamiento", "fechaLevantamiento", "entrega").forEach { assertTrue(json.contains("\"$it\":null")) }
}
```

- [ ] **Step 2:** `./gradlew test --tests 'catastro.valuacion.ValorizacionTest' --tests 'catastro.valuacion.ItemValuacionJsonTest'`
  → FAIL (compilation).
- [ ] **Step 3: Implement** the Interfaces.
- [ ] **Step 4: Unit verify:** `./gradlew test ktlintCheck` → PASS.
- [ ] **Step 5: Integration test** in `ValuacionesApiTest`:

```kotlin
@Test fun `una ficha sin levantar dice su estado, su fecha y su entrega, y no tiene valor`() {
    // admin creates entrega_catastral {codigo: uniq, fecha_corte: "2026-10-01"}; predio with estado SIN_LEVANTAR,
    // fecha_levantamiento "2026-09-30", entrega = id; another predio without them. SRTM_LECTOR reads:
    assertTrue(sin["autoavaluo"].isNull); assertEquals("SIN_LEVANTAMIENTO", sin["motivo"].asString())
    assertEquals(listOf("SIN_LEVANTAR", "2026-09-30", codigo), listOf("estadoLevantamiento", "fechaLevantamiento", "entrega").map { sin[it].asString() })
    listOf("estadoLevantamiento", "fechaLevantamiento", "entrega").forEach { assertTrue(otro.has(it) && otro[it].isNull) }
}
```

  Run `$PRUEBAS $W testdb-catastro integrationTest --tests 'catastro.valuacion.ValuacionesApiTest'` → PASS.
- [ ] **Step 6: Commit** `feat(valuacion): una ficha sin levantar da SIN_LEVANTAMIENTO y la valuación dice su entrega`

---

## Issue #24: vínculo con rentas

Branch: `feat/vinculo-rentas` — `git checkout -b feat/vinculo-rentas` from the head of `feat/entregas-levantamiento`.

### Task 8: Model and loader columns for the vínculo and the SNIC codes

**Files:**
- Modify: `model/model.json` (enum `vinculo_metodo`; `predio_catastral` appends `vinculo_metodo` (ENUM),
  `vinculo_revisado` (BOOLEAN), `cuc` (TEXT), `codigo_referencia_catastral` (TEXT); indexes append `["cuc"]`,
  `["codigo_referencia_catastral"]`)
- Modify: `model/import_fichas.py` (`FICHA_COLUMNS` with the four names as defaults; `fichas_from` parses them)
- Modify: `README.md` (fichas columns)
- Test: `model/test_model.py`, `model/test_import_fichas.py`, `model/test_entregas.py`

**Interfaces:**
- Produces: enum `vinculo_metodo` = `["CODIGO_RENTAS", "LLAVE_HU_MZ_LOTE", "GEOMETRICO", "MANUAL"]`; ficha attributes
  `vinculo_metodo`, `vinculo_revisado` (via `parse_bool`), `cuc`, `codigo_referencia_catastral` (via `code_text`).

- [ ] **Step 1: Failing tests**

```python
def test_the_vinculo_and_its_codes(self):  # test_model
    self.assertEqual(self.model["enums"]["vinculo_metodo"], ["CODIGO_RENTAS", "LLAVE_HU_MZ_LOTE", "GEOMETRICO", "MANUAL"])
    self.assertEqual(self.objects["predio_catastral"]["indexes"],
                     [["sector", "manzana", "lote"], ["codigo_cpu"], ["cuc"], ["codigo_referencia_catastral"]])
def test_vinculo_columns(self):  # test_import_fichas
    # "cod_pre,vinculo_metodo,vinculo_revisado,cuc,codigo_referencia_catastral\nA,llave_hu_mz_lote,si,0001,110101-01-001-001\n"
    self.assertEqual([a[k] for k in ("vinculo_metodo", "vinculo_revisado", "cuc")], ["LLAVE_HU_MZ_LOTE", True, "0001"])
    # "B,VECINO,quizas,," → 2 problems
def test_a_changed_vinculo_is_a_cambio(self): ...  # test_entregas: "cambio A: vinculo_revisado False → True"
```

- [ ] **Step 2:** `cd model && python3 -m unittest -v test_model test_import_fichas test_entregas` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** `cd model && python3 apply.py --validate-only && python3 -m unittest -v && cd .. && yarn format:check`
  → PASS.
- [ ] **Step 5: Commit** `feat(model): cómo se vinculó cada ficha con rentas, el CUC y el código de referencia`

### Task 9: The vínculo keys in `/valuaciones`

**Files:**
- Modify: `src/main/kotlin/catastro/valuacion/Fichas.kt`, `Valuaciones.kt`, `ValuacionesService.kt`
- Modify: `README.md` (API: item example and key list, «el cambio es aditivo»)
- Test: `ItemValuacionJsonTest.kt`, `ValuacionesApiTest.kt`

**Interfaces:**
- Produces: `PredioCatastral` gains `vinculoMetodo: String?`, `vinculoRevisado: Boolean?`, `cuc: String?`,
  `codigoReferenciaCatastral: String?`; `ItemValuacion` appends the same four after `entrega`, in that order.

- [ ] **Step 1: Failing unit test:** extend `las llaves … vienen siempre` to the seven contract keys.
- [ ] **Step 2:** `./gradlew test --tests 'catastro.valuacion.ItemValuacionJsonTest'` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** `./gradlew test ktlintCheck` → PASS.
- [ ] **Step 5: Integration test** `el vínculo y los códigos del SNIC llegan a srtm, nulos sin dato`: one predio with
  `vinculo_metodo = GEOMETRICO`, `vinculo_revisado = false`, `cuc = "C-<uniq>"`, `codigo_referencia_catastral =
  "R-<uniq>"`; one without → `assertEquals("GEOMETRICO", …)`, `assertFalse(item["vinculoRevisado"].asBoolean())`,
  and all four `has && isNull` on the other. Run `$PRUEBAS $W testdb-catastro integrationTest --tests
  'catastro.valuacion.ValuacionesApiTest'` → PASS.
- [ ] **Step 6: Commit** `feat(valuacion): cada valuación dice cómo se vinculó la ficha y sus códigos del SNIC`

---

## Issue #25: titulares del levantamiento

Branch: `feat/titulares` — `git checkout -b feat/titulares` from the head of `feat/vinculo-rentas`.

### Task 10: Model for `titular_catastral`

**Files:**
- Modify: `model/model.json`, `model/roles.json` (READ on `titular_catastral`; the description says it holds
  personal data, Ley 29733, and SRTM_LECTOR is its only reader), `model/apply.py` (docstring: 7 objects,
  4 relationships)
- Test: `model/test_model.py`

**Interfaces:**
- Produces: object `titular_catastral` fields in order `codigo_municipal` (TEXT, required), `tipo_documento`,
  `numero_documento`, `nombre` (TEXT), `porcentaje` (DECIMAL), `condicion` (TEXT); `indexes: [["codigo_municipal"]]`;
  relationship `titular_catastral_predio` (source `titular_catastral`, target `predio_catastral`, fieldName
  `predio`, required).

- [ ] **Step 1: Failing tests:** `OBJETOS["titular_catastral"] = ([...six...], {"codigo_municipal"}, set())`;
  `test_children_hang_from_a_required_predio` also checks `titular_catastral_predio`;
  `test_titulares_page_by_codigo_municipal` asserts the index.
- [ ] **Step 2:** `cd model && python3 -m unittest -v test_model test_apply_roles` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** `cd model && python3 apply.py --validate-only && python3 -m unittest -v test_model test_apply_roles
  && cd .. && yarn format:check` → PASS.
- [ ] **Step 5: Commit** `feat(model): titular_catastral, los titulares de cada ficha`

### Task 11: `import_fichas.py --titulares`

**Files:**
- Modify: `model/import_fichas.py` (`TITULAR_COLUMNS`, `titulares_from`, CLI `--titulares`, `--map-titulares`;
  legacy `load` creates missing titulares by key)
- Modify: `model/entregas.py` (`titular_key`, `plan_entrega(..., titulares=None)`, `read_core(titulares=True)`)
- Modify: `README.md` (fichas: `--titulares`, filler documents, the 100 % report, the personal data rule)
- Test: `model/test_import_fichas.py`, `model/test_entregas.py`

**Interfaces:**
- Produces:
  - `TITULAR_COLUMNS = {"codigo_municipal": "cod_pre", "tipo_documento": "tipo_documento", "numero_documento":
    "numero_documento", "nombre": "nombre", "porcentaje": "porcentaje", "condicion": "condicion"}`.
  - `RELLENO = re.compile(r"0+")`; `titulares_from(rows, mapping, codigos) -> (titulares, problems, avisos)`;
    a titular is `(fila, codigo, attributes)` with `codigo_municipal` in its attributes; `avisos` are the report
    lines `titulares <cod> fila <n>: documento de relleno, queda vacío`, `titulares <cod> fila <n>: repetido, se
    carga una vez`, `titulares <cod>: suman <s> %` (sum ≠ 100 ± 0.01, skipped when all porcentajes are empty).
  - `titular_key(predio_id, a) -> (predio_id, numero_documento or "", " ".join(nombre.split()).upper())`.
  - In the plan: missing titular → POST (line `cambio <cod> titular fila <n>: alta`); changed `tipo_documento`,
    `porcentaje`, `condicion` → PATCH (line `cambio <cod> titular fila <n>: <campos separados por coma>`), never
    DELETE.
  - stdout prints `titulares: <n>` and the avisos; never a name or document.

- [ ] **Step 1: Failing tests**

```python
TITULARES = "cod_pre,tipo_documento,numero_documento,nombre,porcentaje,condicion\n" \
            "120302-0001,DNI,00412345,ANA PEREZ QUISPE,50,PROPIETARIO\n" \
            "120302-0001,DNI,00412345,ana  perez quispe,50,PROPIETARIO\n" \
            "120302-0002,DNI,000000000,LUIS ROJAS,,POSEEDOR\n"
def test_the_document_goes_as_it_comes_and_fillers_go_empty(self):
    t, problems, avisos = imf.titulares_from(rows, pm, {"120302-0001", "120302-0002"})
    self.assertEqual(t[0][2]["numero_documento"], "00412345"); self.assertIsNone(t[-1][2]["numero_documento"])
    self.assertIn("titulares 120302-0002 fila 4: documento de relleno, queda vacío", avisos)
def test_a_repeated_titular_loads_once_and_the_sum_is_reported(self):
    self.assertEqual(len([x for x in t if x[1] == "120302-0001"]), 1)
    self.assertFalse([a for a in avisos if a.startswith("titulares 120302-0001: suman")])  # rows as given: 50 + 50
def test_a_predio_at_200_percent_is_reported(self): ...  # two distinct titulares at 100 each → "suman 200 %"
def test_the_report_never_prints_names_or_documents(self):
    code, out, err = self.cli("--titulares", path)
    for secreto in ("ANA", "PEREZ", "00412345", "LUIS"): self.assertNotIn(secreto, out + err)
def test_titulares_hang_from_their_predio_and_carry_its_code(self): ...   # Core attrs predio == id, codigo_municipal
def test_an_entrega_patches_a_changed_porcentaje_and_deletes_no_titular(self): ...
def test_a_titular_of_a_code_outside_the_fichas_is_a_problem(self): ...   # exit 2
```

- [ ] **Step 2:** `cd model && python3 -m unittest -v test_import_fichas test_entregas` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** `cd model && python3 -m unittest -v` → PASS.
- [ ] **Step 5: Commit** `feat(model): import_fichas --titulares carga los titulares sin imprimir datos personales`

### Task 12: Shared integration helpers (`CatastroApiTest`)

**Files:**
- Create: `src/test/kotlin/catastro/CatastroApiTest.kt`
- Modify: `src/test/kotlin/catastro/valuacion/ValuacionesApiTest.kt` (extends it; keeps only its tests and
  `predio`/`piso`/`leerTodo` helpers)
- Modify: `docs/develop/README.md` §6 (the integration classes and how to run them with `pruebas-remotas.sh`)

**Interfaces:**
- Produces: `abstract class CatastroApiTest : WasichaiIntegrationTest()` with `protected lateinit var admin: String`,
  a `@BeforeEach` that applies the model, the roles and region `SELVA`, and protected `region`, `registro`,
  `cuentaDeServicio`, `send`, `exchange`, `arbol`, `JsonNode.lista()` (unique codes use the inherited `uniqueName`).

- [ ] **Step 1: Move** the helpers unchanged (pure refactor; no new test).
- [ ] **Step 2:** `./gradlew compileTestKotlin ktlintCheck` → OK.
- [ ] **Step 3:** `$PRUEBAS $W testdb-catastro integrationTest --tests 'catastro.valuacion.ValuacionesApiTest'` → PASS
  (same count as before).
- [ ] **Step 4: Commit** `test: los ayudantes de las pruebas de integración en CatastroApiTest`

### Task 13: `GET /api/catastro/titulares`

**Files:**
- Create: `src/main/kotlin/catastro/titulares/Titulares.kt` (DTOs), `TitularesService.kt`, `TitularesController.kt`
- Modify: `src/main/kotlin/catastro/valuacion/Fichas.kt` (`TITULAR_CATASTRAL`)
- Modify: `README.md` (API para srtm: the endpoint, its paging, Ley 29733, an example with synthetic data)
- Test: create `src/test/kotlin/catastro/titulares/TitularesApiTest.kt`

**Interfaces:**
- Produces:
  - `@JsonInclude(ALWAYS) data class Titulares(val page: Int, val size: Int, val total: Long, val items: List<ItemTitular>)`;
    `data class ItemTitular(codigoMunicipal: String?, tipoDocumento: String?, numeroDocumento: String?, nombre:
    String?, porcentaje: BigDecimal?, condicion: String?)`.
  - `TitularesService.pagina(page: Int, size: Int): Titulares` — `registros.pagina(TITULAR_CATASTRAL, …,
    RecordQuery(page = PageRequest(page, size), sort = "codigo_municipal"))`.
  - `GET /api/catastro/titulares` params `page` (≥ 0, default 0), `size` (1–500, default 200); unknown parameter →
    `ParametroInvalido` (422), as `ValuacionesController`.

- [ ] **Step 1: Failing integration tests** (`TitularesApiTest : CatastroApiTest()`)

```kotlin
@Test fun `srtm lee los titulares por código municipal y luego por registro`() {
    // predios B-<u> and A-<u>; titulares: two on B, one on A. reads every page with size=1 as SRTM_LECTOR, keeps ours:
    assertEquals(listOf("A-$u", "B-$u", "B-$u"), nuestros.map { it["codigoMunicipal"].asString() })
    assertEquals(setOf("codigoMunicipal", "tipoDocumento", "numeroDocumento", "nombre", "porcentaje", "condicion"), nuestros[0].nombres())
}
@Test fun `sin token 401, sin el rol 403, un parámetro malo 422 que lo nombra`() { /* size=0, size=501, page=-1, x=1 */ }
```

- [ ] **Step 2:** `$PRUEBAS $W testdb-catastro integrationTest --tests 'catastro.titulares.TitularesApiTest'` → FAIL (404).
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** `./gradlew test ktlintCheck` then `$PRUEBAS $W testdb-catastro integrationTest --tests
  'catastro.titulares.TitularesApiTest'` → PASS.
- [ ] **Step 5: Commit** `feat(api): GET /api/catastro/titulares para srtm`

---

## Issue #26: cambios desde un cursor

Branch: `feat/cambios` — `git checkout -b feat/cambios` from the head of `feat/titulares`.

### Task 14: Cursor and the mapping of an audit row

**Files:**
- Create: `src/main/kotlin/catastro/cambios/Cambios.kt`
- Test: create `src/test/kotlin/catastro/cambios/LecturaDeCambiosTest.kt`

**Interfaces:**
- Produces:
  - `data class CursorCambios(val en: Instant, val id: UUID) { fun codificar(): String; companion object { fun
    leer(texto: String): CursorCambios } }` — `leer` throws `ParametroInvalido("desde", "no es un cursor que haya
    devuelto este endpoint")`.
  - `data class FilaBitacora(val id: UUID, val objeto: String, val registro: UUID?, val operacion: String, val en:
    Instant, val antes: Map<String, Any?>?, val despues: Map<String, Any?>?, val razon: String?)`.
  - `@JsonInclude(ALWAYS) data class Cambio(val codigoMunicipal: String?, val objeto: String, val operacion: String,
    val campos: List<String>, val en: Instant, val entrega: String?)`;
    `@JsonInclude(ALWAYS) data class Cambios(val items: List<Cambio>, val cursor: String?, val hayMas: Boolean)`.
  - `object LecturaDeCambios { val OBJETOS = listOf(PREDIO_CATASTRAL, CONSTRUCCION, OBRA_COMPLEMENTARIA,
    TITULAR_CATASTRAL); fun campos(f: FilaBitacora, delObjeto: List<String>): List<String>; fun predioDe(f:
    FilaBitacora): UUID?; fun codigoPropio(f: FilaBitacora): String?; fun cambio(f: FilaBitacora, codigos:
    Map<UUID, String>, entregas: Set<String>): Cambio }`.

- [ ] **Step 1: Failing tests**

```kotlin
@Test fun `el cursor ida y vuelta`() { val c = CursorCambios(Instant.parse("2026-10-25T10:00:00.123456Z"), UUID.randomUUID()); assertEquals(c, CursorCambios.leer(c.codificar())) }
@Test fun `un cursor que no es nuestro es un 422 sobre desde`() { listOf("x", "", base64("c2\n…")).forEach { assertEquals("desde", assertThrows<ParametroInvalido> { CursorCambios.leer(it) }.violations.single().field) } }
@Test fun `un alta lista sus campos con valor, en el orden del objeto`() { assertEquals(listOf("piso", "area_construida"), campos(create(after = mapOf("area_construida" to 1, "piso" to "1", "techos" to null, "id" to "x")), listOf("piso", "area_construida", "techos"))) }
@Test fun `un cambio lista lo que cambió, 10 y 10.0 son lo mismo`() { … }
@Test fun `una baja no lista campos y su predio sale del antes`() { assertEquals(predio, predioDe(delete(before = mapOf("predio" to predio.toString())))) }
@Test fun `la entrega es la razón solo si es una entrega`() { assertNull(cambio(fila(razon = "a mano"), mapOf(), setOf("E-1")).entrega) }
@Test fun `el titular trae su propio código`() { … }
```

- [ ] **Step 2:** `./gradlew test --tests 'catastro.cambios.LecturaDeCambiosTest'` → FAIL.
- [ ] **Step 3: Implement.** `campos` uses `wasichai.core.audit.AuditDiff.changes` for UPDATE.
- [ ] **Step 4:** `./gradlew test --tests 'catastro.cambios.*' ktlintCheck` → PASS.
- [ ] **Step 5: Commit** `feat(cambios): el cursor y la lectura de una fila del audit log`

### Task 15: `GET /api/catastro/cambios`, README and ADR-014

**Files:**
- Create: `src/main/kotlin/catastro/cambios/BitacoraDeCambios.kt`, `CambiosService.kt`, `CambiosController.kt`
- Modify: `README.md` (API para srtm: the endpoint with a request/response example, the cursor rule, the risk)
- Create: `docs/adr/0014-srtm-sigue-los-cambios-por-un-cursor.md`; Modify: `docs/adr/README.md`, the status lines of
  `docs/adr/0003-valorizar-al-vuelo-sin-guardar.md` and `docs/adr/0007-srtm-lee-con-una-cuenta-de-servicio.md`
  (`· enmendada por [ADR-014](…)`)
- Test: create `src/test/kotlin/catastro/cambios/CambiosApiTest.kt`

**Interfaces:**
- Consumes: Task 14 types; `DatabaseClient`, `WasichaiSchemas`, `CurrentUser`, `MetadataService`, `Actions.READ`,
  `Registros.conCampoEn`.
- Produces:
  - `BitacoraDeCambios.filas(organizacion: UUID, desde: CursorCambios?, limite: Int): List<FilaBitacora>` running
    (the `IN` lists are `LecturaDeCambios.OBJETOS` and the three operations, written as literals):

    ```sql
    SELECT a.id, a.object_name, a.record_id, a.operation, a.occurred_at, a.reason,
           a.before_state::text AS before_state, a.after_state::text AS after_state
    FROM ${schemas.metadata}.audit_log a
    WHERE a.organization_id = :organizacion
      AND a.object_name IN ('predio_catastral', 'construccion', 'obra_complementaria', 'titular_catastral')
      AND a.operation IN ('CREATE', 'UPDATE', 'DELETE')
      AND (a.occurred_at, a.id) > (:en, :id)          -- only with desde
    ORDER BY a.occurred_at, a.id
    LIMIT :limite
    ```
  - `BitacoraDeCambios.codigosDePredios(organizacion: UUID, ids: Collection<UUID>): Map<UUID, String>`:

    ```sql
    SELECT DISTINCT ON (a.record_id) a.record_id,
           COALESCE(a.after_state->>'codigo_municipal', a.before_state->>'codigo_municipal') AS codigo
    FROM ${schemas.metadata}.audit_log a
    WHERE a.organization_id = :organizacion AND a.object_name = 'predio_catastral' AND a.record_id = ANY(:ids)
    ORDER BY a.record_id, a.occurred_at DESC, a.id DESC
    ```
  - `CambiosService.pagina(desde: String?, size: Int): Cambios`: `currentUser.require()`; READ on the five objects
    (`metadata.loadDefinition(org, name).obj.id`); reads `size + 1` rows; `hayMas = rows > size`; `cursor` = last
    returned row's, or `desde` unchanged when no rows (null when `desde` was null and the log is empty); field names
    per object from the definitions; entrega codes via `conCampoEn(ENTREGA_CATASTRAL, …, "codigo", razones)`.
  - `GET /api/catastro/cambios` params `desde` (optional), `size` (1–500, default 200); unknown → 422.

- [ ] **Step 1: Failing integration tests** (`CambiosApiTest : CatastroApiTest()`)

```kotlin
@Test fun `un alta, un cambio de piso y la baja de una obra dan tres ítems, sin repetir ni saltar`() {
    // before: entrega E-<u>; predio P-<u> with piso and obra. c0 = cursor after draining /cambios with size=500.
    // then, with X-Change-Reason E-<u>: create predio Q-<u>; PATCH the piso's area_construida; DELETE the obra.
    val todos = leer(token, desde = c0, size = 1).filter { it["codigoMunicipal"].asString().endsWith(u) }
    assertEquals(listOf(Triple("Q-$u", "predio_catastral", "CREATE"), Triple("P-$u", "construccion", "UPDATE"),
        Triple("P-$u", "obra_complementaria", "DELETE")), todos.map { Triple(it["codigoMunicipal"].asString(), it["objeto"].asString(), it["operacion"].asString()) })
    assertEquals(listOf("area_construida"), todos[1]["campos"].lista().map { it.asString() })
    assertEquals("E-$u", todos[0]["entrega"].asString())
    assertEquals(todos, leer(token, desde = c0, size = 500).filter { … })      // same items whatever the size
}
@Test fun `sin nada nuevo vuelve el mismo cursor y hayMas es falso`() { … assertEquals(c1, r["cursor"].asString()); assertTrue(r["items"].isEmpty); assertFalse(r["hayMas"].asBoolean()) }
@Test fun `el predio de una obra borrada junto con su predio sale del audit log`() { … }  // delete obra then predio
@Test fun `sin token 401, sin el rol 403, desde o size malos 422 que lo nombran`() { … }
```

  (`leer` follows `cursor` while `hayMas`.)
- [ ] **Step 2:** `$PRUEBAS $W testdb-catastro integrationTest --tests 'catastro.cambios.CambiosApiTest'` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Docs.** README: request, response example (synthetic), «el cursor es opaco», nothing new → same
  cursor, the missed-change risk and the weekly full run. ADR-014 «aceptada · 2026-10-25 · enmienda ADR-003 y
  ADR-007»: **Contexto** (c4); **Alternativas** (replica/FDW: wasichai's per-organization tables with hot columns
  break it and skip permissions; webhooks: one more delivery to make reliable; srtm on `GET /api/audit`: needs an
  organization-wide READ, knows catastro's model, newest first; a change table in catastro: a second history);
  **Decisión** (the endpoint, its cursor, catastro reads `audit_log` in-process after checking READ on each object;
  ADR-003 keeps valuing on the fly, srtm re-runs only when there were changes; ADR-007's account reads it with the
  same role); **Consecuencias** (a change can be missed — `RecordChanges` does not write record and audit row in one
  transaction, and `occurred_at` is the transaction start — srtm's weekly full run covers it (srtm#203); a wasichai
  upgrade that touches `audit_log` must keep `CambiosApiTest` green; a framework fix is a wasichai issue).
- [ ] **Step 5: Verify:** `./gradlew test ktlintCheck && yarn format:check` and `$PRUEBAS $W testdb-catastro
  integrationTest --tests 'catastro.cambios.CambiosApiTest'` → PASS.
- [ ] **Step 6: Commit** `feat(api): GET /api/catastro/cambios, los cambios del catastro desde un cursor`

---

## Issue #27: predios rústicos

Branch: `fix/rusticos` — `git checkout -b fix/rusticos` from the head of `feat/cambios`.

### Task 16: `tipo_predio` in the model and the loader

**Files:**
- Modify: `model/model.json` (enum `tipo_predio` = `["URBANO", "RUSTICO"]`; `predio_catastral` appends `tipo_predio`
  ENUM, optional), `model/import_fichas.py` (`FICHA_COLUMNS["tipo_predio"] = "tipo_predio"`, parsed with
  `enum_option`), `README.md` (fichas columns)
- Test: `model/test_model.py`, `model/test_import_fichas.py`

- [ ] **Step 1: Failing tests:** `test_tipo_predio_is_urbano_or_rustico` (enum and field); `test_tipo_predio_column`
  (`rustico` → `"RUSTICO"`, empty → `None`, `AGRICOLA` → one problem).
- [ ] **Step 2:** `cd model && python3 -m unittest -v test_model test_import_fichas` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** `cd model && python3 apply.py --validate-only && python3 -m unittest -v && cd .. && yarn format:check`
  → PASS.
- [ ] **Step 5: Commit** `fix(model): el tipo de predio, urbano o rústico`

### Task 17: The engine answers `PREDIO_RUSTICO`; `valuacion-v3`

**Files:**
- Modify: `Valorizacion.kt` (`const val PREDIO_RUSTICO = "PREDIO_RUSTICO"`; second check in `calcular`:
  `if (i.tipoPredio == "RUSTICO") falta(PREDIO_RUSTICO, PREDIO_RUSTICO)`), `PedidoValuacion.kt` (`"tipoPredio"` in
  `CAMPOS`; a text other than `URBANO`/`RUSTICO` → `CampoInvalido("tipoPredio", "debe ser URBANO o RUSTICO")`),
  `Fichas.kt` (`PredioCatastral.tipoPredio`), `ValuacionesService.kt` (`Insumos.tipoPredio` from the ficha;
  `VERSION = "valuacion-v3"`, comment says what v3 changes)
- Modify: `README.md` (version table row `valuacion-v3`: «un predio rústico (`tipo_predio`/`tipoPredio`) sale sin
  valor con `PREDIO_RUSTICO` hasta que haya aranceles rústicos; los urbanos no cambian»; the two `"version"`
  examples; the POST field list; motivos table)
- Test: `ValorizacionTest.kt`, `PedidoValuacionTest.kt`, `ValuacionesApiTest.kt` (version asserts → v3)

- [ ] **Step 1: Failing tests**

```kotlin
@Test fun `un predio rústico no se valoriza con el arancel urbano`() { val v = sinValor(insumos().copy(tipoPredio = "RUSTICO")); assertEquals("PREDIO_RUSTICO", v.llave); assertEquals("PREDIO_RUSTICO", v.motivo) }
@Test fun `un predio urbano, o sin tipo, se valoriza como siempre`() { assertEquals(bd("9100.00"), valorizada(insumos().copy(tipoPredio = "URBANO")).autoavaluo) }
@Test fun `sin levantar gana sobre rústico`() { assertEquals("SIN_LEVANTAMIENTO", sinValor(insumos().copy(levantamiento = "SIN_LEVANTAR", tipoPredio = "RUSTICO")).llave) }
// PedidoValuacionTest
@Test fun `tipoPredio llega al motor y uno desconocido es un 422`() { assertEquals("RUSTICO", PedidoValuacion.leer("""{"anio":2026,"tipoPredio":"RUSTICO"}""").insumos.tipoPredio); assertEquals("tipoPredio", invalido("""{"anio":2026,"tipoPredio":"AGRICOLA"}""").violations.single().field) }
```

- [ ] **Step 2:** `./gradlew test --tests 'catastro.valuacion.ValorizacionTest' --tests 'catastro.valuacion.PedidoValuacionTest'` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** `./gradlew test ktlintCheck` → PASS.
- [ ] **Step 5: Integration test** `un predio rústico sale con PREDIO_RUSTICO por GET y por POST`: a predio with
  `tipo_predio = RUSTICO` → item `motivo == "PREDIO_RUSTICO"`, `autoavaluo` null, `version == "valuacion-v3"`;
  `POST /valuacion {"anio":2026,"areaTerreno":200,"arancelM2":45.5,"tipoPredio":"RUSTICO"}` → same motivo; the
  existing two `valuacion-v2` asserts become `valuacion-v3`. Run `$PRUEBAS $W testdb-catastro integrationTest --tests
  'catastro.valuacion.ValuacionesApiTest'` → PASS.
- [ ] **Step 6: Commit** `fix(valuacion): un predio rústico sale sin valor con PREDIO_RUSTICO (valuacion-v3)`

---

## Issue #10: cargar el catastro de Ica (converter)

Branch: `feat/convertidor-ica` — `git checkout -b feat/convertidor-ica` from the head of `fix/rusticos`.

### Task 18: Converter core: fichas and pisos from the comparison workbook

**Files:**
- Create: `model/convertir_comparacion_ica.py`, `model/test_convertir_comparacion_ica.py`
- Modify: `model/helpers.py` (`write_xlsx_sheets`)

**Interfaces:**
- Consumes: `tabular.read_table(path, sheet)`, `code_text`, `clean_text`, `parse_decimal`, `parse_int`, `enum_option`,
  `parse_map`, `load_enums`.
- Produces:
  - `helpers.write_xlsx_sheets(testcase, sheets: dict[str, tuple[list, list[list]]]) -> path` (one sheet per entry,
    shared strings, as `write_xlsx`).
  - `PREDIO_COLUMNS = {"codigo_municipal": "cod_predio_rentas", "unidad_catastral": "codigo_unidad_catastro",
    "area_terreno": "area_terreno_catastro", "cuc": "cuc_catastro", "urbanizacion": "urbanizacion_catastro"}`
    (`cuc`, `urbanizacion` optional).
  - `CONSTRUCCION_COLUMNS = {"codigo_municipal": "cod_predio", "nivel": "nivel_catastro", "anio_construccion":
    "ano_catastro", "area_construida": "area_construida_nivel_catastro", "material": "material_catastro",
    "estado_conservacion": "estado_conservacion_catastro", "muros_columnas": "muros_catastro", "techos":
    "techos_catastro", "pisos": "pisos_catastro", "puertas_ventanas": "puertas_catastro", "revestimientos":
    "revestimientos_catastro", "banos": "banos_catastro", "instalaciones": "instalaciones_catastro"}`.
  - `MATERIAL_CODES = {"1": "CONCRETO", "2": "LADRILLO", "3": "ADOBE"}`, `ESTADO_CODES = {"1": "MUY BUENO", "2":
    "BUENO", "3": "REGULAR", "4": "MALO"}`, `NIVELES_FUERA = {71, 81}`, `ANIO_MINIMO = 1900`, `ANIO_MAXIMO = 2026`.
  - `fichas_de(predios, con_pisos: set, con_titulares: set, vinculos: dict | None, mapa) -> (list[dict], Counter)`;
    each row has the columns `FICHAS_CSV = ["cod_pre", "cod_sect", "cod_mzn", "cod_lote", "area_terreno", "uso",
    "id_aranc", "estado_levantamiento", "vinculo_metodo", "codigo_referencia_catastral", "cuc"]`.
  - `pisos_de(filas, codigos: set, mapa, enums, anio_maximo=ANIO_MAXIMO) -> (list[dict], Counter)`; columns
    `PISOS_CSV = ["cod_pre", "piso", "seccion", "area_construida", "anio_construccion", "material",
    "estado_conservacion", *CATEGORIAS]`.
  - Counter keys: `predios_sin_vinculo`, `fichas`, `fichas_repetidas`, `fichas_sin_levantar`, `fichas_parciales`,
    `fichas_area_vacia`, `pisos`, `pisos_de_predios_sin_ficha`, `pisos_nivel_71_81`, `niveles_sin_numero`,
    `pisos_en_seccion_2_o_mas`, `anios_vaciados`, `areas_construidas_vaciadas`, `letras_vaciadas`,
    `materiales_vaciados`, `estados_vaciados`.

- [ ] **Step 1: Failing tests** (synthetic workbook; codes like `S-0001`; no real names)

```python
def test_sector_manzana_lote_and_the_reference_code_come_from_the_unidad_catastral(self):
    f = ficha_de(unidad="11-01-01-02-015-007-01-01-01-001")
    self.assertEqual((f["cod_sect"], f["cod_mzn"], f["cod_lote"]), ("02", "015", "007"))
    self.assertEqual(f["codigo_referencia_catastral"], "11-01-01-02-015-007-01-01-01-001")
def test_a_ficha_without_unidad_catastral_is_not_loaded(self): ...       # predios_sin_vinculo == 1
def test_an_empty_ficha_is_sin_levantar_without_the_rentas_area(self):
    self.assertEqual((f["estado_levantamiento"], f["area_terreno"]), ("SIN_LEVANTAR", ""))
def test_area_zero_with_pisos_is_parcial(self): ...                       # "PARCIAL", area ""
def test_uso_and_id_aranc_are_present_and_empty(self):
    self.assertEqual((f["uso"], f["id_aranc"]), ("", ""))
def test_niveles_71_and_81_and_niveles_without_number_are_dropped(self): ...
def test_a_repeated_nivel_becomes_secciones_in_sheet_order(self):
    self.assertEqual([(p["piso"], p["seccion"]) for p in pisos], [("1", 1), ("1", 2), ("2", 1)])
def test_years_outside_1900_2026_area_zero_and_letters_outside_a_j_go_empty(self): ...
def test_numeric_xlsx_codes_are_text(self): ...                           # cod_predio_rentas 1234.0 → "1234"
def test_material_and_estado_codes_become_the_model_options(self): ...    # "1" → CONCRETO, "4" → MALO, "X" → "" counted
def test_a_shared_construccion_goes_to_each_predio(self): ...             # same nivel rows under S-0001 and S-0002 → both kept
```

- [ ] **Step 2:** `cd model && python3 -m unittest -v test_convertir_comparacion_ica` → FAIL.
- [ ] **Step 3: Implement** (stdlib; the `HERE`/`sys.path` preamble of the other commands).
- [ ] **Step 4:** `cd model && python3 -m unittest -v test_convertir_comparacion_ica` → PASS.
- [ ] **Step 5: Commit** `feat(model): convertir_comparacion_ica, fichas y pisos del libro de comparación`

### Task 19: Converter: titulares, vínculos, CLI, README

**Files:**
- Modify: `model/convertir_comparacion_ica.py`, `model/test_convertir_comparacion_ica.py`, `model/test_isolated.py`
  (`COMMANDS` gains the converter)
- Modify: `README.md` (new «Ica: el libro de comparación» under «Modelo y carga»: the rules of c10, the ogr2ogr
  export of the vínculos, the two commands, «la salida va fuera del repositorio»)

**Interfaces:**
- Produces:
  - `TITULAR_COLUMNS = {"codigo_municipal": "cod_predio", "tipo_documento": "tipo_documento_catastro",
    "numero_documento": "numero_documento_catastro", "nombre": "nombre_catastro", "porcentaje":
    "porcentaje_catastro", "condicion": "condicion_catastro"}`; `VINCULO_COLUMNS = {"codigo_municipal":
    "cod_predio_rentas", "metodo": "vinculo_metodo"}`.
  - `titulares_de(filas, codigos, mapa) -> (list[dict], Counter)` (columns `TITULARES_CSV = ["cod_pre",
    "tipo_documento", "numero_documento", "nombre", "porcentaje", "condicion"]`, values via `code_text`/`clean_text`,
    documents untouched); `vinculos_de(filas, mapa, alias: dict[str, str], opciones) -> (dict[str, str], list[str])`.
  - CLI: `--libro`, `--salida`, `--vinculos`, `--map-predio`, `--map-construccion`, `--map-titulares`,
    `--map-vinculos`, `--metodo TEXTO=ENUM` (repeatable), `--anio-maximo` (default 2026), `--model`. Writes
    `fichas.csv`, `pisos.csv`, `titulares.csv` in `--salida`; prints only `<clave>: <n>` lines. Exit 2: missing
    sheet or required column (named), unknown vínculo method, `--salida` inside the repository (realpath under the
    directory above `model/`).

- [ ] **Step 1: Failing tests**

```python
def test_the_vinculo_comes_from_the_csv_and_unlinked_fichas_are_dropped(self): ...  # S-0002 absent → not in fichas.csv
def test_a_method_alias_and_an_unknown_method(self):  # "--metodo", "LOTE VECINO=GEOMETRICO" ok; "OTRO" → exit 2
def test_titulares_pass_as_they_come(self): ...       # "000123" and "000000000" stay; the importer empties fillers
def test_it_prints_counts_only(self):
    code, out, _ = run(conv.main, [...]); self.assertEqual(code, 0)
    self.assertTrue(all(re.fullmatch(r"[a-z0-9_]+: \d+", l) for l in out.splitlines()))
    for secreto in ("ROSA", "00412345"): self.assertNotIn(secreto, out)
def test_a_missing_sheet_or_column_exits_2_naming_it(self): ...
def test_an_output_inside_the_repository_exits_2(self): ...
def test_its_output_is_a_valid_entrega(self):
    # converter → tmp dir; then import_fichas --entrega ICA-T --fecha-corte 2026-10-24 --fuente BARRIDO --fichas …
    # --pisos … --titulares … --dry-run against FakeCore → exit 0 and "alta S-0001" in out
```

- [ ] **Step 2:** `cd model && python3 -m unittest -v test_convertir_comparacion_ica test_isolated` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Verify:** `cd model && python3 -m unittest -v && cd .. && yarn format:check` → PASS.
- [ ] **Step 5: Commit** `feat(model): el libro de comparación de Ica a una entrega, con titulares y vínculo`
