package catastro.valuacion

import com.fasterxml.jackson.annotation.JsonInclude
import java.math.BigDecimal

// the contract srtm-backend reads (GET /api/catastro/valuaciones): renaming a field breaks srtm's brecha. every key is
// always written, null included
@JsonInclude(JsonInclude.Include.ALWAYS)
data class Valuaciones(
    val anio: Int,
    val version: String,
    // the organization's region (COSTA, SELVA): whose cuadros valued this page
    val region: String,
    val page: Int,
    val size: Int,
    // predios the caller may read, in every page
    val total: Long,
    val items: List<ItemValuacion>
)

// one predio and its autoavalúo of the year. terreno, construccion, obras and autoavaluo are null when the predio is
// not valued; then motivo (for a person) and llave (to group by) say why. areaConstruida is Σ the pisos' declared
// areas (0 when nothing is built). loteGeom is the lote's GeoJSON geometry in EPSG:4326, or null. estadoLevantamiento
// and fechaLevantamiento are the ficha's own fields; entrega is the codigo of its entrega_catastral (null without
// one). vinculoMetodo, vinculoRevisado, cuc and codigoReferenciaCatastral are the ficha's own fields too (ADR-007:
// an aditive change for srtm's brecha con confianza, wasichai/srtm-backend#204). all seven are always written, null
// without data, like motivo and llave
@JsonInclude(JsonInclude.Include.ALWAYS)
data class ItemValuacion(
    val codigoMunicipal: String?,
    val codigoCpu: String?,
    val sector: String?,
    val manzana: String?,
    val lote: String?,
    val uso: String?,
    val areaTerreno: BigDecimal?,
    val areaConstruida: BigDecimal,
    val longitudFrente: BigDecimal?,
    val terreno: BigDecimal?,
    val construccion: BigDecimal?,
    val obras: BigDecimal?,
    val autoavaluo: BigDecimal?,
    val motivo: String?,
    val llave: String?,
    val loteGeom: Map<String, Any?>?,
    val estadoLevantamiento: String?,
    val fechaLevantamiento: String?,
    val entrega: String?,
    val vinculoMetodo: String?,
    val vinculoRevisado: Boolean?,
    val cuc: String?,
    val codigoReferenciaCatastral: String?
)

// the answer of POST /api/catastro/valuacion: one predio's insumos valued as GET /valuaciones values a ficha, plus how
// the engine got there. arancelM2 is the one valued with and origenArancel where it came from (CUERPO, FICHA, or null
// when there was none). terreno, construccion, obras, autoavaluo and detalle are null when the predio is not valued;
// then motivo and llave say why. every key is always written, null included
@JsonInclude(JsonInclude.Include.ALWAYS)
data class ValuacionDeInsumos(
    val anio: Int,
    val version: String,
    val region: String,
    val codigoMunicipal: String?,
    val arancelM2: BigDecimal?,
    val origenArancel: String?,
    val terreno: BigDecimal?,
    val construccion: BigDecimal?,
    val obras: BigDecimal?,
    val autoavaluo: BigDecimal?,
    val motivo: String?,
    val llave: String?,
    val detalle: Detalle?
) {
    companion object {
        const val CUERPO = "CUERPO"
        const val FICHA = "FICHA"
    }
}
