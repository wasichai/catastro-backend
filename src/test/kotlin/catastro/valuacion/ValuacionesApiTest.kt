package catastro.valuacion

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.springframework.http.HttpHeaders
import org.springframework.http.HttpStatus
import tools.jackson.databind.JsonNode
import tools.jackson.databind.json.JsonMapper
import wasichai.test.WasichaiIntegrationTest
import java.io.File
import java.math.BigDecimal

// GET /api/catastro/valuaciones end to end: the real model (model/model.json, applied the way model/apply.py does)
// and the real role (model/roles.json), a service account created and signed in over core's REST, as srtm-backend
// will. the test db is shared and kept between runs: every record carries a unique code
class ValuacionesApiTest : WasichaiIntegrationTest() {
    private lateinit var admin: String

    @BeforeEach
    fun modeloYRol() {
        admin = bearer()
        aplicarModelo()
        aplicarRoles()
    }

    @Test
    fun `la cuenta de servicio de srtm lee las valuaciones del año`() {
        val srtm = cuentaDeServicio(listOf("SRTM_LECTOR"))
        val marca = uniqueName("t5").uppercase()
        val idAranc = "$marca-A"
        registro(ARANCEL, mapOf("clave" to "$idAranc|2026", "id_aranc" to idAranc, "anio" to 2026, "valor_m2" to 45.50))
        // another year's arancel of the same vía must not be used
        registro(ARANCEL, mapOf("clave" to "$idAranc|2025", "id_aranc" to idAranc, "anio" to 2025, "valor_m2" to 999))

        val casa =
            predio(
                "$marca-1",
                idAranc,
                mapOf("codigo_cpu" to "$marca-CPU", "longitud_frente" to 10.5),
                mapOf("lote_geom" to mapOf("type" to "Polygon", "coordinates" to listOf(LOTE)))
            )
        piso(casa, "1", "CONCRETO", "BUENO")
        registro(
            OBRA_COMPLEMENTARIA,
            mapOf(
                "predio" to casa,
                "codigo_vu" to "MUROS PERIMETRICOS O CERCOS|1",
                "cantidad" to 30,
                "anio_construccion" to 2016,
                "material" to "CONCRETO",
                "estado_conservacion" to "BUENO"
            )
        )
        // a techo J has no value in the selva cuadro ("....."): the predio carries a motivo instead
        val sinValor = predio("$marca-2", idAranc)
        piso(sinValor, "1", "CONCRETO", "BUENO", techos = "J")
        // every material and every estado the model's enums spell, as core stores them: none is unknown to the engine
        val modelo = arbol(File("model/model.json"))
        val materiales = modelo["enums"]["material"].lista().map { it.asString() }
        val estados = modelo["enums"]["estado_conservacion"].lista().map { it.asString() }
        val variado = predio("$marca-3", idAranc)
        materiales.forEachIndexed { n, material -> piso(variado, "${n + 1}", material, estados[n % estados.size], area = 10, anio = 2000) }
        estados.forEachIndexed { n, estado -> piso(variado, "S${n + 1}", "LADRILLO", estado, area = 10, anio = 2000) }

        val todos = leerTodo(srtm, 500)
        val items = todos.associateBy { it["codigoMunicipal"].asString() }

        val a = items.getValue("$marca-1")
        // the engine's "todo junto": terreno 200 x 45.50 = 9100.00; piso 78781.60; muro 8870.61 (ValorizacionTest)
        assertEquals("$marca-CPU", a["codigoCpu"].asString())
        assertEquals("S01", a["sector"].asString())
        assertEquals("M01", a["manzana"].asString())
        assertEquals("L01", a["lote"].asString())
        assertEquals("010101", a["uso"].asString())
        numero("200", a["areaTerreno"])
        numero("100", a["areaConstruida"])
        numero("10.5", a["longitudFrente"])
        numero("9100.00", a["terreno"])
        numero("78781.60", a["construccion"])
        numero("8870.61", a["obras"])
        numero("96752.21", a["autoavaluo"])
        assertTrue(a["motivo"].isNull)
        assertTrue(a["llave"].isNull)
        val geometria = a["loteGeom"]
        assertEquals("Polygon", geometria["type"].asString())
        // stored in 32718 and back in 4326
        val (lon, lat) = geometria["coordinates"][0][0].let { it[0].asDouble() to it[1].asDouble() }
        assertEquals(LOTE[0][0], lon, 1e-6)
        assertEquals(LOTE[0][1], lat, 1e-6)

        val b = items.getValue("$marca-2")
        assertEquals("VU_SIN_VALOR:TECHOS:J", b["llave"].asString())
        assertTrue(b["motivo"].asString().isNotBlank())
        for (campo in listOf("terreno", "construccion", "obras", "autoavaluo")) assertTrue(b[campo].isNull, campo)
        assertTrue(b["loteGeom"].isNull)
        numero("100", b["areaConstruida"])

        val c = items.getValue("$marca-3")
        assertTrue(c["llave"].isNull, c.toString())
        assertNotNull(c["autoavaluo"].decimalValue())
        numero("${(materiales.size + estados.size) * 10}", c["areaConstruida"])
    }

