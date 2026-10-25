package catastro.copias

import catastro.CatastroApiTest
import catastro.valuacion.ARANCEL
import catastro.vias.TRAMO_VIA
import catastro.vias.anioEnCurso
import kotlinx.coroutines.runBlocking
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.http.HttpStatus
import tools.jackson.databind.JsonNode
import java.math.BigDecimal
import kotlin.random.Random

// tramo_via.valor_m2 and anio_valor, the copy of the current year's arancel the map view and the WMS layer colour by,
// written by CopiasDelMapa as the platform: after a nudge (a write of an arancel of the year, of a tramo), on every
// periodic run, and on POST /api/catastro/vias/valores. the aranceles are written by srtm's service account, as srtm
// syncs them: it holds no UPDATE on tramo_via. the test db is shared and kept between runs, so every id_aranc carries
// this run's mark, and a test that runs the copies on demand has an organization to itself
class CopiasDelMapaApiTest : CatastroApiTest() {
    @Autowired
    private lateinit var copias: CopiasDelMapa

    private val esteAnio = anioEnCurso()

    @Test
    fun `un arancel del año en curso pone su valor en los tramos de su id_aranc, otro año no y su baja lo quita`() {
        val srtm = cuentaDeServicio(listOf("SRTM_LECTOR"))
        val marca = uniqueName("vt").uppercase()
        val frente = "$marca-01"
        val tramo = tramo(marca, frente)
        val otro = tramo(marca, "$marca-02")
        val segundo = tramo(marca, frente, lado = "DERECHO")
        // another organization with a tramo of the same id_aranc and no arancel: it never takes this one's value
        val (org2, _) = organizacionNueva()
        val ajeno = tramo(marca, frente, token = org2)

        arancel(frente, esteAnio + 1, 999, srtm)
        send("POST", "/api/catastro/vias/valores", emptyMap<String, Any>(), HttpStatus.OK, admin)
        assertEquals(null to null, valor(tramo))

        val id = arancel(frente, esteAnio, 356, srtm)
        hasta("el valor del arancel en el tramo") { valor(tramo) == (BigDecimal("356") to esteAnio) }
        hasta("el valor en el otro frente del mismo código") { valor(segundo) == (BigDecimal("356") to esteAnio) }
        assertEquals(null to null, valor(otro))

        send("PATCH", "/api/objects/$ARANCEL/records/$id", mapOf("attributes" to mapOf("valor_m2" to 400.5)), HttpStatus.OK, srtm)
        hasta("el valor nuevo") { valor(tramo) == (BigDecimal("400.5") to esteAnio) }

        send("DELETE", "/api/objects/$ARANCEL/records/$id", null, HttpStatus.NO_CONTENT, srtm)
        hasta("sin arancel, sin valor") { valor(tramo) == (null to null) && valor(segundo) == (null to null) }

        send("POST", "/api/catastro/vias/valores", emptyMap<String, Any>(), HttpStatus.OK, org2)
        assertEquals(null to null, valor(ajeno, org2))
    }

    @Test
    fun `un tramo nuevo, o que cambia de id_aranc, toma el valor del año de su arancel`() {
        val marca = uniqueName("vtn").uppercase()
        arancel("$marca-01", esteAnio, 120)
        arancel("$marca-02", esteAnio - 1, 80)
        val tramo = tramo(marca, "$marca-01")
        hasta("el valor del tramo nuevo") { valor(tramo) == (BigDecimal("120") to esteAnio) }

        // another year's arancel is not this year's value
        send("PATCH", "/api/objects/$TRAMO_VIA/records/$tramo", mapOf("attributes" to mapOf("id_aranc" to "$marca-02")), HttpStatus.OK, admin)
        hasta("sin valor con el arancel de otro año") { valor(tramo) == (null to null) }
    }

