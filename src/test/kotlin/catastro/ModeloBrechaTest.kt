package catastro

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.springframework.http.HttpStatus
import java.math.BigDecimal

// what model/importar_corte_brecha.py takes for granted of a real core, with the real model: its fichas listed by the
// relation (?corte=<id>), a DATE answered as the text it sent and a DECIMAL as the same number (the loader compares
// them to stay idempotent), a clave that is unique, and a PATCH with null that clears cargado_en
class ModeloBrechaTest : CatastroApiTest() {
    @Test
    fun `lo que el cargador del corte espera del core`() {
        val marca = uniqueName("cb")
        val corte =
            registro(
                "corte_brecha",
                mapOf("clave" to "$marca|2026-10-25", "org_slug" to marca, "fecha" to "2026-10-25", "anio" to 2026, "delta_impuesto" to "120.5")
            )
        val otro = registro("corte_brecha", mapOf("clave" to "$marca|2026-11-25", "org_slug" to marca, "fecha" to "2026-11-25", "anio" to 2026))
        for ((c, n) in listOf(corte to 2, otro to 1)) {
            repeat(n) { i -> registro("brecha_ficha", mapOf("clave" to "$c|$i", "corte" to c, "categoria" to "OMISO", "delta_impuesto" to "-3.25")) }
        }

        val fichas = arbol(send("GET", "/api/objects/brecha_ficha/records?corte=$corte&size=200", null, HttpStatus.OK, admin))["content"].lista()
        assertEquals(2, fichas.size)
        assertTrue(fichas.all { it["attributes"]["corte"].asString() == corte })
        assertEquals(0, BigDecimal("-3.25").compareTo(fichas[0]["attributes"]["delta_impuesto"].decimalValue()))

        val guardado = arbol(send("GET", "/api/objects/corte_brecha/records?clave=$marca|2026-10-25", null, HttpStatus.OK, admin))["content"].lista()
        assertEquals(1, guardado.size)
        val atributos = guardado[0]["attributes"]
        assertEquals("2026-10-25", atributos["fecha"].asString())
        assertEquals(0, BigDecimal("120.5").compareTo(atributos["delta_impuesto"].decimalValue()))

        val (status, cuerpo) =
            exchange(
                "POST",
                "/api/objects/corte_brecha/records",
                mapOf("attributes" to mapOf("clave" to "$marca|2026-10-25", "org_slug" to marca, "fecha" to "2026-10-25", "anio" to 2026)),
                admin
            )
        assertEquals(HttpStatus.CONFLICT, status, cuerpo)

        send("PATCH", "/api/objects/corte_brecha/records/$corte", mapOf("attributes" to mapOf("cargado_en" to "2026-10-25T12:00:00Z")), HttpStatus.OK, admin)
        send("PATCH", "/api/objects/corte_brecha/records/$corte", mapOf("attributes" to mapOf("cargado_en" to null)), HttpStatus.OK, admin)
        val limpio = arbol(send("GET", "/api/objects/corte_brecha/records/$corte", null, HttpStatus.OK, admin))["attributes"]
        assertTrue(limpio["cargado_en"] == null || limpio["cargado_en"].isNull, limpio.toString())
    }
}