    @Test
    fun `las páginas suman el total, sin repetir, por código municipal`() {
        val srtm = cuentaDeServicio(listOf("SRTM_LECTOR"))
        val marca = uniqueName("t5").uppercase()
        repeat(3) { predio("$marca-$it", null) }
        val primera = valuaciones(srtm, "anio=2026&page=0&size=3")
        val total = primera["total"].asLong()
        assertEquals(2026, primera["anio"].asInt())
        assertEquals("valuacion-v1", primera["version"].asString())
        assertEquals(0, primera["page"].asInt())
        assertEquals(3, primera["size"].asInt())
        val codigos = leerTodo(srtm, 3).map { it["codigoMunicipal"].asString() }
        assertEquals(total, codigos.size.toLong())
        assertEquals(codigos.toSet().size, codigos.size)
        assertEquals(codigos.sorted(), codigos)
        // without an arancel there is no land value
        assertEquals("ARANCEL_FALTANTE", leerTodo(srtm, 500).first { it["codigoMunicipal"].asString() == "$marca-0" }["llave"].asString())
    }

    @Test
    fun `sin token 401, una cuenta sin el rol 403`() {
        val sinToken = client.get().uri("/api/catastro/valuaciones?anio=2026").exchange()
        sinToken.expectStatus().isUnauthorized
        val sinRol = cuentaDeServicio(emptyList())
        assertEquals(HttpStatus.FORBIDDEN, exchange("GET", "/api/catastro/valuaciones?anio=2026", null, sinRol).first)
    }

    @Test
    fun `un parámetro que falta, sobra o se sale del rango es un 422 que lo nombra`() {
        for ((query, nombre) in listOf(
            "" to "anio",
            "anio=2026&size=501" to "size",
            "anio=dos" to "anio",
            "anio=2026&page=-1" to "page",
            "anio=2026&sort=x" to "sort"
        )) {
            val (status, body) = exchange("GET", "/api/catastro/valuaciones?$query", null, admin)
            assertEquals(HttpStatus.UNPROCESSABLE_CONTENT, status, "$query: $body")
            assertEquals(nombre, arbol(body)["errors"][0]["field"].asString(), body)
        }
    }

    // every page of the year, in order, as srtm reads them
    private fun leerTodo(
        token: String,
        size: Int
    ): List<JsonNode> {
        val items = mutableListOf<JsonNode>()
        var page = 0
        while (true) {
            val pagina = valuaciones(token, "anio=2026&page=$page&size=$size")
            items += pagina["items"].lista()
            if (pagina["items"].size() < size) return items
            page++
        }
    }

    private fun valuaciones(
        token: String,
        query: String
    ): JsonNode = arbol(send("GET", "/api/catastro/valuaciones?$query", null, HttpStatus.OK, token))

    private fun numero(
        esperado: String,
        nodo: JsonNode
    ) = assertEquals(0, BigDecimal(esperado).compareTo(nodo.decimalValue()), "$esperado != $nodo")

    // records

