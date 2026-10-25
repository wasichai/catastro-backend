package catastro.cambios

import catastro.ParametroInvalido
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RequestParam
import org.springframework.web.bind.annotation.RestController

// srtm-backend follows the catastro's changes here (contract 3, wasichai/srtm-backend#202; ADR-014): an alta, cambio
// or baja of a predio, a construccion, an obra or a titular, oldest first, after the cursor it got last time. it needs
// a token (401 without one) and SRTM_LECTOR's READ (core's 403 otherwise). a parameter it does not know, a size out
// of range or a desde this endpoint did not write is a 422 that names it, as ValuacionesController
@RestController
@RequestMapping("/api/catastro")
class CambiosController(
    private val cambios: CambiosService
) {
    @GetMapping("/cambios")
    suspend fun cambios(
        @RequestParam params: Map<String, String>
    ): Cambios {
        params.keys.firstOrNull { it !in CONOCIDOS }?.let { throw ParametroInvalido(it, "no existe en este endpoint") }
        return cambios.pagina(
            params["desde"],
            params["size"]?.let { entero("size", it, 1..CambiosService.TAMANO_MAXIMO) } ?: CambiosService.TAMANO
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
        val CONOCIDOS = setOf("desde", "size")
    }
}
