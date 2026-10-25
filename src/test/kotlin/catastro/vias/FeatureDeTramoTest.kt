package catastro.vias

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Test
import java.math.BigDecimal

// a tramo_via as the map's Feature: its geometry, its properties (all present, null without a datum) and the year's value
class FeatureDeTramoTest {
    private val parte = listOf(listOf(-75.73, -14.07), listOf(-75.729, -14.07))

    @Test
    fun `un MultiLineString de una parte sale como su LineString`() {
        val f = feature(tramo(mapOf("type" to "MultiLineString", "coordinates" to listOf(parte))), 2026, BigDecimal("356.00"))!!
        assertEquals(mapOf("type" to "LineString", "coordinates" to parte), f.geometry)
        assertEquals("t1", f.id)
        assertEquals("Feature", f.type)
    }

    @Test
    fun `uno de varias partes sale tal cual`() {
        val geom = mapOf("type" to "MultiLineString", "coordinates" to listOf(parte, parte))
        assertEquals(geom, feature(tramo(geom), 2026, null)!!.geometry)
    }

    @Test
    fun `las propiedades del contrato, en su orden, con el año y el valor`() {
        val f = feature(tramo(mapOf("type" to "MultiLineString", "coordinates" to listOf(parte))), 2027, null)!!
        assertEquals(
            listOf("cod_via_eje", "tip_via", "nom_via", "cuadra", "lado", "id_aranc", "asignacion", "anio", "valor_m2"),
            f.properties.keys.toList()
        )
        assertEquals("026220", f.properties["cod_via_eje"])
        assertNull(f.properties["cuadra"])
        assertEquals(2027, f.properties["anio"])
        assertNull(f.properties["valor_m2"])
    }

    @Test
    fun `sin geometría no hay nada que dibujar`() {
        assertNull(feature(tramo(null), 2026, BigDecimal.ONE))
    }

    private fun tramo(geom: Map<String, Any?>?) =
        TramoVia(
            id = "t1",
            codViaEje = "026220",
            tipVia = "CA.",
            nomVia = "LOS PRUEBA",
            lado = "AMBOS",
            idAranc = "0010000401-01",
            asignacion = "NOMBRE_UNICO",
            geom = geom
        )
}
