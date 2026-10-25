package catastro.cambios

import catastro.ParametroInvalido
import catastro.cambios.LecturaDeCambios.cambio
import catastro.cambios.LecturaDeCambios.campos
import catastro.cambios.LecturaDeCambios.codigoPropio
import catastro.cambios.LecturaDeCambios.predioDe
import catastro.valuacion.CONSTRUCCION
import catastro.valuacion.OBRA_COMPLEMENTARIA
import catastro.valuacion.PREDIO_CATASTRAL
import catastro.valuacion.TITULAR_CATASTRAL
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import tools.jackson.databind.json.JsonMapper
import java.math.BigDecimal
import java.time.Instant
import java.util.Base64
import java.util.UUID

// the pure half of GET /api/catastro/cambios: the opaque cursor, and one row of wasichai's audit_log read as an item
// of contract 3 (wasichai/srtm-backend#202). the sql and the permissions are CambiosApiTest's
class LecturaDeCambiosTest {
    private val predio = UUID.randomUUID()
    private val en = Instant.parse("2026-10-25T10:00:00.123456Z")

    // the field names of each object, in definition order, as MetadataService would give them
    private val camposDe =
        mapOf(
            PREDIO_CATASTRAL to listOf("codigo_municipal", "uso", "area_terreno", "entrega"),
            CONSTRUCCION to listOf("predio", "piso", "area_construida", "techos"),
            OBRA_COMPLEMENTARIA to listOf("predio", "codigo_vu", "cantidad"),
            TITULAR_CATASTRAL to listOf("predio", "codigo_municipal", "nombre", "porcentaje")
        )

    private fun fila(
        objeto: String = CONSTRUCCION,
        operacion: String = "UPDATE",
        antes: Map<String, Any?>? = null,
        despues: Map<String, Any?>? = null,
        razon: String? = null
    ) = FilaBitacora(UUID.randomUUID(), objeto, UUID.randomUUID(), operacion, en, antes, despues, razon)

    private fun create(
        objeto: String = CONSTRUCCION,
        after: Map<String, Any?>
    ) = fila(objeto, "CREATE", despues = after)

    private fun update(
        objeto: String = CONSTRUCCION,
        before: Map<String, Any?>,
        after: Map<String, Any?>
    ) = fila(objeto, "UPDATE", before, after)

    private fun delete(
        objeto: String = CONSTRUCCION,
        before: Map<String, Any?>
    ) = fila(objeto, "DELETE", antes = before)

    private fun base64(texto: String) = Base64.getUrlEncoder().withoutPadding().encodeToString(texto.toByteArray())

    @Test
    fun `el cursor ida y vuelta`() {
        val c = CursorCambios(en, UUID.randomUUID())
        assertEquals(c, CursorCambios.leer(c.codificar()))
    }

    @Test
    fun `el cursor es base64url sin relleno de la versión, el instante y el id`() {
        val id = UUID.fromString("0b7e3c1a-9f2d-4c55-8a10-3e5f6a7b8c9d")
        val texto = CursorCambios(en, id).codificar()
        assertEquals(base64("c1\n2026-10-25T10:00:00.123456Z\n$id"), texto)
        assertTrue(texto.none { it == '=' || it == '+' || it == '/' }, texto)
    }

    @Test
    fun `un cursor que no es nuestro es un 422 sobre desde`() {
        val id = UUID.randomUUID()
        listOf(
            "x",
            "",
            base64("c2\n2026-10-25T10:00:00Z\n$id"),
            base64("c1\nayer\n$id"),
            base64("c1\n2026-10-25T10:00:00Z\nno-es-un-uuid"),
            base64("c1\n2026-10-25T10:00:00Z\n$id\nmas"),
            "a+b/c==="
        ).forEach {
            val e = assertThrows<ParametroInvalido>(it) { CursorCambios.leer(it) }
            assertEquals("desde", e.violations.single().field, it)
        }
    }

    @Test
    fun `un alta lista sus campos con valor, en el orden del objeto`() {
        assertEquals(
            listOf("piso", "area_construida"),
            campos(
                create(after = mapOf("area_construida" to 1, "piso" to "1", "techos" to null, "id" to "x")),
                listOf("piso", "area_construida", "techos")
            )
        )
    }

