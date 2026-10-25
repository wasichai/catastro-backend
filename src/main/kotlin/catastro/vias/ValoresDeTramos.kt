package catastro.vias

import catastro.Copias
import catastro.TablaFisica
import catastro.valuacion.ARANCEL
import org.springframework.r2dbc.core.DatabaseClient
import org.springframework.r2dbc.core.awaitOne
import org.springframework.r2dbc.core.awaitRowsUpdated
import org.springframework.stereotype.Component
import wasichai.core.data.RecordChange
import wasichai.core.data.RecordChangeKind
import wasichai.core.data.RecordChangeListener
import java.util.UUID

// keeps tramo_via.valor_m2 and anio_valor, the copy of the arancel of the current year (America/Lima) that the map
// view aranceles_valor and the WMS layer colour by (model/vistas_de_mapa.py), as wasichai's after-write hook
// (RecordChangeListener, ADR-025): it runs right after every write of a record, on every path (the record api, srtm's
// sync, RecordService in-process, automations), in the caller's transaction when there is one.
// - a write of an arancel of the current year (create, update, delete; on an update both the old and the new id_aranc
//   and anio count) recomputes the tramos of that id_aranc: its valor_m2, or empty when it has none that year;
// - a write of a tramo_via recomputes that tramo, so a tramo whose id_aranc changed gets its value at once.
// an arancel of another year changes nothing; POST /api/catastro/vias/valores recomputes every tramo for a year (the
// first fill, and the rollover of 1 January). it writes through Copias (no audit row, no new version: see there)
@Component
class ValoresDeTramos(
    private val db: DatabaseClient,
    private val copias: Copias
) : RecordChangeListener {
    override suspend fun recordChanged(change: RecordChange) {
        when (change.objectName) {
            ARANCEL -> {
                val anio = anioEnCurso()
                val ids = arancelesDelAnio(change, anio)
                if (ids.isNotEmpty()) recalcular(change.organizationId, anio, aranceles = ids)
            }
            TRAMO_VIA ->
                if (change.kind == RecordChangeKind.CREATED || change.kind == RecordChangeKind.UPDATED) {
                    recalcular(change.organizationId, anioEnCurso(), tramo = change.recordId)
                }
        }
    }

    // writes the valor_m2 of `anio` (and anio_valor, empty with it) on the tramos of the organization: those of
    // `aranceles`, or the one `tramo`, or all of them. only a tramo whose copy differs is written; how many were
    suspend fun recalcular(
        organizacion: UUID,
        anio: Int,
        aranceles: Collection<String>? = null,
        tramo: UUID? = null
    ): Long {
        val (t, a) = tablas(organizacion) ?: return 0
        val filtro =
            buildString {
                if (aranceles != null) append(" AND t.${t.columna(ID_ARANC)} = ANY(:aranceles)")
                if (tramo != null) append(" AND t.id = :tramo")
            }
        // clave (id_aranc|anio) is unique, so an arancel per tramo at most; the LIMIT keeps a malformed clave from
        // doubling a row
        var spec =
            db
                .sql(
                    """
                    WITH v AS (
                        SELECT t.id, a.valor, CASE WHEN a.valor IS NULL THEN NULL ELSE CAST(:anio AS integer) END AS anio
                        FROM ${t.nombre} t
                        LEFT JOIN LATERAL (
                            SELECT ar.${a.columna(VALOR_M2)} AS valor FROM ${a.nombre} ar
                            WHERE ar.organization_id = t.organization_id AND ar.${a.columna(ID_ARANC)} = t.${t.columna(ID_ARANC)}
                              AND ar.${a.columna(ANIO)} = :anioArancel
                            ORDER BY ar.id LIMIT 1
                        ) a ON true
                        WHERE t.organization_id = :organizacion$filtro
                    )
                    UPDATE ${t.nombre} t SET ${t.columna(VALOR_M2)} = v.valor, ${t.columna(ANIO_VALOR)} = v.anio
                    FROM v
                    WHERE t.id = v.id AND t.organization_id = :organizacionTramo
                      AND (t.${t.columna(VALOR_M2)} IS DISTINCT FROM v.valor OR t.${t.columna(ANIO_VALOR)} IS DISTINCT FROM v.anio)
                    """.trimIndent()
                ).bind("anio", anio)
                .bind("anioArancel", anio)
                .bind("organizacion", organizacion)
                .bind("organizacionTramo", organizacion)
        if (aranceles != null) spec = spec.bind("aranceles", aranceles.distinct().toTypedArray())
        if (tramo != null) spec = spec.bind("tramo", tramo)
        return spec.fetch().awaitRowsUpdated()
    }

    // how many tramos the organization has, and how many with a valor_m2
    suspend fun conteo(organizacion: UUID): Pair<Long, Long> {
        val (t, _) = tablas(organizacion) ?: return 0L to 0L
        return db
            .sql("SELECT count(*) AS tramos, count(${t.columna(VALOR_M2)}) AS con_valor FROM ${t.nombre} WHERE organization_id = :organizacion")
            .bind("organizacion", organizacion)
            .map { row, _ -> (row.get("tramos") as Number).toLong() to (row.get("con_valor") as Number).toLong() }
            .awaitOne()
    }

    private suspend fun tablas(organizacion: UUID): Pair<TablaFisica, TablaFisica>? {
        val tramos = copias.tabla(organizacion, TRAMO_VIA, listOf(ID_ARANC, VALOR_M2, ANIO_VALOR)) ?: return null
        val aranceles = copias.tabla(organizacion, ARANCEL, listOf(ID_ARANC, ANIO, VALOR_M2)) ?: return null
        return tramos to aranceles
    }

    private companion object {
        const val ID_ARANC = "id_aranc"
        const val VALOR_M2 = "valor_m2"
        const val ANIO_VALOR = "anio_valor"
        const val ANIO = "anio"
    }
}

// the id_aranc an arancel's write touched in `anio`: the one it had and the one it has, when their anio is `anio`
internal fun arancelesDelAnio(
    change: RecordChange,
    anio: Int
): Set<String> =
    listOfNotNull(change.before, change.after)
        .filter { it["anio"]?.toString()?.trim()?.toIntOrNull() == anio }
        .mapNotNull { it["id_aranc"]?.toString()?.trim()?.ifEmpty { null } }
        .toSet()