    private fun predio(
        codigo: String,
        idAranc: String?,
        extra: Map<String, Any?> = emptyMap(),
        geometrias: Map<String, Any?>? = null
    ): String =
        registro(
            PREDIO_CATASTRAL,
            mapOf(
                "codigo_municipal" to codigo,
                "sector" to "S01",
                "manzana" to "M01",
                "lote" to "L01",
                "id_aranc" to idAranc,
                "uso" to "010101",
                "area_terreno" to 200,
                "es_edificio" to false
            ) + extra,
            geometrias
        )

    private fun piso(
        predio: String,
        piso: String,
        material: String,
        estado: String,
        techos: String = "D",
        area: Int = 100,
        anio: Int = 2016
    ) = registro(
        CONSTRUCCION,
        mapOf(
            "predio" to predio,
            "piso" to piso,
            "area_construida" to area,
            "anio_construccion" to anio,
            "material" to material,
            "estado_conservacion" to estado,
            "muros_columnas" to "C",
            "techos" to techos,
            "puertas_ventanas" to "E"
        )
    )

    // a record created by the seeded admin: its id
    private fun registro(
        objeto: String,
        atributos: Map<String, Any?>,
        geometrias: Map<String, Any?>? = null
    ): String {
        val cuerpo = mutableMapOf<String, Any?>("attributes" to atributos)
        if (geometrias != null) cuerpo["geometries"] = geometrias
        return arbol(send("POST", "/api/objects/$objeto/records", cuerpo, HttpStatus.CREATED, admin))["id"].asString()
    }

    // a service account with `roles`, signed in through /api/auth/token as srtm does: its Bearer
    private fun cuentaDeServicio(roles: List<String>): String {
        val cuenta = arbol(send("POST", "/api/service-accounts", mapOf("name" to uniqueName("srtm"), "roles" to roles), HttpStatus.CREATED, admin))
        val acceso =
            arbol(
                send(
                    "POST",
                    "/api/auth/token",
                    mapOf("clientId" to cuenta["clientId"].asString(), "clientSecret" to cuenta["clientSecret"].asString()),
                    HttpStatus.OK,
                    admin
                )
            )
        return "Bearer ${acceso["token"].asString()}"
    }

    // model/roles.json, as model/apply_roles.py applies it: a missing role is created, its permissions are roles.json's
    private fun aplicarRoles() {
        val existentes = arbol(send("GET", "/api/roles", null, HttpStatus.OK, admin)).lista().map { it["name"].asString() }.toSet()
        for (rol in arbol(File("model/roles.json"))["roles"]) {
            val nombre = rol["name"].asString()
            if (nombre !in existentes) send("POST", "/api/roles", mapOf("name" to nombre, "label" to rol["label"].asString()), HttpStatus.CREATED, admin)
            val permisos =
                rol["permisos"].properties().flatMap { (objeto, acciones) -> acciones.lista().map { mapOf("objectName" to objeto, "action" to it.asString()) } }
            send("PUT", "/api/roles/$nombre/permissions", mapOf("permissions" to permisos), HttpStatus.OK, admin)
        }
    }