    @Test
    fun `POST valores corre las copias al momento, es idempotente y es solo del admin`() {
        val (org, _) = organizacionNueva()
        val marca = uniqueName("vtr").uppercase()
        arancel("$marca-01", esteAnio, 356, org)
        val tramo = tramo(marca, "$marca-01", token = org)
        tramo(marca, null, token = org)
        val primera = arbol(send("POST", "/api/catastro/vias/valores", emptyMap<String, Any>(), HttpStatus.OK, org))
        assertEquals(esteAnio, primera["anio"].asInt())
        assertEquals(BigDecimal("356") to esteAnio, valor(tramo, org))

        // a copy written by hand (a PATCH that keeps id_aranc nudges nothing) is the arancel's again after a run
        send("PATCH", "/api/objects/$TRAMO_VIA/records/$tramo", mapOf("attributes" to mapOf("valor_m2" to 1)), HttpStatus.OK, org)
        val antes = actualizado(tramo, org)
        val corrida = arbol(send("POST", "/api/catastro/vias/valores", emptyMap<String, Any>(), HttpStatus.OK, org))
        assertEquals(1, corrida["tramos"].asInt())
        assertEquals(0, corrida["fichas"].asInt())
        assertEquals(BigDecimal("356") to esteAnio, valor(tramo, org))
        // a write through core: the record's version moves (ADR-051), so an If-Match read before is stale
        assertNotEquals(antes, actualizado(tramo, org))
        assertEquals(0, arbol(send("POST", "/api/catastro/vias/valores", emptyMap<String, Any>(), HttpStatus.OK, org))["tramos"].asInt())

        for (roles in listOf(listOf("SRTM_LECTOR"), listOf("CATASTRO_LECTOR"), listOf("CATASTRO_ANALISTA"))) {
            val (status, _) = exchange("POST", "/api/catastro/vias/valores", emptyMap<String, Any>(), cuentaDeServicio(roles, org))
            assertEquals(HttpStatus.FORBIDDEN, status, roles.toString())
        }
        // the year is always the current one: an anio, or anything else, is a 400 that names it
        for ((query, nombre) in listOf("anio=2027" to "anio", "x=1" to "x")) {
            val (status, body) = exchange("POST", "/api/catastro/vias/valores?$query", emptyMap<String, Any>(), org)
            assertEquals(HttpStatus.BAD_REQUEST, status, "$query: $body")
            assertEquals(nombre, arbol(body)["errors"][0]["field"].asString(), body)
        }
        client
            .post()
            .uri("/api/catastro/vias/valores")
            .exchange()
            .expectStatus()
            .isUnauthorized
    }

    @Test
    fun `la corrida periódica cura una copia que nadie avisó, en cada organización`() {
        val (org, _) = organizacionNueva()
        val marca = uniqueName("vtp").uppercase()
        arancel("$marca-01", esteAnio, 70, org)
        val tramo = tramo(marca, "$marca-01", token = org)
        hasta("la primera copia") { valor(tramo, org) == (BigDecimal("70") to esteAnio) }
        send("PATCH", "/api/objects/$TRAMO_VIA/records/$tramo", mapOf("attributes" to mapOf("valor_m2" to 5, "anio_valor" to esteAnio - 1)), HttpStatus.OK, org)

        // the scheduled method, called as the scheduler does: outside any request, every organization as the platform
        runBlocking { copias.periodica() }
        assertEquals(BigDecimal("70") to esteAnio, valor(tramo, org))
    }

    @Test
    fun `un lector ve el valor guardado y no lo escribe`() {
        val lector = cuentaDeServicio(listOf("CATASTRO_LECTOR"))
        val marca = uniqueName("vtl").uppercase()
        arancel("$marca-01", esteAnio, 50)
        val tramo = tramo(marca, "$marca-01")
        hasta("el valor para el lector") { valor(tramo, lector) == (BigDecimal("50") to esteAnio) }
        val (status, cuerpo) = exchange("PATCH", "/api/objects/$TRAMO_VIA/records/$tramo", mapOf("attributes" to mapOf("valor_m2" to 1)), lector)
        assertEquals(HttpStatus.FORBIDDEN, status, cuerpo)
    }

    private fun registroDe(
        tramo: String,
        token: String
    ): JsonNode = arbol(send("GET", "/api/objects/$TRAMO_VIA/records/$tramo", null, HttpStatus.OK, token))

    private fun actualizado(
        tramo: String,
        token: String
    ): String = registroDe(tramo, token)["updatedAt"].asString()

    // valor_m2 and anio_valor of a tramo, read through the record api
    private fun valor(
        tramo: String,
        token: String = admin
    ): Pair<BigDecimal?, Int?> {
        val atributos = registroDe(tramo, token)["attributes"]
        val valor =
            atributos
                .campo("valor_m2")
                ?.decimalValue()
                ?.stripTrailingZeros()
                ?.let { if (it.scale() < 0) it.setScale(0) else it }
        return valor to atributos.campo("anio_valor")?.asInt()
    }

    private fun JsonNode.campo(nombre: String): JsonNode? = get(nombre)?.takeUnless { it.isNull }

    private fun arancel(
        idAranc: String,
        anio: Int,
        valor: Number,
        token: String = admin
    ) = registro(ARANCEL, mapOf("clave" to "$idAranc|$anio", "id_aranc" to idAranc, "anio" to anio, "valor_m2" to valor), token = token)

    private fun tramo(
        marca: String,
        idAranc: String?,
        lado: String = "AMBOS",
        token: String = admin
    ): String {
        val fid = Random.nextInt(1, Int.MAX_VALUE)
        return registro(
            TRAMO_VIA,
            mapOf(
                "clave" to "$marca-$fid|$lado",
                "fid_eje" to fid,
                "cod_via_eje" to marca,
                "lado" to lado,
                "id_aranc" to idAranc,
                "asignacion" to if (idAranc == null) "SIN_ARANCEL" else "NOMBRE_UNICO"
            ),
            mapOf("geom" to mapOf("type" to "MultiLineString", "coordinates" to listOf(EJE))),
            token
        )
    }

    private companion object {
        val EJE = listOf(listOf(-75.7300, -14.0700), listOf(-75.7290, -14.0700))
    }
}
