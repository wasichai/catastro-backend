package catastro.vias

import catastro.CatastroApiTest
import catastro.valuacion.ARANCEL
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.springframework.http.HttpStatus
import org.springframework.http.MediaType
import tools.jackson.databind.JsonNode
import java.math.BigDecimal
import java.time.LocalDate
import java.time.ZoneId
import kotlin.random.Random

// GET /api/catastro/vias/aranceles end to end, with the real model and role (CatastroApiTest): the tramos de vía as
// GeoJSON in 4326, each with the valor_m2 of its id_aranc for the year asked. the test db is shared and kept between
// runs, so every tramo carries this run's cod_via_eje and only those features are looked at
class ViasApiTest : CatastroApiTest() {
    @Test
    fun `cada tramo trae el valor de su arancel del año, nulo sin arancel o sin código`() {
        val srtm = cuentaDeServicio(listOf("SRTM_LECTOR"))
        val marca = uniqueName("tv").uppercase()
        val frente = "$marca-01"
        val otroFrente = "$marca-02"
        arancel(frente, 2026, 356.00)
        arancel(frente, 2025, 300)
        // the other frente has an arancel only in 2027: in 2026 its tramo has no value, never another year's
        arancel(otroFrente, 2027, 10)
        val ambos = tramo(marca, "AMBOS", frente, "NOMBRE_UNICO", listOf(EJE))
        val izquierdo = tramo(marca, "IZQUIERDO", otroFrente, "CERCANIA", listOf(EJE, OTRO_EJE))
        val sinArancel = tramo(marca, "AMBOS", null, "SIN_ARANCEL", listOf(OTRO_EJE))

        val (status, cuerpo) = exchange("GET", "/api/catastro/vias/aranceles?anio=2026", null, srtm)
        assertEquals(HttpStatus.OK, status, cuerpo)
        val coleccion = arbol(cuerpo)
        assertEquals("FeatureCollection", coleccion["type"].asString())
        val tramos = deLaMarca(coleccion, marca)
        assertEquals(setOf(ambos, izquierdo, sinArancel), tramos.keys)

        val a = tramos.getValue(ambos)
        assertEquals("Feature", a["type"].asString())
        // a one-part MultiLineString answers as its LineString, stored in 32718 and back in 4326
        assertEquals("LineString", a["geometry"]["type"].asString())
        val primero = a["geometry"]["coordinates"][0]
        assertEquals(EJE[0][0], primero[0].asDouble(), 1e-6)
        assertEquals(EJE[0][1], primero[1].asDouble(), 1e-6)
        val p = a["properties"]
        assertEquals(marca, p["cod_via_eje"].asString())
        assertEquals("CA.", p["tip_via"].asString())
        assertEquals("LOS PRUEBA", p["nom_via"].asString())
        assertTrue(p["cuadra"].isNull, p.toString())
        assertEquals("AMBOS", p["lado"].asString())
        assertEquals(frente, p["id_aranc"].asString())
        assertEquals("NOMBRE_UNICO", p["asignacion"].asString())
        assertEquals(2026, p["anio"].asInt())
        numero("356", p["valor_m2"])

        val i = tramos.getValue(izquierdo)
        assertEquals("MultiLineString", i["geometry"]["type"].asString())
        assertEquals(2, i["geometry"]["coordinates"].size())
        assertEquals("IZQUIERDO", i["properties"]["lado"].asString())
        assertEquals("CERCANIA", i["properties"]["asignacion"].asString())
        assertTrue(i["properties"]["valor_m2"].isNull, i.toString())

        val s = tramos.getValue(sinArancel)
        assertTrue(s["properties"]["id_aranc"].isNull, s.toString())
        assertTrue(s["properties"]["valor_m2"].isNull, s.toString())
        assertEquals("SIN_ARANCEL", s["properties"]["asignacion"].asString())
    }

    @Test
    fun `el año elige el valor y sin año es el año en curso`() {
        val marca = uniqueName("tva").uppercase()
        val frente = "$marca-01"
        val esteAnio = LocalDate.now(ZoneId.of("America/Lima")).year
        arancel(frente, 2025, 300)
        arancel(frente, 2026, 356)
        arancel(frente, esteAnio + 1, 999)
        if (esteAnio !in 2025..2026) arancel(frente, esteAnio, 1)
        val id = tramo(marca, "AMBOS", frente, "NOMBRE_UNICO", listOf(EJE))

        fun valor(query: String): JsonNode {
            val coleccion = arbol(send("GET", "/api/catastro/vias/aranceles$query", null, HttpStatus.OK, admin))
            return deLaMarca(coleccion, marca).getValue(id)["properties"]
        }

        numero("300", valor("?anio=2025")["valor_m2"])
        numero("356", valor("?anio=2026")["valor_m2"])
        assertTrue(valor("?anio=2024")["valor_m2"].isNull)
        val sinAnio = valor("")
        assertEquals(esteAnio, sinAnio["anio"].asInt())
        numero(mapOf(2025 to "300", 2026 to "356")[esteAnio] ?: "1", sinAnio["valor_m2"])
    }

