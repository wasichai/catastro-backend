package catastro.valuacion

import tools.jackson.databind.PropertyNamingStrategies
import tools.jackson.databind.annotation.JsonNaming
import java.math.BigDecimal

// object and relation names of model/model.json
const val PREDIO_CATASTRAL = "predio_catastral"
const val CONSTRUCCION = "construccion"
const val OBRA_COMPLEMENTARIA = "obra_complementaria"
const val ARANCEL = "arancel"
const val CONFIGURACION_CATASTRO = "configuracion_catastro"
const val ENTREGA_CATASTRAL = "entrega_catastral"
const val TITULAR_CATASTRAL = "titular_catastral"

// the relation field construccion and obra_complementaria hang from
const val PREDIO = "predio"

// the records as core returns them: json keys are the model's field names (snake_case). every field nullable, as the
// admin or a field permission may leave any of them out; the engine turns a missing datum into a motivo

@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy::class)
data class PredioCatastral(
    val id: String,
    val codigoMunicipal: String? = null,
    val codigoCpu: String? = null,
    val sector: String? = null,
    val manzana: String? = null,
    val lote: String? = null,
    val idAranc: String? = null,
    val uso: String? = null,
    val areaTerreno: BigDecimal? = null,
    val longitudFrente: BigDecimal? = null,
    val esEdificio: Boolean? = null,
    // GeoJSON geometry, EPSG:4326 (wasichai-gis transforms it from the column's 32718)
    val loteGeom: Map<String, Any?>? = null,
    // entrega_catastral.id (relation field "entrega"); the last entrega that changed this ficha or a child of it
    val entrega: String? = null,
    // DATE as ISO text ("2026-09-30"); empty when the ficha has not been surveyed yet
    val fechaLevantamiento: String? = null,
    // SIN_LEVANTAR, PARCIAL or COMPLETO; what Valorizacion.calcular reads as Insumos.levantamiento
    val estadoLevantamiento: String? = null,
    // CODIGO_RENTAS, LLAVE_HU_MZ_LOTE, GEOMETRICO or MANUAL: how this ficha was matched to its predio de rentas
    val vinculoMetodo: String? = null,
    // whether a person already reviewed the vínculo; who and when live in the audit log, not here
    val vinculoRevisado: Boolean? = null,
    // Sistema Nacional Integrado de Catastro (Ley 28294) codes, optional
    val cuc: String? = null,
    val codigoReferenciaCatastral: String? = null
)

// material and estado_conservacion come in the model's enum spelling (CONCRETO, MUY BUENO …), which is what
// Valorizacion.materialRnt / estadoRnt read; clasificacion likewise, for Valorizacion.TABLA_POR_CLASIFICACION
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy::class)
data class FichaConstruccion(
    val id: String,
    val predio: String? = null,
    val piso: String? = null,
    val areaConstruida: BigDecimal? = null,
    val anioConstruccion: Int? = null,
    val material: String? = null,
    val estadoConservacion: String? = null,
    val murosColumnas: String? = null,
    val techos: String? = null,
    val puertasVentanas: String? = null,
    val techoIncluido: Boolean? = null,
    val clasificacion: String? = null,
    val seccion: Int? = null
)

@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy::class)
data class FichaObra(
    val id: String,
    val predio: String? = null,
    val codigoVu: String? = null,
    val cantidad: BigDecimal? = null,
    val anioConstruccion: Int? = null,
    val material: String? = null,
    val estadoConservacion: String? = null
)

@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy::class)
data class Arancel(
    val id: String,
    val idAranc: String? = null,
    val anio: Int? = null,
    val valorM2: BigDecimal? = null
)

// the organization's single configuracion_catastro record: the region whose tables value its predios
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy::class)
data class ConfiguracionCatastro(
    val id: String,
    val region: String? = null
)

// just enough of an entrega to name it: the codigo an item's "entrega" key carries, resolved from the predio's
// relation id
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy::class)
data class EntregaCatastral(
    val id: String,
    val codigo: String? = null
)
