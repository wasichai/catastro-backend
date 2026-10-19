package catastro.valuacion

import catastro.tablas.Region
import catastro.tablas.Tablas
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.math.BigDecimal

// the engine with the costa tables (anexo I.2) against real niveles of the Municipalidad de Ica's padrón
// (PADRON_CONSTRUCCION.xlsx, sheet construcciones, read 2026-10-20; no contribuyente or predio code is copied here).
// the padrón prices muros C + techos C + puertas F at 764.04 = 387.43 + 285.80 + 90.81 (anexo I.2), and its
// valor_total_nivel is (valor_unitario + incremento_5) x (1 - dep%) x área. its codes, read against the RNT:
// clasificacion_construccion 1-4 is the RNT tabla 01-04, material_predominante 1 concreto, 2 ladrillo, 3 adobe,
// estado_de_conservacion 1-4 muy bueno to malo, antigüedad 2026 - año: with them the depreciation implied by
// valor_total_nivel is the RNT's in 3742 of its 3755 niveles (the '*' cells as D3). its depreciacion column is not:
// it lags a tramo behind in a third of the rows, so the tests compare the total, never that column
class ValorizacionCostaTest {
    private val costa = Tablas.de(Region.COSTA)

    private fun bd(valor: String) = BigDecimal(valor)

    // one nivel of the padrón as the only construction of a predio, muros C, techos C, puertas F. the uso picks the
    // RNT tabla the padrón's clasificacion_construccion names (uso-tabla-depreciacion.csv: 010101 -> 01, 020301 -> 02,
    // 020401 -> 03). terreno is not the padrón's: only construccion is compared
    private fun nivel(
        uso: String,
        material: String,
        estado: String,
        anio: Int,
        area: String
    ) = Insumos(
        anio = 2026,
        areaTerreno = bd("100"),
        arancelM2 = bd("10"),
        uso = uso,
        esEdificio = false,
        construcciones = listOf(Construccion("1", bd(area), anio, material, estado, 'C', 'C', 'F')),
        obras = emptyList()
    )

    private fun construccion(i: Insumos): BigDecimal {
        val v = Valorizacion.valorizar(i, costa)
        assertTrue(v is Valuacion.Valorizada) { "se esperaba un valor y salió $v" }
        return (v as Valuacion.Valorizada).construccion
    }

    private fun sinValor(
        i: Insumos,
        t: Tablas = costa
    ): Valuacion.SinValorizar {
        val v = Valorizacion.valorizar(i, t)
        assertTrue(v is Valuacion.SinValorizar) { "se esperaba un motivo y salió $v" }
        return v as Valuacion.SinValorizar
    }

    @Test
    fun `cinco niveles del padrón de Ica - mismo valor_total_nivel`() {
        // clasificación 1, ladrillo, muy bueno, 2023, 127.20 m2: tabla 01 Ladrillo Muy Bueno hasta 5 = 0 %
        // 764.04 x 127.20 = 97185.888 -> 97185.89 (padrón: 97185.89)
        assertEquals(bd("97185.89"), construccion(nivel("010101", "LADRILLO", "MUY BUENO", 2023, "127.2")))
        // clasificación 1, ladrillo, regular, 1974, 129 m2: antigüedad 52, tabla 01 Ladrillo Regular más de 50 = 50 %
        // 764.04 x 0.50 x 129 = 49280.58 (padrón: 49280.58; su columna depreciacion dice 47)
        assertEquals(bd("49280.58"), construccion(nivel("010101", "LADRILLO", "REGULAR", 1974, "129")))
        // clasificación 2, ladrillo, bueno, 2004, 9.50 m2: antigüedad 22, tabla 02 Ladrillo Bueno hasta 25 = 24 %
        // 764.04 x 0.76 x 9.50 = 5516.3688 -> 5516.37 (padrón: 5516.37; su columna depreciacion dice 20)
        assertEquals(bd("5516.37"), construccion(nivel("020301", "LADRILLO", "BUENO", 2004, "9.5")))
        // clasificación 3, ladrillo, bueno, 2003, 101 m2: antigüedad 23, tabla 03 Ladrillo Bueno hasta 25 = 25 %
        // 764.04 x 0.75 x 101 = 57876.03 (padrón: 57876.03)
        assertEquals(bd("57876.03"), construccion(nivel("020401", "LADRILLO", "BUENO", 2003, "101")))
        // clasificación 1, concreto, muy bueno, 2016, 63.45 m2: antigüedad 10, tabla 01 Concreto Muy Bueno hasta 10 = 0 %
        // 764.04 x 63.45 = 48478.338 -> 48478.34 (padrón: 48478.34)
        assertEquals(bd("48478.34"), construccion(nivel("010101", "CONCRETO", "MUY BUENO", 2016, "63.45")))
    }

    @Test
    fun `el padrón de Ica redondea el VU depreciado antes del área - el motor no`() {
        // clasificación 1, ladrillo, bueno, 2022, 114.89 m2: antigüedad 4, tabla 01 Ladrillo Bueno hasta 5 = 8 %.
        // motor: 764.04 x 0.92 x 114.89 = 80758.1112 -> 80758.11. padrón: 80758.48 = round(764.04 x 0.92, 2) = 702.92,
        // x 114.89. the same rounding explains 3653 of its 3712 niveles; the engine keeps perené's arithmetic (open)
        assertEquals(bd("80758.11"), construccion(nivel("010101", "LADRILLO", "BUENO", 2022, "114.89")))
    }

    @Test
    fun `una celda de puntos de la costa no es cero`() {
        // anexo I.2: muros H is «......»
        val i = nivel("010101", "LADRILLO", "BUENO", 2016, "50").let { it.copy(construcciones = listOf(it.construcciones[0].copy(muros = 'H'))) }
        val v = sinValor(i)
        assertEquals("VU_SIN_VALOR:MUROS_COLUMNAS:H", v.llave)
        assertTrue(v.motivo.contains("costa"), v.motivo)
    }

    @Test
    fun `la categoría J no está en el cuadro de la costa`() {
        val i = nivel("010101", "LADRILLO", "BUENO", 2016, "50").let { it.copy(construcciones = listOf(it.construcciones[0].copy(techos = 'J'))) }
        val v = sinValor(i)
        assertEquals("CATEGORIA_INVALIDA:TECHOS:J", v.llave)
        assertTrue(v.motivo.contains("A a I"), v.motivo)
    }

    @Test
    fun `sin cuadro de obras de la región una obra no se valoriza, no se salta`() {
        val sinObras = Tablas(costa.region, costa.valoresUnitarios, costa.depreciaciones, null, costa.usos, costa.parametros)
        val muro = Obra("MUROS PERIMETRICOS O CERCOS|1", bd("30"), 2016, "CONCRETO", "BUENO")
        val v = sinValor(nivel("010101", "LADRILLO", "BUENO", 2016, "50").copy(obras = listOf(muro)), sinObras)
        assertEquals("OBRAS_SIN_CUADRO:COSTA", v.llave)
        assertTrue(v.motivo.contains("obras-complementarias-costa-2026.csv"), v.motivo)
        // without obras the same predio has a value: 764.04 x (1 - 0.11, tabla 01 Ladrillo Bueno hasta 10) x 50 = 33999.78
        assertEquals(bd("33999.78"), (Valorizacion.valorizar(nivel("010101", "LADRILLO", "BUENO", 2016, "50"), sinObras) as Valuacion.Valorizada).construccion)
    }
}
