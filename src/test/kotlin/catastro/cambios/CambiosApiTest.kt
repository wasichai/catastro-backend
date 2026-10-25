package catastro.cambios

import catastro.CatastroApiTest
import catastro.valuacion.CONSTRUCCION
import catastro.valuacion.ENTREGA_CATASTRAL
import catastro.valuacion.OBRA_COMPLEMENTARIA
import catastro.valuacion.PREDIO_CATASTRAL
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.http.HttpStatus
import org.springframework.r2dbc.core.DatabaseClient
import tools.jackson.databind.JsonNode
import wasichai.core.platform.WasichaiSchemas
import java.util.UUID

// GET /api/catastro/cambios end to end: wasichai's audit_log read oldest first, by an opaque cursor, as srtm follows
// it (contract 3 of wasichai/srtm-backend#202). The test db is shared and kept between runs, so each test first
// drains the feed to its end and then looks only at the rows it wrote, every one with a unique code. This test also
// pins the audit_log columns catastro reads (ADR-014): a wasichai upgrade that changes them turns it red
class CambiosApiTest : CatastroApiTest() {
    @Autowired
    private lateinit var db: DatabaseClient

    @Autowired
    private lateinit var schemas: WasichaiSchemas

    @Test
    fun `un alta, un cambio de piso y la baja de una obra dan tres ítems, sin repetir ni saltar`() {
        val srtm = cuentaDeServicio(listOf("SRTM_LECTOR"))
        val u = uniqueName("c1")
        registro(ENTREGA_CATASTRAL, mapOf("codigo" to "E-$u", "fecha_corte" to "2026-10-25", "fuente" to "OTRA"))
        val p = registro(PREDIO_CATASTRAL, mapOf("codigo_municipal" to "P-$u"))
        val piso = registro(CONSTRUCCION, mapOf("predio" to p, "piso" to "1", "area_construida" to 100, "material" to "CONCRETO"))
        val obra = registro(OBRA_COMPLEMENTARIA, mapOf("predio" to p, "codigo_vu" to "MUROS PERIMETRICOS O CERCOS|1", "cantidad" to 30))
        val (_, c0) = leer(srtm, desde = null, size = 500)

        // as a loader writes them: the entrega's code as the reason
        val razon = mapOf("X-Change-Reason" to "E-$u")
        send("POST", "/api/objects/$PREDIO_CATASTRAL/records", mapOf("attributes" to mapOf("codigo_municipal" to "Q-$u")), HttpStatus.CREATED, admin, razon)
        send("PATCH", "/api/objects/$CONSTRUCCION/records/$piso", mapOf("attributes" to mapOf("area_construida" to 120)), HttpStatus.OK, admin, razon)
        send("DELETE", "/api/objects/$OBRA_COMPLEMENTARIA/records/$obra", null, HttpStatus.NO_CONTENT, admin, razon)

        val todos = leer(srtm, desde = c0, size = 1).first.filter { codigo(it)?.endsWith(u) == true }
        assertEquals(
            listOf(
                Triple("Q-$u", PREDIO_CATASTRAL, "CREATE"),
                Triple("P-$u", CONSTRUCCION, "UPDATE"),
                Triple("P-$u", OBRA_COMPLEMENTARIA, "DELETE")
            ),
            todos.map { Triple(codigo(it), it["objeto"].asString(), it["operacion"].asString()) }
        )
        assertEquals(listOf("codigo_municipal"), todos[0]["campos"].lista().map { it.asString() })
        assertEquals(listOf("area_construida"), todos[1]["campos"].lista().map { it.asString() })
        assertEquals(emptyList<String>(), todos[2]["campos"].lista().map { it.asString() })
        assertEquals(listOf("E-$u", "E-$u", "E-$u"), todos.map { it["entrega"].asString() })
        assertEquals(setOf("codigoMunicipal", "objeto", "operacion", "campos", "en", "entrega"), todos[0].propertyNames().asSequence().toSet())
        // the same items whatever the size
        assertEquals(todos, leer(srtm, desde = c0, size = 500).first.filter { codigo(it)?.endsWith(u) == true })
    }

    @Test
    fun `filas de una misma transacción, con el mismo instante, salen todas y en orden con cualquier size`() {
        val srtm = cuentaDeServicio(listOf("SRTM_LECTOR"))
        val u = uniqueName("c2")
        val organizacion = organizacionDe(registro(PREDIO_CATASTRAL, mapOf("codigo_municipal" to "P-$u")))
        val (_, c0) = leer(srtm, desde = null, size = 500)

        // three rows written by one statement share now(), the transaction's start: only the id orders them. wasichai
        // writes one audit row per request today, so they are put in the log directly (synthetic, never a record)
        db
            .sql(
                """
                INSERT INTO ${schemas.metadata}.audit_log (organization_id, object_name, record_id, operation, after_state)
                VALUES (:organizacion, 'predio_catastral', gen_random_uuid(), 'CREATE', CAST(:a AS jsonb)),
                       (:organizacion, 'predio_catastral', gen_random_uuid(), 'CREATE', CAST(:b AS jsonb)),
                       (:organizacion, 'predio_catastral', gen_random_uuid(), 'CREATE', CAST(:c AS jsonb))
                """.trimIndent()
            ).bind("organizacion", organizacion)
            .bind("a", """{"codigo_municipal": "A-$u"}""")
            .bind("b", """{"codigo_municipal": "B-$u"}""")
            .bind("c", """{"codigo_municipal": "C-$u"}""")
            .fetch()
            .rowsUpdated()
            .block()

        val porUno = leer(srtm, desde = c0, size = 1).first.filter { codigo(it)?.endsWith(u) == true }
        assertEquals(setOf("A-$u", "B-$u", "C-$u"), porUno.map { codigo(it) }.toSet())
        assertEquals(3, porUno.size)
        assertEquals(1, porUno.map { it["en"].asString() }.toSet().size)
        assertEquals(porUno, leer(srtm, desde = c0, size = 2).first.filter { codigo(it)?.endsWith(u) == true })
        assertEquals(porUno, leer(srtm, desde = c0, size = 500).first.filter { codigo(it)?.endsWith(u) == true })
    }

