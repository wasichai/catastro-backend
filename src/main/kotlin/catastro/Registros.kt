package catastro

import org.springframework.stereotype.Component
import tools.jackson.databind.DeserializationFeature
import tools.jackson.databind.json.JsonMapper
import tools.jackson.module.kotlin.KotlinModule
import wasichai.core.common.PageRequest
import wasichai.core.common.PageResponse
import wasichai.core.data.RecordCriterion
import wasichai.core.data.RecordQuery
import wasichai.core.data.RecordResponse
import wasichai.core.data.RecordService
import java.util.UUID

// wasichai's RecordService read as the caller, with catastro's dtos on it (the minimal read side of srtm-backend's
// Registros). RecordService checks the caller's object and field permissions, so nothing here repeats that: a role
// without READ gets core's 403, a field it may not read comes back absent (null in the dto)
@Component
class Registros(
    private val records: RecordService
) {
    // one page, with core's total
    suspend fun <T : Any> pagina(
        objectName: String,
        type: Class<T>,
        query: RecordQuery
    ): PageResponse<T> = records.list(objectName, query).map { read(type, it) }

    // every record whose `campo` is one of `valores` (a relation's ids as UUIDs, or a text field's values), and that
    // meets `filters`: one keyset pass (no COUNT, no OFFSET) per MAX_SIZE values, so a page of predios costs one query
    // per child object instead of one per predio
    suspend fun <T : Any> conCampoEn(
        objectName: String,
        type: Class<T>,
        campo: String,
        valores: Collection<Any>,
        filters: Map<String, String> = emptyMap(),
        sort: String? = null
    ): List<T> =
        valores.distinct().chunked(PageRequest.MAX_SIZE).flatMap { grupo ->
            val enGrupo =
                RecordCriterion { definition, bind ->
                    val columna = "\"${definition.fields.first { it.name == campo }.columnName}\""
                    "$columna = ANY(${bind(arreglo(grupo))})"
                }
            todas(
                objectName,
                RecordQuery(page = PageRequest.of(0, PageRequest.MAX_SIZE), sort = sort, filters = filters, criteria = listOf(enGrupo), count = false)
            ).map { read(type, it) }
        }

    // every record of `ids`, read whole, one query per MAX_SIZE ids: a page's predios point at a handful of entregas,
    // cheaper to fetch once by id than per predio
    suspend fun <T : Any> porIds(
        objectName: String,
        type: Class<T>,
        ids: Collection<UUID>
    ): List<T> =
        ids.distinct().chunked(PageRequest.MAX_SIZE).flatMap { grupo ->
            records.list(objectName, RecordQuery(page = PageRequest.of(0, PageRequest.MAX_SIZE), ids = grupo, count = false)).content.map { read(type, it) }
        }

    // every record of an object, in one keyset pass sorted by `sort` (no COUNT, no OFFSET): for a layer drawn whole,
    // such as the tramos de vía of the map
    suspend fun <T : Any> todas(
        objectName: String,
        type: Class<T>,
        sort: String
    ): List<T> = todas(objectName, RecordQuery(page = PageRequest.of(0, PageRequest.MAX_SIZE), sort = sort, count = false)).map { read(type, it) }

    private suspend fun todas(
        objectName: String,
        primera: RecordQuery
    ): List<RecordResponse> {
        val rows = mutableListOf<RecordResponse>()
        var query = primera
        while (true) {
            val result = records.list(objectName, query)
            rows += result.content
            query = query.copy(after = result.nextCursor ?: return rows)
        }
    }

    // postgres needs a typed array: uuid[] for a relation, text[] for a text field
    private fun arreglo(valores: List<Any>): Array<*> =
        if (valores.all { it is java.util.UUID }) valores.map { it as java.util.UUID }.toTypedArray() else valores.map { it.toString() }.toTypedArray()

    // a geometry travels in core's "geometries" section (wasichai-gis, GeoJSON in EPSG:4326), not in the attributes:
    // the dtos carry it as one more field
    private fun <T : Any> read(
        type: Class<T>,
        response: RecordResponse
    ): T = JSON.convertValue(response.attributes + response.sections[GEOMETRIES].orEmpty() + ("id" to response.id), type)

    companion object {
        // wasichai-gis's section name (wasichai.gis.GEOMETRIES)
        const val GEOMETRIES = "geometries"

        // core reads DECIMAL as BigDecimal, INTEGER as Long (Int in a dto), a relation as the id string. a field the dto
        // does not know is ignored
        private val JSON: JsonMapper =
            JsonMapper
                .builder()
                .addModule(KotlinModule.Builder().build())
                .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                .build()
    }
}
