package catastro.valuacion

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test

// core sorts the construcciones by piso only: the secciones of a piso must come in a fixed order too, so a predio's
// first missing datum (its motivo) is the same on every call
class PorSeccionTest {
    private fun ficha(
        piso: String,
        seccion: Int?
    ) = FichaConstruccion(id = "$piso/$seccion", piso = piso, seccion = seccion)

    @Test
    fun `las secciones de un piso van por número, sin mover los pisos`() {
        // core's order of the pisos ("10" before "2" as text) is kept; null is seccion 1
        val deCore = listOf(ficha("10", 2), ficha("10", null), ficha("2", 3), ficha("2", 1), ficha("S1", null))
        assertEquals(listOf("10/null", "10/2", "2/1", "2/3", "S1/null"), porSeccion(deCore).map { it.id })
    }
}
