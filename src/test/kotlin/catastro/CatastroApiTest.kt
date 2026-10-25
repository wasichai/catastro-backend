package catastro

import catastro.valuacion.CONFIGURACION_CATASTRO
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.BeforeEach
import org.springframework.http.HttpHeaders
import org.springframework.http.HttpStatus
import tools.jackson.databind.JsonNode
import tools.jackson.databind.json.JsonMapper
import wasichai.test.WasichaiIntegrationTest
import java.io.File

// shared base for the integration tests of the catastro API: applies the real model (model/model.json, as
// model/apply.py does) and the real role (model/roles.json), and gives the http/record helpers every one of
// them needs. The base itself signs in as admin; cuentaDeServicio is a helper the subclasses call to sign in
// as a service account, as srtm-backend will. the test db is shared and kept between runs: every record
// carries a unique code
abstract class CatastroApiTest : WasichaiIntegrationTest() {
    protected lateinit var admin: String

    @BeforeEach
    fun modeloYRol() {
        admin = bearer()
        aplicarModelo()
        aplicarRoles()
        // perené's region, as model/configurar_region.py --region SELVA leaves it
        region("SELVA")
    }

    // records

    // the organization's configuracion_catastro left with exactly one record saying `region`, or none when null
    protected fun region(region: String?) {
        val ids =
            arbol(send("GET", "/api/objects/$CONFIGURACION_CATASTRO/records?size=200", null, HttpStatus.OK, admin))["content"]
                .lista()
                .map { it["id"].asString() }
        ids.forEach { send("DELETE", "/api/objects/$CONFIGURACION_CATASTRO/records/$it", null, HttpStatus.NO_CONTENT, admin) }
        if (region != null) registro(CONFIGURACION_CATASTRO, mapOf("region" to region))
    }

    // a record created by the seeded admin: its id
    protected fun registro(
        objeto: String,
        atributos: Map<String, Any?>,
        geometrias: Map<String, Any?>? = null
    ): String {
        val cuerpo = mutableMapOf<String, Any?>("attributes" to atributos)
        if (geometrias != null) cuerpo["geometries"] = geometrias
        return arbol(send("POST", "/api/objects/$objeto/records", cuerpo, HttpStatus.CREATED, admin))["id"].asString()
    }

    // a service account with `roles`, signed in through /api/auth/token as srtm does: its Bearer
    protected fun cuentaDeServicio(roles: List<String>): String {
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

    protected fun send(
        method: String,
        path: String,
        body: Any?,
        status: HttpStatus,
        token: String,
        headers: Map<String, String> = emptyMap()
    ): String {
        val (actual, response) = exchange(method, path, body, token, headers)
        assertEquals(status, actual, "$method $path: $response")
        return response
    }

    protected fun exchange(
        method: String,
        path: String,
        body: Any?,
        token: String,
        headers: Map<String, String> = emptyMap()
    ): Pair<HttpStatus, String> {
        val spec =
            when (method) {
                "GET" -> client.get().uri(path)
                "PUT" -> client.put().uri(path).bodyValue(body!!)
                "PATCH" -> client.patch().uri(path).bodyValue(body!!)
                "DELETE" -> client.delete().uri(path)
                else -> client.post().uri(path).bodyValue(body!!)
            }
        val result =
            spec
                .header(HttpHeaders.AUTHORIZATION, token)
                .headers { h -> headers.forEach { (nombre, valor) -> h.set(nombre, valor) } }
                .exchange()
                .expectBody(String::class.java)
                .returnResult()
        return HttpStatus.valueOf(result.status.value()) to (result.responseBody ?: "")
    }

    protected fun arbol(texto: String): JsonNode = json.readValue(texto, JsonNode::class.java)

    protected fun arbol(archivo: File): JsonNode = json.readValue(archivo, JsonNode::class.java)

    protected fun JsonNode.lista(): List<JsonNode> = iterator().asSequence().toList()

    private companion object {
        val json: JsonMapper = JsonMapper.builder().build()
    }
}
