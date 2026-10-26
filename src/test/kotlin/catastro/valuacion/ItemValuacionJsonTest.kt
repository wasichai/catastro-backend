package catastro.valuacion

import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import tools.jackson.databind.json.JsonMapper
import java.math.BigDecimal

// the engine's levantamiento and vínculo keys travel in every item, present and null, exactly like motivo/llave; srtm
// reads them without a schema check, so a key missing from the json would pass quietly here and fail over there
class ItemValuacionJsonTest {
    private fun item(
        estadoLevantamiento: String? = null,
        fechaLevantamiento: String? = null,
        entrega: String? = null,
        vinculoMetodo: String? = null,
        vinculoRevisado: Boolean? = null,
        cuc: String? = null,
        codigoReferenciaCatastral: String? = null
    ) = ItemValuacion(
        codigoMunicipal = null,
        codigoCpu = null,
        sector = null,
        manzana = null,
        lote = null,
        uso = null,
        areaTerreno = null,
        areaConstruida = BigDecimal.ZERO,
        longitudFrente = null,
        terreno = null,
        construccion = null,
        obras = null,
        autoavaluo = null,
        motivo = null,
        llave = null,
        loteGeom = null,
        estadoLevantamiento = estadoLevantamiento,
        fechaLevantamiento = fechaLevantamiento,
        entrega = entrega,
        vinculoMetodo = vinculoMetodo,
        vinculoRevisado = vinculoRevisado,
        cuc = cuc,
        codigoReferenciaCatastral = codigoReferenciaCatastral,
        construcciones = emptyList()
    )

    @Test
    fun `las llaves del levantamiento vienen siempre, nulas sin dato`() {
        val json = JsonMapper.builder().build().writeValueAsString(item())
        listOf(
            "estadoLevantamiento",
            "fechaLevantamiento",
            "entrega",
            "vinculoMetodo",
            "vinculoRevisado",
            "cuc",
            "codigoReferenciaCatastral"
        ).forEach { assertTrue(json.contains("\"$it\":null")) }
    }

    @Test
    fun `las llaves del levantamiento llevan su dato cuando lo hay`() {
        val json =
            JsonMapper.builder().build().writeValueAsString(
                item("SIN_LEVANTAR", "2026-09-30", "ENT-1", "GEOMETRICO", false, "C-1", "R-1")
            )
        assertTrue(json.contains("\"estadoLevantamiento\":\"SIN_LEVANTAR\""), json)
        assertTrue(json.contains("\"fechaLevantamiento\":\"2026-09-30\""), json)
        assertTrue(json.contains("\"entrega\":\"ENT-1\""), json)
        assertTrue(json.contains("\"vinculoMetodo\":\"GEOMETRICO\""), json)
        assertTrue(json.contains("\"vinculoRevisado\":false"), json)
        assertTrue(json.contains("\"cuc\":\"C-1\""), json)
        assertTrue(json.contains("\"codigoReferenciaCatastral\":\"R-1\""), json)
    }
}
