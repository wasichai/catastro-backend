package catastro.vias

import tools.jackson.databind.PropertyNamingStrategies
import tools.jackson.databind.annotation.JsonNaming
import wasichai.gis.Feature
import java.math.BigDecimal
import java.time.LocalDate
import java.time.ZoneId

// the object of model/model.json: one frente of a tramo of the eje vial, with the SAT code of its arancel
const val TRAMO_VIA = "tramo_via"

// the municipality's clock: "the current year" of the map and of tramo_via.valor_m2
val LIMA: ZoneId = ZoneId.of("America/Lima")

fun anioEnCurso(): Int = LocalDate.now(LIMA).year

// a tramo_via as core returns it (fields by their model names); geom is wasichai-gis's GeoJSON in EPSG:4326
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy::class)
data class TramoVia(
    val id: String,
    val codViaEje: String? = null,
    val tipVia: String? = null,
    val nomVia: String? = null,
    val cuadra: String? = null,
    val lado: String? = null,
    val idAranc: String? = null,
    val asignacion: String? = null,
    val geom: Map<String, Any?>? = null
)

// one tramo as the map's Feature (GET /api/catastro/vias/aranceles): the year's valor_m2 of its id_aranc, joined on
// read for any year (the tramo's own valor_m2 is a copy of the current year's, for the map view and the WMS layer
// only), so an arancel srtm syncs shows on the map at once. every property is present, null without a datum. null when the tramo has no geometry: there is nothing to draw
internal fun feature(
    tramo: TramoVia,
    anio: Int,
    valorM2: BigDecimal?
): Feature? {
    val geometria = tramo.geom?.let(::geometria) ?: return null
    return Feature(
        id = tramo.id,
        geometry = geometria,
        properties =
            linkedMapOf(
                "cod_via_eje" to tramo.codViaEje,
                "tip_via" to tramo.tipVia,
                "nom_via" to tramo.nomVia,
                "cuadra" to tramo.cuadra,
                "lado" to tramo.lado,
                "id_aranc" to tramo.idAranc,
                "asignacion" to tramo.asignacion,
                "anio" to anio,
                "valor_m2" to valorM2
            )
    )
}

// the column is a MultiLineString (model.json); a one-part one answers as its LineString, the shape most tramos have
private fun geometria(geom: Map<String, Any?>): Map<String, Any?> {
    val partes = geom["coordinates"] as? List<*>
    return if (geom["type"] == "MultiLineString" && partes?.size == 1) {
        mapOf("type" to "LineString", "coordinates" to partes.single())
    } else {
        geom
    }
}