    @Test
    fun `un cambio lista lo que cambió, 10 y 10,0 son lo mismo`() {
        val antes = mapOf("predio" to predio.toString(), "piso" to "1", "area_construida" to 10, "techos" to "A", "updated_at" to "t0")
        val despues =
            mapOf("predio" to predio.toString(), "piso" to "2", "area_construida" to 10.0, "techos" to null, "updated_at" to "t1")
        assertEquals(listOf("piso", "techos"), campos(update(before = antes, after = despues), camposDe.getValue(CONSTRUCCION)))
        val decimal = update(before = mapOf("area_construida" to BigDecimal("10.00")), after = mapOf("area_construida" to 10))
        assertEquals(emptyList<String>(), campos(decimal, camposDe.getValue(CONSTRUCCION)))
    }

    @Test
    fun `una baja no lista campos y su predio sale del antes`() {
        val baja = delete(before = mapOf("predio" to predio.toString(), "piso" to "1"))
        assertEquals(predio, predioDe(baja))
        assertEquals(emptyList<String>(), campos(baja, camposDe.getValue(CONSTRUCCION)))
    }

    @Test
    fun `una obra toma el código de su predio, uno que no se resuelve queda nulo`() {
        val obra = create(OBRA_COMPLEMENTARIA, mapOf("predio" to predio.toString(), "codigo_vu" to "MUROS|1", "cantidad" to 30))
        assertEquals("P-1", cambio(obra, mapOf(predio to "P-1"), setOf(), camposDe).codigoMunicipal)
        val sinPredio = cambio(obra, mapOf(), setOf(), camposDe)
        assertNull(sinPredio.codigoMunicipal)
        assertEquals(listOf("predio", "codigo_vu", "cantidad"), sinPredio.campos)
    }

    @Test
    fun `un predio trae su propio código, también al darse de baja`() {
        val alta = create(PREDIO_CATASTRAL, mapOf("codigo_municipal" to "P-1", "uso" to "010101", "id" to "x"))
        assertNull(predioDe(alta))
        assertEquals("P-1", codigoPropio(alta))
        assertEquals("P-2", codigoPropio(delete(PREDIO_CATASTRAL, mapOf("codigo_municipal" to "P-2"))))
        assertNull(codigoPropio(create(after = mapOf("predio" to predio.toString()))))
    }

    @Test
    fun `la entrega es la razón solo si es una entrega`() {
        assertNull(cambio(fila(razon = "a mano"), mapOf(), setOf("E-1"), camposDe).entrega)
        assertNull(cambio(fila(razon = null), mapOf(), setOf("E-1"), camposDe).entrega)
        assertEquals("E-1", cambio(fila(razon = "E-1"), mapOf(), setOf("E-1"), camposDe).entrega)
    }

    @Test
    fun `el titular trae su propio código`() {
        val otro = UUID.randomUUID()
        val titular =
            update(
                TITULAR_CATASTRAL,
                before = mapOf("predio" to otro.toString(), "codigo_municipal" to "T-1", "porcentaje" to 50),
                after = mapOf("predio" to otro.toString(), "codigo_municipal" to "T-1", "porcentaje" to 100)
            )
        assertNull(predioDe(titular))
        assertEquals(
            Cambio("T-1", TITULAR_CATASTRAL, "UPDATE", listOf("porcentaje"), en, null),
            cambio(titular, mapOf(otro to "P-9"), setOf(), camposDe)
        )
    }

    @Test
    fun `en sale como instante iso y toda llave viene, nula sin dato`() {
        val json = JsonMapper.builder().build()
        val texto = json.writeValueAsString(Cambios(listOf(Cambio(null, CONSTRUCCION, "DELETE", listOf(), en, null)), null, false))
        val arbol = json.readTree(texto)
        val item = arbol["items"][0]
        assertEquals("2026-10-25T10:00:00.123456Z", item["en"].asString(), texto)
        listOf("codigoMunicipal", "objeto", "operacion", "campos", "en", "entrega").forEach { assertTrue(item.has(it), "$it: $texto") }
        listOf("items", "cursor", "hayMas").forEach { assertTrue(arbol.has(it), "$it: $texto") }
    }
}
