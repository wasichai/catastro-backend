package catastro.titulares

import catastro.CatastroApiTest
import catastro.valuacion.PREDIO_CATASTRAL
import catastro.valuacion.TITULAR_CATASTRAL
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test
import org.springframework.http.HttpStatus
import tools.jackson.databind.JsonNode

// GET /api/catastro/titulares end to end: paged by codigo_municipal and then by record id, SRTM_LECTOR only (its
// permission is the only READ on titular_catastral: datos personales, Ley 29733). The test db is shared and kept
// between runs, so every record carries a unique code; names and documents here are clearly synthetic
class TitularesApiTest : CatastroApiTest() {
    @Test
    fun `srtm lee los titulares por código municipal y luego por registro`() {
        val srtm = cuentaDeServicio(listOf("SRTM_LECTOR"))
        val u = uniqueName("t1")
        val a = predio("A-$u")
        val b = predio("B-$u")
        titular(b, "B-$u", "DNI", "11111111", "Titular Sintético Uno", "50", "PROPIETARIO")
        titular(b, "B-$u", "DNI", "22222222", "Titular Sintético Dos", "50", "PROPIETARIO")
        titular(a, "A-$u", "RUC", "33333333333", "Titular Sintético Tres", null, "POSEEDOR")

        // every page with size=1, as srtm reads them; the shared db may carry other organizations' titulares too
        val nuestros = leerTodo(srtm, 1).filter { it["codigoMunicipal"].asString().endsWith(u) }
        assertEquals(listOf("A-$u", "B-$u", "B-$u"), nuestros.map { it["codigoMunicipal"].asString() })
        assertEquals(
            setOf("codigoMunicipal", "tipoDocumento", "numeroDocumento", "nombre", "porcentaje", "condicion"),
            nuestros[0].nombres()
        )
    }

    @Test
    fun `sin token 401, sin el rol 403, un parámetro malo 422 que lo nombra`() {
        val sinToken = client.get().uri("/api/catastro/titulares").exchange()
        sinToken.expectStatus().isUnauthorized
        val sinRol = cuentaDeServicio(emptyList())
        assertEquals(HttpStatus.FORBIDDEN, exchange("GET", "/api/catastro/titulares", null, sinRol).first)

        val srtm = cuentaDeServicio(listOf("SRTM_LECTOR"))
        for ((query, nombre) in listOf(
            "size=0" to "size",
            "size=501" to "size",
            "page=-1" to "page",
            "x=1" to "x"
        )) {
            val (status, body) = exchange("GET", "/api/catastro/titulares?$query", null, srtm)
            assertEquals(HttpStatus.UNPROCESSABLE_CONTENT, status, "$query: $body")
            assertEquals(nombre, arbol(body)["errors"][0]["field"].asString(), body)
        }
    }

    // every page, as srtm reads them
    private fun leerTodo(
        token: String,
        size: Int
    ): List<JsonNode> {
        val items = mutableListOf<JsonNode>()
        var page = 0
        while (true) {
            val pagina = arbol(send("GET", "/api/catastro/titulares?page=$page&size=$size", null, HttpStatus.OK, token))
            items += pagina["items"].lista()
            if (pagina["items"].size() < size) return items
            page++
        }
    }

    private fun predio(codigo: String): String = registro(PREDIO_CATASTRAL, mapOf("codigo_municipal" to codigo))

    private fun titular(
        predio: String,
        codigoMunicipal: String,
        tipoDocumento: String,
        numeroDocumento: String,
        nombre: String,
        porcentaje: String?,
        condicion: String
    ): String =
        registro(
            TITULAR_CATASTRAL,
            mapOf(
                "predio" to predio,
                "codigo_municipal" to codigoMunicipal,
                "tipo_documento" to tipoDocumento,
                "numero_documento" to numeroDocumento,
                "nombre" to nombre,
                "porcentaje" to porcentaje,
                "condicion" to condicion
            )
        )

    private fun JsonNode.nombres(): Set<String> = propertyNames().asSequence().toSet()
}
