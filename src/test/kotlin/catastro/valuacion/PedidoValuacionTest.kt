package catastro.valuacion

import catastro.CampoInvalido
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import java.math.BigDecimal

// the body of POST /api/catastro/valuacion read into the engine's Insumos: a blank datum stays null (the engine's
// motivo), a malformed one is a 422 that names its field
class PedidoValuacionTest {
    private fun invalido(cuerpo: String?): CampoInvalido = assertThrows<CampoInvalido> { PedidoValuacion.leer(cuerpo) }

    @Test
    fun `un cuerpo completo llega al motor tal cual`() {
        val pedido =
            PedidoValuacion.leer(
                """
                {"anio": 2026, "areaTerreno": 200, "arancelM2": 45.50, "uso": "010101", "esEdificio": true,
                 "construcciones": [{"piso": "5", "areaConstruida": 50.5, "anioConstruccion": 2016, "material": "CONCRETO",
                   "estado": "MUY BUENO", "muros": "D", "techos": "A", "puertas": "J", "techoIncluido": true,
                   "clasificacion": "EDIFICIO-OFICINAS", "seccion": 2}],
                 "obras": [{"codigoVu": "MUROS PERIMETRICOS O CERCOS|1", "cantidad": 30, "anioConstruccion": 2016,
                   "material": "CONCRETO", "estado": "BUENO"}],
                 "codigoMunicipal": "0101001"}
                """.trimIndent()
            )
        val i = pedido.insumos
        assertEquals(2026, i.anio)
        assertEquals(0, BigDecimal("45.50").compareTo(i.arancelM2))
        assertEquals("010101", i.uso)
        assertTrue(i.esEdificio)
        assertEquals(
            Construccion("5", BigDecimal("50.5"), 2016, "CONCRETO", "MUY BUENO", 'D', 'A', 'J', true, "EDIFICIO-OFICINAS", 2),
            i.construcciones.single()
        )
        assertEquals(Obra("MUROS PERIMETRICOS O CERCOS|1", BigDecimal("30"), 2016, "CONCRETO", "BUENO"), i.obras.single())
        assertEquals("0101001", pedido.codigoMunicipal)
    }

    @Test
    fun `lo que no viene, o viene nulo, queda nulo para que el motor diga el motivo`() {
        val pedido = PedidoValuacion.leer("""{"anio": 2026, "arancelM2": null, "construcciones": [{"piso": "1"}]}""")
        val i = pedido.insumos
        assertNull(i.areaTerreno)
        assertNull(i.arancelM2)
        assertNull(i.uso)
        assertEquals(false, i.esEdificio)
        assertTrue(i.obras.isEmpty())
        assertEquals(Construccion("1", null, null, null, null, null, null, null), i.construcciones.single())
        assertNull(pedido.codigoMunicipal)
    }

    @Test
    fun `un cuerpo mal formado es un 422 que nombra el campo`() {
        for ((cuerpo, campo) in listOf(
            null to "cuerpo",
            "" to "cuerpo",
            "no es json" to "cuerpo",
            "[]" to "cuerpo",
            "{}" to "anio",
            """{"anio": "2026"}""" to "anio",
            """{"anio": 2026.5}""" to "anio",
            """{"anio": 1800}""" to "anio",
            """{"anio": 2026, "areaTerreno": "200"}""" to "areaTerreno",
            """{"anio": 2026, "esEdificio": "si"}""" to "esEdificio",
            """{"anio": 2026, "uso": 10101}""" to "uso",
            """{"anio": 2026, "otro": 1}""" to "otro",
            """{"anio": 2026, "construcciones": {}}""" to "construcciones",
            """{"anio": 2026, "construcciones": [{}]}""" to "construcciones[0].piso",
            """{"anio": 2026, "construcciones": [{"piso": " "}]}""" to "construcciones[0].piso",
            """{"anio": 2026, "construcciones": [{"piso": "1"}, {"piso": "2", "muros": "CC"}]}""" to "construcciones[1].muros",
            """{"anio": 2026, "construcciones": [{"piso": "1", "techos": "K"}]}""" to "construcciones[0].techos",
            """{"anio": 2026, "construcciones": [{"piso": "1", "puertas": "e"}]}""" to "construcciones[0].puertas",
            """{"anio": 2026, "construcciones": [{"piso": "1", "seccion": 0}]}""" to "construcciones[0].seccion",
            """{"anio": 2026, "construcciones": [{"piso": "1", "pisos": 1}]}""" to "construcciones[0].pisos",
            """{"anio": 2026, "obras": [{"cantidad": "x"}]}""" to "obras[0].cantidad",
            """{"anio": 2026, "codigoMunicipal": 1}""" to "codigoMunicipal"
        )) {
            val e = invalido(cuerpo)
            assertEquals(campo, e.violations.single().field, "$cuerpo: ${e.message}")
            assertTrue(e.message!!.startsWith("El campo '$campo' "), e.message)
        }
    }

    @Test
    fun `las letras son una sola de la A a la J`() {
        assertTrue(invalido("""{"anio": 2026, "construcciones": [{"piso": "1", "muros": "K"}]}""").message!!.contains("A a la J"))
    }
}
