package catastro.valuacion

import catastro.ParametroInvalido
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RequestParam
import org.springframework.web.bind.annotation.RestController

// srtm-backend's door into the catastro: the valuations of a year, page by page. it needs a token (401 without one)
// and READ on the five objects (core's 403 otherwise): the service account `srtm` gets both through SRTM_LECTOR
// (model/roles.json, model/crear_cuenta_srtm.py). a parameter it does not know, or cannot read, is a 422 that names it;
// an organization without its region (configuracion_catastro) is a 409 (RegionNoConfigurada)
@RestController
@RequestMapping("/api/catastro")
class ValuacionesController(
    private val valuaciones: ValuacionesService
) {
    @GetMapping("/valuaciones")
    suspend fun valuaciones(
        @RequestParam params: Map<String, String>
    ): Valuaciones {
        params.keys.firstOrNull { it !in CONOCIDOS }?.let { throw ParametroInvalido(it, "no existe en este endpoint") }
        val anio = params["anio"] ?: throw ParametroInvalido("anio", "es obligatorio")
        return valuaciones.pagina(
            entero("anio", anio, ANIOS),
            params["page"]?.let { entero("page", it, 0..Int.MAX_VALUE) } ?: 0,
            params["size"]?.let { entero("size", it, 1..ValuacionesService.TAMANO_MAXIMO) } ?: ValuacionesService.TAMANO
        )
    }

    // the same valuation for one predio's insumos sent whole, read as the caller like GET /valuaciones (same 401, 403
    // and 409; SRTM_LECTOR is enough: nothing is written). a malformed body is a 422 that names its field
    // (PedidoValuacion). the área común is not supported: the engine has no such insumo, so a predio's share of one
    // is not valued here
    @PostMapping("/valuacion")
    suspend fun valuacion(
        @RequestBody(required = false) cuerpo: String?
    ): ValuacionDeInsumos = valuaciones.valuar(PedidoValuacion.leer(cuerpo))

    private fun entero(
        nombre: String,
        valor: String,
        rango: IntRange
    ): Int =
        valor.trim().toIntOrNull()?.takeIf { it in rango }
            ?: throw ParametroInvalido(nombre, "debe ser un entero entre ${rango.first} y ${rango.last}")

    private companion object {
        val CONOCIDOS = setOf("anio", "page", "size")
        val ANIOS = 1900..2100
    }
}