    // model/apply.py in kotlin, as much of it as an empty or an earlier test db needs: missing objects (with their
    // fields), fields and relationships are created, a relation model.json requires is made required, and the
    // indexes follow model.json
    private fun aplicarModelo() {
        val model = arbol(File("model/model.json"))
        val enums = model["enums"]

        fun payload(field: JsonNode) =
            buildMap {
                put("name", field["name"].asString())
                put("label", field["label"].asString())
                put("type", field["type"].asString())
                put("required", field["required"]?.asBoolean() ?: false)
                put("unique", field["unique"]?.asBoolean() ?: false)
                if (field["type"].asString() == "ENUM") put("enumOptions", enums[field["enum"].asString()].lista().map { it.asString() })
                if (field["type"].asString() == "GEOMETRY") {
                    put("geometryType", field["geometryType"].asString())
                    put("srid", field["srid"]?.asInt() ?: 4326)
                }
            }

        val existentes = arbol(send("GET", "/api/objects", null, HttpStatus.OK, admin)).lista().map { it["name"].asString() }.toSet()
        for (obj in model["objects"]) {
            val nombre = obj["name"].asString()
            val campos = obj["fields"].lista()
            if (nombre !in existentes) {
                send(
                    "POST",
                    "/api/objects",
                    mapOf(
                        "name" to nombre,
                        "label" to obj["label"].asString(),
                        "pluralLabel" to obj["pluralLabel"].asString(),
                        "fields" to campos.map(::payload)
                    ),
                    HttpStatus.CREATED,
                    admin
                )
                continue
            }
            val guardados =
                arbol(send("GET", "/api/metadata/objects/$nombre/fields", null, HttpStatus.OK, admin)).lista().map { it["name"].asString() }.toSet()
            for (campo in campos.filter { it["name"].asString() !in guardados }) {
                send("POST", "/api/metadata/objects/$nombre/fields", payload(campo), HttpStatus.CREATED, admin)
            }
        }
        val relaciones = arbol(send("GET", "/api/relationships", null, HttpStatus.OK, admin)).lista().map { it["name"].asString() }.toSet()
        for (rel in model["relationships"]) {
            if (rel["name"].asString() in relaciones) continue
            send(
                "POST",
                "/api/relationships",
                listOf("name", "label", "inverseLabel", "source", "target", "fieldName").associateWith { rel[it].asString() } + ("type" to "MANY_TO_ONE"),
                HttpStatus.CREATED,
                admin
            )
            if (rel["required"]?.asBoolean() != true) continue
            send(
                "PUT",
                "/api/metadata/objects/${rel["source"].asString()}/fields/${rel["fieldName"].asString()}",
                mapOf("required" to true),
                HttpStatus.OK,
                admin
            )
        }
        val guardados = arbol(send("GET", "/api/objects", null, HttpStatus.OK, admin)).lista().associateBy { it["name"].asString() }
        for (obj in model["objects"]) {
            val indexes = obj["indexes"]?.lista()?.map { set -> set.lista().map { it.asString().trim().lowercase() } }.orEmpty()
            val actual = guardados.getValue(obj["name"].asString())
            val tiene = actual["indexes"]?.lista()?.map { set -> set.lista().map { it.asString() } }.orEmpty()
            if (indexes == tiene) continue
            val conservados =
                mapOf(
                    "label" to actual["label"].asString(),
                    "pluralLabel" to actual["pluralLabel"]?.takeUnless { it.isNull }?.asString(),
                    "description" to actual["description"]?.takeUnless { it.isNull }?.asString(),
                    "enabled" to (actual["enabled"]?.asBoolean() ?: true)
                )
            send("PUT", "/api/objects/${obj["name"].asString()}", conservados + ("indexes" to indexes), HttpStatus.OK, admin)
        }
    }

    // calls

    private fun send(
        method: String,
        path: String,
        body: Any?,
        status: HttpStatus,
        token: String
    ): String {
        val (actual, response) = exchange(method, path, body, token)
        assertEquals(status, actual, "$method $path: $response")
        return response
    }

    private fun exchange(
        method: String,
        path: String,
        body: Any?,
        token: String
    ): Pair<HttpStatus, String> {
        val spec =
            when (method) {
                "GET" -> client.get().uri(path)
                "PUT" -> client.put().uri(path).bodyValue(body!!)
                else -> client.post().uri(path).bodyValue(body!!)
            }
        val result =
            spec
                .header(HttpHeaders.AUTHORIZATION, token)
                .exchange()
                .expectBody(String::class.java)
                .returnResult()
        return HttpStatus.valueOf(result.status.value()) to (result.responseBody ?: "")
    }

    private fun arbol(texto: String): JsonNode = json.readValue(texto, JsonNode::class.java)

    private fun arbol(archivo: File): JsonNode = json.readValue(archivo, JsonNode::class.java)

    private fun JsonNode.lista(): List<JsonNode> = iterator().asSequence().toList()

    private companion object {
        val json: JsonMapper = JsonMapper.builder().build()

        // a small lote in Perené, EPSG:4326
        val LOTE =
            listOf(
                listOf(-75.2200, -10.9500),
                listOf(-75.2195, -10.9500),
                listOf(-75.2195, -10.9495),
                listOf(-75.2200, -10.9495),
                listOf(-75.2200, -10.9500)
            )
    }
}
