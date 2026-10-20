package catastro.valuacion

import catastro.tablas.Region
import catastro.tablas.Tablas
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.math.BigDecimal

// how the engine got to its totals, piso by piso and obra by obra: the cases of ValorizacionTest and
// ValorizacionCostaTest, with the same hand-worked figures. Σ valor is always the total the predio already had
class DetalleTest {
    private val selva = Tablas.de(Region.SELVA)
    private val costa = Tablas.de(Region.COSTA)

    private fun bd(valor: String) = BigDecimal(valor)

    private fun igual(
        esperado: String,
        actual: BigDecimal
    ) = assertEquals(0, bd(esperado).compareTo(actual), "$esperado != $actual")

    private fun piso(
        piso: String = "1",
        area: String = "100",
        anio: Int = 2016,
        material: String = "CONCRETO",
        estado: String = "BUENO",
        muros: Char = 'C',
        techos: Char = 'D',
        puertas: Char = 'E',
        clasificacion: String? = null,
        seccion: Int? = null
    ) = Construccion(piso, bd(area), anio, material, estado, muros, techos, puertas, null, clasificacion, seccion)

    private val muro = Obra("MUROS PERIMETRICOS O CERCOS|1", bd("30"), 2016, "CONCRETO", "BUENO")

    private fun valorizada(
        i: Insumos,
        t: Tablas = selva
    ): Valuacion.Valorizada {
        val v = Valorizacion.valorizar(i, t)
        assertTrue(v is Valuacion.Valorizada) { "se esperaba un valor y salió $v" }
        return v as Valuacion.Valorizada
    }

    private fun insumos(
        construcciones: List<Construccion> = emptyList(),
        obras: List<Obra> = emptyList(),
        uso: String = "010101",
        esEdificio: Boolean = false
    ) = Insumos(2026, bd("200"), bd("45.50"), uso, esEdificio, construcciones, obras)

    @Test
    fun `un terreno sin construir no tiene detalle`() {
        val v = valorizada(insumos())
        assertTrue(v.detalle.pisos.isEmpty())
        assertTrue(v.detalle.obras.isEmpty())
    }

    @Test
    fun `todo junto - el piso y la obra con sus pasos`() {
        // casa de un piso: VU 829.28, tabla 01 Concreto Bueno hasta 10 = 5 %, 829.28 x 0.95 = 787.816; x 100 = 78781.60
        // muro: 457.72 x 30 x Fo 0.68 x 0.95 = 8870.61 (ValorizacionTest)
        val v = valorizada(insumos(listOf(piso()), listOf(muro)))
        val p = v.detalle.pisos.single()
        assertEquals("1", p.piso)
        assertEquals(null, p.seccion)
        igual("100", p.areaConstruida)
        igual("829.28", p.valorUnitario)
        igual("0", p.incremento)
        assertEquals("01", p.tablaDepreciacion)
        assertEquals(10, p.antiguedad)
        igual("5", p.porcentajeDepreciacion)
        igual("787.816", p.valorUnitarioDepreciado)
        igual("78781.60", p.valor)

        val o = v.detalle.obras.single()
        assertEquals("MUROS PERIMETRICOS O CERCOS|1", o.codigoVu)
        igual("30", o.cantidad)
        igual("457.72", o.valorUnitario)
        igual("0.68", o.factorOficializacion)
        assertEquals("01", o.tablaDepreciacion)
        assertEquals(10, o.antiguedad)
        igual("5", o.porcentajeDepreciacion)
        igual("8870.61", o.valor)
        igual("96752.21", v.autoavaluo)
    }

    @Test
    fun `el quinto piso de un edificio lleva su incremento, el cuarto no`() {
        // VU 1610.76; piso 5: 1610.76 x 1.05 = 1691.298, incremento 80.538; tabla 03 Concreto Muy Bueno hasta 5 = 0 %
        val dos =
            listOf("4", "5").map {
                piso(piso = it, area = "50", anio = 2021, estado = "MUY BUENO", muros = 'B', techos = 'A', puertas = 'A')
            }
        val v = valorizada(insumos(dos, uso = "020401", esEdificio = true))
        val (cuarto, quinto) = v.detalle.pisos
        igual("0", cuarto.incremento)
        igual("80538.00", cuarto.valor)
        igual("1610.76", quinto.valorUnitario)
        igual("80.538", quinto.incremento)
        assertEquals("03", quinto.tablaDepreciacion)
        igual("0", quinto.porcentajeDepreciacion)
        igual("84564.90", quinto.valor)
        igual("165102.90", v.construccion)
    }

    @Test
    fun `la costa redondea el incremento y el VU depreciado al céntimo, como el padrón de Ica`() {
        // padrón: valor_unitario 764.04, incremento_5 38.20; round(802.24 x 0.77, 2) = 617.72; x 32 = 19767.04
        val i =
            Insumos(
                2026,
                bd("100"),
                bd("10"),
                "010101",
                true,
                listOf(piso(piso = "5", area = "32", anio = 2000, material = "LADRILLO", muros = 'C', techos = 'C', puertas = 'F')),
                emptyList()
            )
        val p = valorizada(i, costa).detalle.pisos.single()
        igual("764.04", p.valorUnitario)
        igual("38.20", p.incremento)
        assertEquals(26, p.antiguedad)
        igual("23", p.porcentajeDepreciacion)
        igual("617.72", p.valorUnitarioDepreciado)
        igual("19767.04", p.valor)
    }

    @Test
    fun `cada construcción con su tabla y su sección`() {
        // piso 1 CLINICAS... = tabla 04, 10 %: 74635.20; piso 2, sección 2, sin clasificación: tabla 01, 5 %: 78781.60
        val v =
            valorizada(
                insumos(
                    listOf(
                        piso(clasificacion = "CLINICAS HOSPITALES CINES INDUSTRIAS COLEGIOS TALLERES"),
                        piso(piso = "2", seccion = 2)
                    )
                )
            )
        val (uno, dos) = v.detalle.pisos
        assertEquals("04", uno.tablaDepreciacion)
        igual("10", uno.porcentajeDepreciacion)
        igual("74635.20", uno.valor)
        assertEquals("01", dos.tablaDepreciacion)
        assertEquals(2, dos.seccion)
        igual("78781.60", dos.valor)
        igual("153416.80", v.construccion)
    }

    @Test
    fun `la celda asterisco muestra el último porcentaje publicado`() {
        // ADOBE MUY MALO 1980: antigüedad 46, '*' -> 90 %; VU 128.74 x 0.10 = 12.874; x 40 = 514.96
        val v =
            valorizada(
                insumos(listOf(piso(area = "40", anio = 1980, material = "ADOBE", estado = "MUY MALO", muros = 'H', techos = 'H', puertas = 'H')))
            )
        val p = v.detalle.pisos.single()
        assertEquals(46, p.antiguedad)
        igual("90", p.porcentajeDepreciacion)
        igual("514.96", p.valor)
    }

    @Test
    fun `un año sin tablas no se valoriza con otro año`() {
        // only 2026 ships: 2027 (or 2025) is a motivo, never 2026's figures
        for (anio in listOf(2025, 2027)) {
            val v = Valorizacion.valorizar(insumos(listOf(piso()), listOf(muro)).copy(anio = anio), selva)
            assertEquals("PARAMETRO_FALTANTE:PORCENTAJE_ACTUALIZACION:$anio", (v as Valuacion.SinValorizar).llave)
        }
    }
}
