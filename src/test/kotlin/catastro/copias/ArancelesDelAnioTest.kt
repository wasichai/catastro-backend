package catastro.copias

import catastro.brechas.BRECHA_FICHA
import catastro.brechas.CORTE_BRECHA
import catastro.brechas.DECISION_BRECHA
import catastro.valuacion.ARANCEL
import catastro.vias.TRAMO_VIA
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import wasichai.core.data.RecordChange
import wasichai.core.data.RecordChangeKind
import java.math.BigDecimal
import java.util.UUID

// which writes nudge CopiasDelMapa (AvisosDeCopias), and what a copy should hold: pure, no database
class ArancelesDelAnioTest {
    private val usuario = UUID.randomUUID()

    @Test
    fun `un alta del año cuenta, una de otro año no`() {
        assertEquals(setOf("A-01"), arancelesDelAnio(cambio(ARANCEL, RecordChangeKind.CREATED, after = arancel("A-01", 2026L)), 2026))
        assertEquals(emptySet<String>(), arancelesDelAnio(cambio(ARANCEL, RecordChangeKind.CREATED, after = arancel("A-01", 2027L)), 2026))
    }

    @Test
    fun `una baja cuenta por lo que tenía, y un cambio por el viejo y el nuevo`() {
        assertEquals(setOf("A-01"), arancelesDelAnio(cambio(ARANCEL, RecordChangeKind.DELETED, before = arancel("A-01", 2026L)), 2026))
        assertEquals(
            setOf("A-01", "A-02"),
            arancelesDelAnio(cambio(ARANCEL, RecordChangeKind.UPDATED, before = arancel("A-01", 2026L), after = arancel("A-02", 2026L)), 2026)
        )
        assertEquals(
            setOf("A-01"),
            arancelesDelAnio(cambio(ARANCEL, RecordChangeKind.UPDATED, before = arancel("A-01", 2026L), after = arancel("A-01", 2027L)), 2026)
        )
    }

    @Test
    fun `el año llega como número o como texto, y un id_aranc vacío no cuenta`() {
        assertEquals(setOf("A-01"), arancelesDelAnio(cambio(ARANCEL, RecordChangeKind.CREATED, after = arancel("A-01", "2026")), 2026))
        assertEquals(setOf("A-01"), arancelesDelAnio(cambio(ARANCEL, RecordChangeKind.CREATED, after = arancel("A-01", 2026)), 2026))
        assertEquals(emptySet<String>(), arancelesDelAnio(cambio(ARANCEL, RecordChangeKind.CREATED, after = arancel(" ", 2026L)), 2026))
    }

    @Test
    fun `avisan las escrituras que cambian una copia, y nunca las del propio job`() {
        assertTrue(avisa(cambio(ARANCEL, RecordChangeKind.CREATED, after = arancel("A-01", 2026L)), 2026))
        assertFalse(avisa(cambio(ARANCEL, RecordChangeKind.CREATED, after = arancel("A-01", 2027L)), 2026))
        assertTrue(avisa(cambio(TRAMO_VIA, RecordChangeKind.CREATED, after = mapOf("id_aranc" to "A")), 2026))
        assertTrue(avisa(cambio(TRAMO_VIA, RecordChangeKind.UPDATED, before = mapOf("id_aranc" to "A"), after = mapOf("id_aranc" to "B")), 2026))
        assertFalse(avisa(cambio(TRAMO_VIA, RecordChangeKind.UPDATED, before = mapOf("id_aranc" to "A"), after = mapOf("id_aranc" to "A")), 2026))
        assertTrue(avisa(cambio(DECISION_BRECHA, RecordChangeKind.UPDATED), 2026))
        assertTrue(avisa(cambio(CORTE_BRECHA, RecordChangeKind.UPDATED, before = mapOf("cargado_en" to null), after = mapOf("cargado_en" to "x")), 2026))
        assertTrue(avisa(cambio(CORTE_BRECHA, RecordChangeKind.DELETED, before = mapOf("cargado_en" to "x")), 2026))
        assertTrue(avisa(cambio(BRECHA_FICHA, RecordChangeKind.UPDATED, before = mapOf("estado" to "A"), after = mapOf("estado" to "B")), 2026))
        assertFalse(avisa(cambio(BRECHA_FICHA, RecordChangeKind.UPDATED, before = mapOf("estado" to "A"), after = mapOf("estado" to "A")), 2026))
        assertFalse(avisa(cambio("predio_catastral", RecordChangeKind.CREATED), 2026))
        // the platform (the job's own copies): no nudge, or every run would ask for the next
        assertFalse(avisa(cambio(DECISION_BRECHA, RecordChangeKind.UPDATED).copy(userId = null), 2026))
    }

    @Test
    fun `la copia de un tramo es el valor del año de su arancel, y nada si ya lo es`() {
        val valores = mapOf("A" to BigDecimal("356.00"))
        assertNull(copiaDeTramo(CopiaDeTramo("t", "A", BigDecimal("356"), 2026), valores, 2026))
        assertEquals(
            mapOf("valor_m2" to BigDecimal("356.00"), "anio_valor" to 2026),
            copiaDeTramo(CopiaDeTramo("t", "A", BigDecimal("300"), 2026), valores, 2026)
        )
        assertEquals(
            mapOf("valor_m2" to BigDecimal("356.00"), "anio_valor" to 2026),
            copiaDeTramo(CopiaDeTramo("t", "A", BigDecimal("356"), 2025), valores, 2026)
        )
        assertEquals(mapOf("valor_m2" to null, "anio_valor" to null), copiaDeTramo(CopiaDeTramo("t", "B", BigDecimal("1"), 2026), valores, 2026))
        assertNull(copiaDeTramo(CopiaDeTramo("t", null, null, null), valores, 2026))
    }

    @Test
    fun `la copia de una ficha es el estado de su decisión, PENDIENTE sin una`() {
        val decididos = mapOf("P1" to "A_FISCALIZAR")
        assertNull(copiaDeFicha(CopiaDeFicha("f", "P1", "A_FISCALIZAR"), decididos))
        assertEquals(mapOf("estado" to "A_FISCALIZAR"), copiaDeFicha(CopiaDeFicha("f", "P1", "PENDIENTE"), decididos))
        assertEquals(mapOf("estado" to "PENDIENTE"), copiaDeFicha(CopiaDeFicha("f", "P2", null), decididos))
        assertEquals(mapOf("estado" to "PENDIENTE"), copiaDeFicha(CopiaDeFicha("f", null, "DESCARTADO"), decididos))
    }

    private fun arancel(
        idAranc: String,
        anio: Any
    ): Map<String, Any?> = mapOf("clave" to "$idAranc|$anio", "id_aranc" to idAranc, "anio" to anio, "valor_m2" to 1)

    private fun cambio(
        objeto: String,
        kind: RecordChangeKind,
        before: Map<String, Any?>? = null,
        after: Map<String, Any?>? = null
    ) = RecordChange(UUID.randomUUID(), usuario, UUID.randomUUID(), objeto, UUID.randomUUID(), kind, before, after)
}