    @Test
    fun `responde json`() {
        val respuesta =
            client
                .get()
                .uri("/api/catastro/vias/aranceles?anio=2026")
                .header("Authorization", admin)
                .exchange()
        respuesta.expectStatus().isOk
        val tipo = respuesta.returnResult(String::class.java).responseHeaders.contentType
        assertNotNull(tipo)
        assertTrue(tipo!!.isCompatibleWith(MediaType.APPLICATION_JSON), tipo.toString())
    }

    @Test
    fun `un año que no se lee es un 400 que nombra anio, y un parámetro que sobra también`() {
        for ((query, nombre) in listOf("anio=dos" to "anio", "anio=1800" to "anio", "anio=" to "anio", "anio=2026&page=1" to "page")) {
            val (status, body) = exchange("GET", "/api/catastro/vias/aranceles?$query", null, admin)
            assertEquals(HttpStatus.BAD_REQUEST, status, "$query: $body")
            assertEquals(nombre, arbol(body)["errors"][0]["field"].asString(), body)
        }
    }

    @Test
    fun `sin token 401, sin READ sobre tramo_via 403`() {
        client
            .get()
            .uri("/api/catastro/vias/aranceles?anio=2026")
            .exchange()
            .expectStatus()
            .isUnauthorized
        val sinRol = cuentaDeServicio(emptyList())
        assertEquals(HttpStatus.FORBIDDEN, exchange("GET", "/api/catastro/vias/aranceles?anio=2026", null, sinRol).first)
    }

    @Test
    fun `el lector de catastro ve el mapa con el valor del año`() {
        val lector = cuentaDeServicio(listOf("CATASTRO_LECTOR"))
        val marca = uniqueName("tvl").uppercase()
        arancel("$marca-01", 2026, 120)
        val id = tramo(marca, "AMBOS", "$marca-01", "NOMBRE_UNICO", listOf(EJE))
        val coleccion = arbol(send("GET", "/api/catastro/vias/aranceles?anio=2026", null, HttpStatus.OK, lector))
        numero("120", deLaMarca(coleccion, marca).getValue(id)["properties"]["valor_m2"])
        // read only: it cannot write a tramo
        val (status, cuerpo) =
            exchange("POST", "/api/objects/$TRAMO_VIA/records", mapOf("attributes" to mapOf("clave" to "$marca|x")), lector)
        assertEquals(HttpStatus.FORBIDDEN, status, cuerpo)
    }

    // the features of this run's tramos, by id
    private fun deLaMarca(
        coleccion: JsonNode,
        marca: String
    ): Map<String, JsonNode> =
        coleccion["features"]
            .lista()
            .filter { it["properties"]["cod_via_eje"].asString() == marca }
            .associateBy { it["id"].asString() }

    private fun numero(
        esperado: String,
        nodo: JsonNode
    ) = assertEquals(0, BigDecimal(esperado).compareTo(nodo.decimalValue()), "$esperado != $nodo")

    private fun arancel(
        idAranc: String,
        anio: Int,
        valor: Number
    ) = registro(ARANCEL, mapOf("clave" to "$idAranc|$anio", "id_aranc" to idAranc, "anio" to anio, "valor_m2" to valor))

    private fun tramo(
        codVia: String,
        lado: String,
        idAranc: String?,
        asignacion: String,
        partes: List<List<List<Double>>>
    ): String {
        val fid = Random.nextInt(1, Int.MAX_VALUE)
        return registro(
            TRAMO_VIA,
            mapOf(
                "clave" to "$codVia-$fid|$lado",
                "fid_eje" to fid,
                "cod_via_eje" to codVia,
                "tip_via" to "CA.",
                "nom_via" to "LOS PRUEBA",
                "lado" to lado,
                "id_aranc" to idAranc,
                "asignacion" to asignacion
            ),
            mapOf("geom" to mapOf("type" to "MultiLineString", "coordinates" to partes))
        )
    }

    private companion object {
        // two short axes in Ica (UTM 18S), EPSG:4326
        val EJE = listOf(listOf(-75.7300, -14.0700), listOf(-75.7290, -14.0700))
        val OTRO_EJE = listOf(listOf(-75.7290, -14.0700), listOf(-75.7290, -14.0690))
    }
}
