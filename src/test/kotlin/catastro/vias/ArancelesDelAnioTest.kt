package catastro.vias

import catastro.valuacion.ARANCEL
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test
import wasichai.core.data.RecordChange
import wasichai.core.data.RecordChangeKind
import java.util.UUID

// which id_aranc an arancel's write makes ValoresDeTramos recompute: the ones of the current year, before and after
class ArancelesDelAnioTest {
    @Test
    fun `un alta del año cuenta, una de otro año no`() {
        assertEquals(setOf("A-01"), arancelesDelAnio(cambio(RecordChangeKind.CREATED, after = arancel("A-01", 2026L)), 2026))
        assertEquals(emptySet<String>(), arancelesDelAnio(cambio(RecordChangeKind.CREATED, after = arancel("A-01", 2027L)), 2026))
    }

    @Test
    fun `una baja cuenta por lo que tenía`() {
        assertEquals(setOf("A-01"), arancelesDelAnio(cambio(RecordChangeKind.DELETED, before = arancel("A-01", 2026L)), 2026))
    }

    @Test
    fun `un cambio de id_aranc o de año recalcula el viejo y el nuevo del año`() {
        assertEquals(
            setOf("A-01", "A-02"),
            arancelesDelAnio(cambio(RecordChangeKind.UPDATED, before = arancel("A-01", 2026L), after = arancel("A-02", 2026L)), 2026)
        )
        // moved to another year: its tramos lose this year's value
        assertEquals(
            setOf("A-01"),
            arancelesDelAnio(cambio(RecordChangeKind.UPDATED, before = arancel("A-01", 2026L), after = arancel("A-01", 2027L)), 2026)
        )
    }

    @Test
    fun `el año llega como número o como texto, y un id_aranc vacío no cuenta`() {
        assertEquals(setOf("A-01"), arancelesDelAnio(cambio(RecordChangeKind.CREATED, after = arancel("A-01", "2026")), 2026))
        assertEquals(setOf("A-01"), arancelesDelAnio(cambio(RecordChangeKind.CREATED, after = arancel("A-01", 2026)), 2026))
        assertEquals(emptySet<String>(), arancelesDelAnio(cambio(RecordChangeKind.CREATED, after = arancel(" ", 2026L)), 2026))
        assertEquals(emptySet<String>(), arancelesDelAnio(cambio(RecordChangeKind.CREATED, after = mapOf("anio" to 2026L)), 2026))
    }

    private fun arancel(
        idAranc: String,
        anio: Any
    ): Map<String, Any?> = mapOf("clave" to "$idAranc|$anio", "id_aranc" to idAranc, "anio" to anio, "valor_m2" to 1)

    private fun cambio(
        kind: RecordChangeKind,
        before: Map<String, Any?>? = null,
        after: Map<String, Any?>? = null
    ) = RecordChange(UUID.randomUUID(), null, UUID.randomUUID(), ARANCEL, UUID.randomUUID(), kind, before, after)
}
