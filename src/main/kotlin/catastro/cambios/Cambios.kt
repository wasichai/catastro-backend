package catastro.cambios

import catastro.ParametroInvalido
import catastro.valuacion.CONSTRUCCION
import catastro.valuacion.OBRA_COMPLEMENTARIA
import catastro.valuacion.PREDIO
import catastro.valuacion.PREDIO_CATASTRAL
import catastro.valuacion.TITULAR_CATASTRAL
import com.fasterxml.jackson.annotation.JsonInclude
import wasichai.core.audit.AuditDiff
import java.time.DateTimeException
import java.time.Instant
import java.util.Base64
import java.util.UUID

// the contract srtm-backend reads (GET /api/catastro/cambios, contract 3 of wasichai/srtm-backend#202): what changed
// in the catastro since a cursor, oldest first, read from wasichai's audit_log. every key is always written, null
// included, like Valuaciones
@JsonInclude(JsonInclude.Include.ALWAYS)
data class Cambios(
    val items: List<Cambio>,
    // what the caller passes as desde next time; the same desde back when nothing is new, null only when the log is
    // empty and no desde came
    val cursor: String?,
    val hayMas: Boolean
)

// one audit row as srtm reads it: names only, never values. codigoMunicipal is null when it cannot be resolved (a
// child whose predio never reached the audit log); entrega is the row's reason only when it is an entrega's codigo
@JsonInclude(JsonInclude.Include.ALWAYS)
data class Cambio(
    val codigoMunicipal: String?,
    val objeto: String,
    // CREATE, UPDATE or DELETE
    val operacion: String,
    val campos: List<String>,
    // ISO-8601 instant (jackson 3 writes java.time as text)
    val en: Instant,
    val entrega: String?
)

// the position after the last row returned: rows go by (occurred_at, id) ascending, and the next page starts strictly
// after it. opaque to srtm: base64url without padding of "c1\n<occurred_at ISO>\n<id>", "c1" being its version
data class CursorCambios(
    val en: Instant,
    val id: UUID
) {
    fun codificar(): String = Base64.getUrlEncoder().withoutPadding().encodeToString("$VERSION\n$en\n$id".toByteArray(Charsets.UTF_8))

    companion object {
        private const val VERSION = "c1"

        // only a text this endpoint wrote is accepted: whatever decodes must encode back to the same text, which rules
        // out padding, another spelling of the instant or the uuid, and a future version
        fun leer(texto: String): CursorCambios {
            val cursor =
                try {
                    val partes = String(Base64.getUrlDecoder().decode(texto), Charsets.UTF_8).split("\n")
                    if (partes.size == 3 && partes[0] == VERSION) CursorCambios(Instant.parse(partes[1]), UUID.fromString(partes[2])) else null
                } catch (_: IllegalArgumentException) {
                    null
                } catch (_: DateTimeException) {
                    null
                }
            if (cursor == null || cursor.codificar() != texto) {
                throw ParametroInvalido("desde", "no es un cursor que haya devuelto este endpoint")
            }
            return cursor
        }
    }
}

// one row of ${schemas.metadata}.audit_log, its states already read from jsonb into maps keyed by field name
data class FilaBitacora(
    val id: UUID,
    // object_name
    val objeto: String,
    // record_id
    val registro: UUID?,
    // CREATE, UPDATE or DELETE
    val operacion: String,
    // occurred_at
    val en: Instant,
    // before_state, null on a CREATE
    val antes: Map<String, Any?>?,
    // after_state, null on a DELETE
    val despues: Map<String, Any?>?,
    // reason: X-Change-Reason, the entrega's codigo when a loader wrote it
    val razon: String?
)

// one audit row read as an item of the contract, without touching the database: the service brings the rows, the
// predios' codes and the entregas' codigos
object LecturaDeCambios {
    // the objects whose changes srtm follows
    val OBJETOS = listOf(PREDIO_CATASTRAL, CONSTRUCCION, OBRA_COMPLEMENTARIA, TITULAR_CATASTRAL)

    private const val CODIGO_MUNICIPAL = "codigo_municipal"

    // the objects that borrow their predio's code through the predio relation
    private val HIJOS = setOf(CONSTRUCCION, OBRA_COMPLEMENTARIA)

    // the objects that carry codigo_municipal themselves (a titular's is a copy of its predio's)
    private val CON_CODIGO = setOf(PREDIO_CATASTRAL, TITULAR_CATASTRAL)

    // the fields a row touched, restricted to the object's fields (delObjeto, in definition order) so that id,
    // timestamps and other system keys never show: an alta lists the fields it set, a cambio the ones whose value
    // differs (AuditDiff compares numbers by value, so 10 and 10.0 are the same), a baja none
    fun campos(
        f: FilaBitacora,
        delObjeto: List<String>
    ): List<String> {
        val tocados: Set<String> =
            when (f.operacion) {
                "CREATE" ->
                    f.despues
                        .orEmpty()
                        .filterValues { it != null }
                        .keys
                "UPDATE" -> AuditDiff.changes(f.antes, f.despues).map { it.field }.toSet()
                else -> emptySet()
            }
        return delObjeto.filter { it in tocados }
    }

    // the predio of a construccion or an obra: from the state after the change, or from the one before for a baja.
    // null for the objects that carry their own code, and when the relation is empty or not a uuid
    fun predioDe(f: FilaBitacora): UUID? {
        if (f.objeto !in HIJOS) return null
        val valor = f.despues?.get(PREDIO) ?: f.antes?.get(PREDIO) ?: return null
        return try {
            UUID.fromString(valor.toString())
        } catch (_: IllegalArgumentException) {
            null
        }
    }

    // the codigo_municipal of a predio or a titular, from its own state (the one before for a baja)
    fun codigoPropio(f: FilaBitacora): String? {
        if (f.objeto !in CON_CODIGO) return null
        return (f.despues?.get(CODIGO_MUNICIPAL) ?: f.antes?.get(CODIGO_MUNICIPAL))?.toString()
    }

    // codigos: predio id → its codigo_municipal, from the latest audit state of each predio (so a deleted predio still
    // resolves); entregas: the codigos of the entregas that exist; camposDe: object name → its field names, in
    // definition order
    fun cambio(
        f: FilaBitacora,
        codigos: Map<UUID, String>,
        entregas: Set<String>,
        camposDe: Map<String, List<String>>
    ): Cambio =
        Cambio(
            codigoMunicipal = codigoPropio(f) ?: predioDe(f)?.let { codigos[it] },
            objeto = f.objeto,
            operacion = f.operacion,
            campos = campos(f, camposDe[f.objeto].orEmpty()),
            en = f.en,
            entrega = f.razon?.takeIf { it in entregas }
        )
}
