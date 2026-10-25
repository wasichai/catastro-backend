package catastro

import org.springframework.stereotype.Component
import wasichai.core.common.NotFoundException
import wasichai.core.metadata.MetadataService
import wasichai.core.platform.SqlIdentifier
import wasichai.core.platform.WasichaiSchemas
import java.util.UUID

// the copies catastro keeps of another object's value, so that a map view and a WMS layer of wasichai-gis can colour
// an object by its own field (ADR-072 colours only by those): tramo_via.valor_m2 and anio_valor (the arancel of the
// year) and brecha_ficha.estado (the decision). they are written with one UPDATE on the physical table, not through
// RecordService, because
// - the caller does not hold UPDATE on the copy: srtm's SRTM_LECTOR writes the aranceles and CATASTRO_ANALISTA the
//   decisions, and neither may write a tramo or a ficha. RecordService.asPlatform is refused inside a request
//   (ADR-039), and widening their roles would open the generic record api to them;
// - a copy is not a change of the catastro: it leaves no audit row (so GET /api/catastro/cambios, which reads the audit
//   log, never lists it), no updated_by and no new updated_at (the record's version, ADR-051, stays).
// the physical table is internal api (ADR-024), as audit_log is for BitacoraDeCambios; wasichai-gis's StyleClassService
// reads it the same way (schemas.dataTable, organization_id)
@Component
class Copias(
    private val metadata: MetadataService,
    private val schemas: WasichaiSchemas
) {
    // the physical table of `objeto` and the quoted columns of `campos`, or null when the organization lacks the object
    // or one of the fields: a model not applied yet copies nothing, and never fails the write that triggered the copy
    suspend fun tabla(
        organizacion: UUID,
        objeto: String,
        campos: Collection<String>
    ): TablaFisica? {
        val definicion =
            try {
                metadata.loadDefinition(organizacion, objeto)
            } catch (_: NotFoundException) {
                return null
            }
        val columnas = campos.associateWith { campo -> definicion.fields.firstOrNull { it.name == campo }?.columnName ?: return null }
        return TablaFisica(schemas.dataTable(definicion.obj.physicalTable), columnas.mapValues { SqlIdentifier.quote(it.value) })
    }
}

// a table as sql takes it: the qualified name and a quoted column per field name
class TablaFisica(
    val nombre: String,
    private val columnas: Map<String, String>
) {
    fun columna(campo: String): String = columnas.getValue(campo)
}
