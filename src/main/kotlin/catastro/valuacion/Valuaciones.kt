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
// areas (0 when nothing is built). loteGeom is the lote's GeoJSON geometry in EPSG:4326, or null
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
    val loteGeom: Map<String, Any?>?
)
