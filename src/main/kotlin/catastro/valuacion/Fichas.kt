package catastro.valuacion

import tools.jackson.databind.PropertyNamingStrategies
import tools.jackson.databind.annotation.JsonNaming
import java.math.BigDecimal

// object and relation names of model/model.json
const val PREDIO_CATASTRAL = "predio_catastral"
const val CONSTRUCCION = "construccion"
const val OBRA_COMPLEMENTARIA = "obra_complementaria"
const val ARANCEL = "arancel"

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
    val loteGeom: Map<String, Any?>? = null
)

// material and estado_conservacion come in the model's enum spelling (CONCRETO, MUY BUENO …), which is what
// Valorizacion.materialRnt / estadoRnt read
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
    val puertasVentanas: String? = null
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
