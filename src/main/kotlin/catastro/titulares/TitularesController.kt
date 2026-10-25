package catastro.titulares

import catastro.ParametroInvalido
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RequestParam
import org.springframework.web.bind.annotation.RestController

// srtm-backend's dedicated door into a predio's titulares (contract 2, wasichai/srtm-backend#202): a lighter read
// than the generic record API, which only gives the predio's uuid. it needs a token (401 without one) and READ on
// titular_catastral (core's 403 otherwise): the service account `srtm` gets it through SRTM_LECTOR. a parameter it
// does not know, or out of range, is a 422 that names it, as ValuacionesController
@RestController
@RequestMapping("/api/catastro")
class TitularesController(
    private val titulares: TitularesService
) {
    @GetMapping("/titulares")
    suspend fun titulares(
        @RequestParam params: Map<String, String>
    ): Titulares {
        params.keys.firstOrNull { it !in CONOCIDOS }?.let { throw ParametroInvalido(it, "no existe en este endpoint") }
        return titulares.pagina(
            params["page"]?.let { entero("page", it, 0..Int.MAX_VALUE) } ?: 0,
            params["size"]?.let { entero("size", it, 1..TitularesService.TAMANO_MAXIMO) } ?: TitularesService.TAMANO
        )
    }

    private fun entero(
        nombre: String,
        valor: String,
        rango: IntRange
    ): Int =
        valor.trim().toIntOrNull()?.takeIf { it in rango }
            ?: throw ParametroInvalido(nombre, "debe ser un entero entre ${rango.first} y ${rango.last}")

    private companion object {
        val CONOCIDOS = setOf("page", "size")
    }
}
