package catastro.cambios

import io.r2dbc.spi.Row
import kotlinx.coroutines.flow.toList
import org.springframework.r2dbc.core.DatabaseClient
import org.springframework.r2dbc.core.flow
import org.springframework.stereotype.Component
import tools.jackson.core.type.TypeReference
import tools.jackson.databind.ObjectMapper
import wasichai.core.platform.Rows
import wasichai.core.platform.WasichaiSchemas
import java.util.UUID

// wasichai's audit_log read in-process, as GET /api/audit cannot serve srtm (it demands an organization-wide READ and
// goes newest first, ADR-014). it checks no permission: CambiosService does that first. this is the one place that
// knows audit_log's columns, pinned by CambiosApiTest
@Component
class BitacoraDeCambios(
    private val db: DatabaseClient,
    private val schemas: WasichaiSchemas,
    private val json: ObjectMapper
) {
    // the organization's alta, cambio and baja rows of the objects srtm follows, by (occurred_at, id) ascending,
    // strictly after `desde` (from the start without it), at most `limite`
    suspend fun filas(
        organizacion: UUID,
        desde: CursorCambios?,
        limite: Int
    ): List<FilaBitacora> {
        val despues = if (desde == null) "" else "\n  AND (a.occurred_at, a.id) > (:en, :id)"
        var spec =
            db
                .sql(
                    """
                    SELECT a.id, a.object_name, a.record_id, a.operation, a.occurred_at, a.reason,
                           a.before_state::text AS before_state, a.after_state::text AS after_state
                    FROM ${schemas.metadata}.audit_log a
                    WHERE a.organization_id = :organizacion
                      AND a.object_name IN ('predio_catastral', 'construccion', 'obra_complementaria', 'titular_catastral')
                      AND a.operation IN ('CREATE', 'UPDATE', 'DELETE')$despues
                    ORDER BY a.occurred_at, a.id
                    LIMIT :limite
                    """.trimIndent()
                ).bind("organizacion", organizacion)
                .bind("limite", limite)
        // occurred_at is a timestamptz in microseconds: read as an Instant it keeps them all, so the cursor binds back
        // the very value the row holds
        if (desde != null) spec = spec.bind("en", desde.en).bind("id", desde.id)
        return spec.map { row, _ -> fila(row) }.flow().toList()
    }

    // predio id → its codigo_municipal in the latest audit state of that predio, a deleted one included (its baja
    // keeps it in before_state). a predio the log never saw is absent
    suspend fun codigosDePredios(
        organizacion: UUID,
        ids: Collection<UUID>
    ): Map<UUID, String> {
        if (ids.isEmpty()) return emptyMap()
        return db
            .sql(
                """
                SELECT DISTINCT ON (a.record_id) a.record_id,
                       COALESCE(a.after_state->>'codigo_municipal', a.before_state->>'codigo_municipal') AS codigo
                FROM ${schemas.metadata}.audit_log a
                WHERE a.organization_id = :organizacion AND a.object_name = 'predio_catastral' AND a.record_id = ANY(:ids)
                ORDER BY a.record_id, a.occurred_at DESC, a.id DESC
                """.trimIndent()
            ).bind("organizacion", organizacion)
            .bind("ids", ids.distinct().toTypedArray())
            .map { row, _ -> Rows.uuid(row, "record_id") to Rows.stringOrNull(row, "codigo") }
            .flow()
            .toList()
            .mapNotNull { (id, codigo) -> codigo?.let { id to it } }
            .toMap()
    }

    private fun fila(row: Row): FilaBitacora =
        FilaBitacora(
            id = Rows.uuid(row, "id"),
            objeto = Rows.string(row, "object_name"),
            registro = Rows.uuidOrNull(row, "record_id"),
            operacion = Rows.string(row, "operation"),
            en = Rows.instantOrNull(row, "occurred_at")!!,
            antes = estado(Rows.stringOrNull(row, "before_state")),
            despues = estado(Rows.stringOrNull(row, "after_state")),
            razon = Rows.stringOrNull(row, "reason")
        )

    private fun estado(texto: String?): Map<String, Any?>? = texto?.let { json.readValue(it, ESTADO) }

    private companion object {
        val ESTADO = object : TypeReference<Map<String, Any?>>() {}
    }
}
