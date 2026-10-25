package catastro.vias

import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RequestParam
import org.springframework.web.bind.annotation.RestController
import wasichai.core.common.FieldViolation
import wasichai.core.common.ValidationException
import wasichai.gis.FeatureCollection

// catastro-ui's map of aranceles por vía: every tramo_via as a GeoJSON FeatureCollection in EPSG:4326, each with the
// valor_m2 of its id_aranc for `anio` (the current year in Lima without it). it needs a token (401 without one) and
// READ on tramo_via (core's 403 otherwise); a vía's value also needs READ on arancel. unlike the other endpoints, a
// parameter it cannot read is a 400 that names it (errors[].field): that is the contract catastro-ui is built on
@RestController
@RequestMapping("/api/catastro")
class ViasController(
    private val vias: ViasService
) {
    @GetMapping("/vias/aranceles")
    suspend fun aranceles(
        @RequestParam params: Map<String, String>
    ): FeatureCollection = vias.aranceles(anio(params))

    // recomputes tramo_via.valor_m2 and anio_valor of every tramo for `anio` (the current year in Lima without it): the
    // first fill, and the rollover each 1 January (README, «Vías»). only the organization's admin: 403 otherwise
    @PostMapping("/vias/valores")
    suspend fun valores(
        @RequestParam params: Map<String, String>
    ): ValoresRecalculados = vias.recalcular(anio(params))

    private fun anio(params: Map<String, String>): Int {
        params.keys.firstOrNull { it != "anio" }?.let { throw invalido(it, "no existe en este endpoint") }
        return params["anio"]?.let { valor ->
            valor.trim().toIntOrNull()?.takeIf { it in ANIOS }
                ?: throw invalido("anio", "debe ser un entero entre ${ANIOS.first} y ${ANIOS.last}")
        } ?: anioEnCurso()
    }

    private fun invalido(
        nombre: String,
        razon: String
    ) = ValidationException("El parámetro '$nombre' $razon", listOf(FieldViolation(nombre, razon)))

    private companion object {
        val ANIOS = 1900..2100
    }
}
