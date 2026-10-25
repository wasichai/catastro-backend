package catastro.vias

import catastro.CatastroApiTest
import catastro.valuacion.ARANCEL
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test
import org.springframework.http.HttpStatus
import tools.jackson.databind.JsonNode
import java.math.BigDecimal
import kotlin.random.Random

// tramo_via.valor_m2 and anio_valor, the copy of the current year's arancel the map view and the WMS layer colour by:
// kept by ValoresDeTramos on every write of an arancel or a tramo, and recomputed whole by POST /api/catastro/vias/
// valores. the aranceles are written by srtm's service account, as srtm syncs them: it holds no UPDATE on tramo_via.
// the test db is shared and kept between runs, so every id_aranc carries this run's mark
class ValoresDeTramosApiTest : CatastroApiTest() {
    private val esteAnio = anioEnCurso()

    @Test
    fun `un arancel del año en curso pone su valor en los tramos de su id_aranc, otro año no y su baja lo quita`() {
        val srtm = cuentaDeServicio(listOf("SRTM_LECTOR"))
        val marca = uniqueName("vt").uppercase()
        val frente = "$marca-01"
        val tramo = tramo(marca, frente)
        val otro = tramo(marca, "$marca-02")
        val segundo = tramo(marca, frente, lado = "DERECHO")

        arancel(frente, esteAnio + 1, 999, srtm)
        assertEquals(null to null, valor(tramo))

        val id = arancel(frente, esteAnio, 356, srtm)
        assertEquals(BigDecimal("356") to esteAnio, valor(tramo))
        assertEquals(BigDecimal("356") to esteAnio, valor(segundo))
        assertEquals(null to null, valor(otro))

        send("PATCH", "/api/objects/$ARANCEL/records/$id", mapOf("attributes" to mapOf("valor_m2" to 400.5)), HttpStatus.OK, srtm)
        assertEquals(BigDecimal("400.5") to esteAnio, valor(tramo))

        send("DELETE", "/api/objects/$ARANCEL/records/$id", null, HttpStatus.NO_CONTENT, srtm)
        assertEquals(null to null, valor(tramo))
        assertEquals(null to null, valor(segundo))
    }

    @Test
    fun `un tramo nuevo, o que cambia de id_aranc, toma el valor del año de su arancel`() {
        val marca = uniqueName("vtn").uppercase()
        arancel("$marca-01", esteAnio, 120)
        arancel("$marca-02", esteAnio - 1, 80)
        val tramo = tramo(marca, "$marca-01")
        assertEquals(BigDecimal("120") to esteAnio, valor(tramo))

        // another year's arancel is not this year's value
        send("PATCH", "/api/objects/$TRAMO_VIA/records/$tramo", mapOf("attributes" to mapOf("id_aranc" to "$marca-02")), HttpStatus.OK, admin)
        assertEquals(null to null, valor(tramo))
        // a value sent by hand is the arancel's again after the write
        send("PATCH", "/api/objects/$TRAMO_VIA/records/$tramo", mapOf("attributes" to mapOf("id_aranc" to "$marca-01", "valor_m2" to 1)), HttpStatus.OK, admin)
        assertEquals(BigDecimal("120") to esteAnio, valor(tramo))
    }

    @Test
    fun `POST valores recalcula cada tramo para un año, es idempotente y es solo del admin`() {
        val (org, _) = organizacionNueva()
        val marca = uniqueName("vtr").uppercase()
        arancel("$marca-01", esteAnio, 356, org)
        arancel("$marca-01", esteAnio - 1, 300, org)
        val tramo = tramo(marca, "$marca-01", token = org)
        tramo(marca, null, token = org)
        assertEquals(BigDecimal("356") to esteAnio, valor(tramo, org))

        // the year before, as the rollover would be run the other way round
        val anterior = arbol(send("POST", "/api/catastro/vias/valores?anio=${esteAnio - 1}", emptyMap<String, Any>(), HttpStatus.OK, org))
        assertEquals(esteAnio - 1, anterior["anio"].asInt())
        assertEquals(2, anterior["tramos"].asInt())
        assertEquals(1, anterior["con_valor"].asInt())
        assertEquals(1, anterior["actualizados"].asInt())
        assertEquals(BigDecimal("300") to esteAnio - 1, valor(tramo, org))

        // without anio, the current year; the second time nothing changes
        val actual = arbol(send("POST", "/api/catastro/vias/valores", emptyMap<String, Any>(), HttpStatus.OK, org))
        assertEquals(esteAnio, actual["anio"].asInt())
        assertEquals(1, actual["actualizados"].asInt())
        assertEquals(BigDecimal("356") to esteAnio, valor(tramo, org))
        assertEquals(0, arbol(send("POST", "/api/catastro/vias/valores", emptyMap<String, Any>(), HttpStatus.OK, org))["actualizados"].asInt())

        // a year with no arancel clears them
        val vacio = arbol(send("POST", "/api/catastro/vias/valores?anio=${esteAnio + 5}", emptyMap<String, Any>(), HttpStatus.OK, org))
        assertEquals(0, vacio["con_valor"].asInt())
        assertEquals(null to null, valor(tramo, org))
        send("POST", "/api/catastro/vias/valores", emptyMap<String, Any>(), HttpStatus.OK, org)

        for (roles in listOf(listOf("SRTM_LECTOR"), listOf("CATASTRO_LECTOR"), listOf("CATASTRO_ANALISTA"))) {
            assertEquals(
                HttpStatus.FORBIDDEN,
                exchange("POST", "/api/catastro/vias/valores", emptyMap<String, Any>(), cuentaDeServicio(roles, org)).first,
                roles.toString()
            )
        }
        for ((query, nombre) in listOf("anio=dos" to "anio", "anio=1800" to "anio", "x=1" to "x")) {
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
    fun `un lector ve el valor guardado y no lo escribe`() {
        val lector = cuentaDeServicio(listOf("CATASTRO_LECTOR"))
        val marca = uniqueName("vtl").uppercase()
        arancel("$marca-01", esteAnio, 50)
        val tramo = tramo(marca, "$marca-01")
        assertEquals(BigDecimal("50") to esteAnio, valor(tramo, lector))
        val (status, cuerpo) = exchange("PATCH", "/api/objects/$TRAMO_VIA/records/$tramo", mapOf("attributes" to mapOf("valor_m2" to 1)), lector)
        assertEquals(HttpStatus.FORBIDDEN, status, cuerpo)
    }

    // valor_m2 and anio_valor of a tramo, read through the record api
    private fun valor(
        tramo: String,
        token: String = admin
    ): Pair<BigDecimal?, Int?> {
        val atributos = arbol(send("GET", "/api/objects/$TRAMO_VIA/records/$tramo", null, HttpStatus.OK, token))["attributes"]
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
