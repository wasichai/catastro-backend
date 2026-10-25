package catastro.brechas

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.math.BigDecimal

// the pure side of the brechas API: the filters, the orders, the panel and the csv, without core
class BrechasTest {
    private fun ficha(
        id: String,
        codigo: String?,
        categoria: String,
        delta: String?,
        confianza: String? = "CONFIABLE",
        sector: String? = "01",
        supera: Boolean? = null,
        estado: String? = null
    ) = fila(
        BrechaFicha(
            id = id,
            codigoCatastro = codigo,
            codigoMunicipal = codigo,
            categoria = categoria,
            confianza = confianza,
            sector = sector,
            deltaImpuesto = delta?.let(::BigDecimal),
            supera5Uit = supera
        ),
        estado?.let { DecisionBrecha(id = "d$id", codigoMunicipal = codigo, estado = it) },
        conGeometria = codigo != null
    )

    private val filas =
        listOf(
            ficha("a", "1", "SUBVALUADO", "100.5000000000", supera = true),
            ficha("b", "2", "OMISO", "-200", confianza = null, sector = "02", estado = "A_FISCALIZAR"),
            ficha("c", null, "SIN_CATASTRO", null, confianza = "DUDOSO", sector = null)
        )

    @Test
    fun `un filtro deja pasar solo lo que cumple todo`() {
        assertEquals(listOf("a"), filas.filter(Filtro(categorias = setOf("SUBVALUADO", "COINCIDE"))::admite).map { it.id })
        assertEquals(listOf("b"), filas.filter(Filtro(estados = setOf("A_FISCALIZAR"))::admite).map { it.id })
        assertEquals(listOf("a", "c"), filas.filter(Filtro(estados = setOf(PENDIENTE))::admite).map { it.id })
        assertEquals(listOf("b", "c"), filas.filter(Filtro(supera5Uit = false)::admite).map { it.id })
        // |Δ|, and a ficha without Δ never passes min_delta
        assertEquals(listOf("b"), filas.filter(Filtro(minDelta = BigDecimal("150"))::admite).map { it.id })
        assertEquals(listOf("a", "b"), filas.filter(Filtro(minDelta = BigDecimal.ZERO)::admite).map { it.id })
        assertEquals(filas, filas.filter(Filtro()::admite))
    }

    @Test
    fun `los órdenes dejan lo vacío al final`() {
        assertEquals(listOf("a", "b", "c"), filas.sortedWith(Orden.DELTA_DESC.comparador).map { it.id })
        assertEquals(listOf("b", "a", "c"), filas.sortedWith(Orden.DELTA_ASC.comparador).map { it.id })
        assertEquals(listOf("a", "b", "c"), filas.sortedWith(Orden.CODIGO.comparador).map { it.id })
        assertEquals(Orden.CODIGO, Orden.de("codigo"))
        assertEquals(null, Orden.de("precio"))
    }

    @Test
    fun `el panel cuenta todo en una pasada`() {
        val p = panel(Vista(CorteBrecha(id = "x", clave = "o|2026-10-25", anio = 2026), filas))
        assertEquals(3, p.kpis.fichas)
        assertEquals(BigDecimal("-99.5"), p.kpis.deltaImpuesto)
        assertEquals(BigDecimal("100.5"), p.kpis.deltaImpuestoConfiable)
        assertEquals(BigDecimal("-200"), p.kpis.omisosEstimado)
        assertEquals(1, p.kpis.supera5Uit)
        assertEquals(2, p.kpis.pendientes)
        assertEquals(2, p.kpis.conGeometria)
        assertEquals(CATEGORIAS, p.porCategoria.map { it.clave })
        // a ficha without confianza is its own entry, after the model's three
        assertEquals(listOf("CONFIABLE", "DUDOSO", "SIN_LEVANTAR", null), p.porConfianza.map { it.clave })
        assertEquals(ESTADOS, p.porEstado.map { it.clave })
        assertEquals(listOf("01", "02"), p.topSectores.map { it.sector })
    }

    @Test
    fun `un decimal sin ceros de sobra ni exponente`() {
        assertEquals("100.5", BigDecimal("100.5000000000").limpio().toPlainString())
        assertEquals("100", BigDecimal("100.0000000000").limpio().toString())
    }

    @Test
    fun `el csv lleva bom, crlf y comillas donde hacen falta`() {
        val texto = String(csv(filas.take(1)), Charsets.UTF_8)
        assertTrue(texto.startsWith("\uFEFFid,codigo_catastro,"), texto)
        val lineas = texto.removePrefix("\uFEFF").split("\r\n")
        assertEquals(FilaFicha.COLUMNAS.size, lineas[1].split(",").size)
        assertTrue(lineas[1].startsWith("a,1,1,,SUBVALUADO,CONFIABLE,"), lineas[1])
        assertTrue(lineas[1].contains(",100.5,"), lineas[1])
        val conComa = filas[0].copy(nota = "uno, \"dos\"")
        assertTrue(String(csv(listOf(conComa)), Charsets.UTF_8).contains(",\"uno, \"\"dos\"\"\","))
        assertFalse(texto.contains("null"))
    }
}
