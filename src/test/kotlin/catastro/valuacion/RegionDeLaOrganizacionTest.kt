package catastro.valuacion

import catastro.RegionNoConfigurada
import catastro.tablas.Region
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows

// which region an organization's configuracion_catastro records give: exactly one, with a region the engine has
// tables for. anything else is RegionNoConfigurada, never a default
class RegionDeLaOrganizacionTest {
    private fun config(region: String?) = ConfiguracionCatastro("id-$region", region)

    private fun falla(configuraciones: List<ConfiguracionCatastro>): String {
        val error = assertThrows<RegionNoConfigurada> { ValuacionesService.regionDe(configuraciones) }
        return error.message.orEmpty()
    }

    @Test
    fun `un registro con una región conocida`() {
        assertEquals(Region.COSTA, ValuacionesService.regionDe(listOf(config("COSTA"))))
        assertEquals(Region.SELVA, ValuacionesService.regionDe(listOf(config("SELVA"))))
    }

    @Test
    fun `sin registro`() {
        assertTrue(falla(emptyList()).contains("no hay un registro"))
    }

    @Test
    fun `dos registros, aunque digan lo mismo`() {
        assertTrue(falla(listOf(config("SELVA"), config("SELVA"))).contains("más de un registro"))
    }

    @Test
    fun `una región del modelo sin tablas en el motor`() {
        // an option added to region_catastro before its tables
        val mensaje = falla(listOf(config("SIERRA")))
        assertTrue(mensaje.contains("«SIERRA»") && mensaje.contains("sin tablas"), mensaje)
    }

    @Test
    fun `un registro sin región, o que quien llama no puede leer`() {
        val mensaje = falla(listOf(config(null)))
        assertTrue(mensaje.contains("no tiene región") && mensaje.contains("no puede leer"), mensaje)
    }
}