    @Test
    fun `sin nada nuevo vuelve el mismo cursor y hayMas es falso`() {
        val srtm = cuentaDeServicio(listOf("SRTM_LECTOR"))
        registro(PREDIO_CATASTRAL, mapOf("codigo_municipal" to "P-${uniqueName("c3")}"))
        val (_, c1) = leer(srtm, desde = null, size = 500)

        val r = arbol(send("GET", "/api/catastro/cambios?desde=$c1", null, HttpStatus.OK, srtm))
        assertEquals(c1, r["cursor"].asString())
        assertTrue(r["items"].isEmpty)
        assertFalse(r["hayMas"].asBoolean())
    }

    @Test
    fun `el predio de una obra borrada junto con su predio sale del audit log`() {
        val srtm = cuentaDeServicio(listOf("SRTM_LECTOR"))
        val u = uniqueName("c4")
        val r = registro(PREDIO_CATASTRAL, mapOf("codigo_municipal" to "R-$u"))
        val obra = registro(OBRA_COMPLEMENTARIA, mapOf("predio" to r, "codigo_vu" to "MUROS PERIMETRICOS O CERCOS|1", "cantidad" to 30))
        val (_, c0) = leer(srtm, desde = null, size = 500)

        send("DELETE", "/api/objects/$OBRA_COMPLEMENTARIA/records/$obra", null, HttpStatus.NO_CONTENT, admin)
        send("DELETE", "/api/objects/$PREDIO_CATASTRAL/records/$r", null, HttpStatus.NO_CONTENT, admin)

        val todos = leer(srtm, desde = c0, size = 1).first.filter { codigo(it)?.endsWith(u) == true }
        assertEquals(
            listOf(Triple("R-$u", OBRA_COMPLEMENTARIA, "DELETE"), Triple("R-$u", PREDIO_CATASTRAL, "DELETE")),
            todos.map { Triple(codigo(it), it["objeto"].asString(), it["operacion"].asString()) }
        )
        // no reason given: no entrega
        assertTrue(todos.all { it["entrega"].isNull })
    }

    @Test
    fun `sin token 401, sin el rol 403, desde o size malos 422 que lo nombran`() {
        client
            .get()
            .uri("/api/catastro/cambios")
            .exchange()
            .expectStatus()
            .isUnauthorized
        val sinRol = cuentaDeServicio(emptyList())
        assertEquals(HttpStatus.FORBIDDEN, exchange("GET", "/api/catastro/cambios", null, sinRol).first)

        val srtm = cuentaDeServicio(listOf("SRTM_LECTOR"))
        for ((query, nombre) in listOf(
            "desde=no-es-un-cursor" to "desde",
            "size=0" to "size",
            "size=501" to "size",
            "size=dos" to "size",
            "x=1" to "x"
        )) {
            val (status, body) = exchange("GET", "/api/catastro/cambios?$query", null, srtm)
            assertEquals(HttpStatus.UNPROCESSABLE_CONTENT, status, "$query: $body")
            assertEquals(nombre, arbol(body)["errors"][0]["field"].asString(), body)
        }
    }

    // every page from `desde`, following the cursor while hayMas, as srtm reads them: the items and the last cursor
    private fun leer(
        token: String,
        desde: String?,
        size: Int
    ): Pair<List<JsonNode>, String?> {
        val items = mutableListOf<JsonNode>()
        var cursor = desde
        while (true) {
            val query = listOfNotNull(cursor?.let { "desde=$it" }, "size=$size").joinToString("&")
            val pagina = arbol(send("GET", "/api/catastro/cambios?$query", null, HttpStatus.OK, token))
            items += pagina["items"].lista()
            cursor = pagina["cursor"].takeUnless { it.isNull }?.asString()
            if (!pagina["hayMas"].asBoolean()) return items to cursor
        }
    }

    private fun codigo(item: JsonNode): String? = item["codigoMunicipal"].takeUnless { it.isNull }?.asString()

    // the organization a record was written in, from its own audit row
    private fun organizacionDe(registro: String): UUID =
        db
            .sql("SELECT organization_id FROM ${schemas.metadata}.audit_log WHERE record_id = :id LIMIT 1")
            .bind("id", UUID.fromString(registro))
            .map { row, _ -> row.get("organization_id", UUID::class.java)!! }
            .one()
            .block()!!
}
