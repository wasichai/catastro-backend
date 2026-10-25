package catastro.brechas

import catastro.CatastroApiTest
import catastro.valuacion.PREDIO_CATASTRAL
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.springframework.http.HttpHeaders
import org.springframework.http.HttpStatus
import org.springframework.http.MediaType
import tools.jackson.databind.JsonNode
import java.math.BigDecimal

// /api/catastro/brechas end to end, with the real model and roles (CatastroApiTest). each test has an organization to
// itself (organizacionNueva), so "the most recent corte" and "no corte at all" are its own; every corte and ficha is
// fictitious and made here, as importar_corte_brecha.py would leave them. a clave goes raw in a uri: WebTestClient's
// template encodes its "|"
class BrechasApiTest : CatastroApiTest() {
    private lateinit var org: String
    private lateinit var email: String

    @BeforeEach
    fun organizacion() {
        val (token, correo) = organizacionNueva()
        org = token
        email = correo
    }

    @Test
    fun `el panel cuadra con las fichas del corte`() {
        val corte = cargarCorte("2026-10-25")
        decidir(listOf("01-01-0001"), "A_FISCALIZAR")

        val panel = arbol(send("GET", "/api/catastro/brechas/panel", null, HttpStatus.OK, org))
        assertEquals("ica-prueba|2026-10-25", panel["corte"]["clave"].asString())
        assertEquals("2026-10-25", panel["corte"]["fecha"].asString())
        assertEquals(2026, panel["corte"]["anio"].asInt())
        assertEquals("corrida-1", panel["corte"]["corrida"].asString())
        val kpis = panel["kpis"]
        assertEquals(6, kpis["fichas"].asInt())
        // 500 + 120.5 + (-30) + 0 + 80 + (none)
        numero("670.5", kpis["delta_impuesto"])
        numero("620.5", kpis["delta_impuesto_confiable"])
        numero("80", kpis["omisos_estimado"])
        assertEquals(2, kpis["supera_5_uit"].asInt())
        assertEquals(5, kpis["pendientes"].asInt())
        assertEquals(2, kpis["con_geometria"].asInt())

        val categorias = panel["por_categoria"].lista().associateBy { it["clave"].asString() }
        assertEquals(CATEGORIAS, panel["por_categoria"].lista().map { it["clave"].asString() })
        assertEquals(2, categorias.getValue("SUBVALUADO")["fichas"].asInt())
        numero("620.5", categorias.getValue("SUBVALUADO")["delta_impuesto"])
        assertEquals(0, categorias.getValue("SIN_VALOR")["fichas"].asInt())
        val confianzas = panel["por_confianza"].lista().associateBy { it["clave"].asString() }
        assertEquals(3, confianzas.getValue("CONFIABLE")["fichas"].asInt())
        assertEquals(2, confianzas.getValue("DUDOSO")["fichas"].asInt())
        assertEquals(1, confianzas.getValue("SIN_LEVANTAR")["fichas"].asInt())
        val estados = panel["por_estado"].lista().associate { it["clave"].asString() to it["fichas"].asInt() }
        assertEquals(mapOf("PENDIENTE" to 5, "A_INSPECCIONAR" to 0, "INSPECCIONADO" to 0, "A_FISCALIZAR" to 1, "DESCARTADO" to 0), estados)
        val sectores = panel["top_sectores"].lista()
        assertEquals(listOf("01", "03", "02"), sectores.map { it["sector"].asString() })
        assertEquals(2, sectores[0]["fichas"].asInt())
        numero("620.5", sectores[0]["delta_impuesto"])

        // by its clave, the same corte
        val porClave = arbol(send("GET", "/api/catastro/brechas/panel?corte=$corte", null, HttpStatus.OK, org))
        assertEquals(6, porClave["kpis"]["fichas"].asInt())
        val (status, cuerpo) = exchange("GET", "/api/catastro/brechas/panel?corte=otra", null, org)
        assertEquals(HttpStatus.NOT_FOUND, status, cuerpo)
    }

    @Test
    fun `los cortes, el más reciente primero`() {
        cargarCorte("2026-09-30")
        cargarCorte("2026-10-25")
        val cortes = arbol(send("GET", "/api/catastro/brechas/cortes", null, HttpStatus.OK, org)).lista()
        assertEquals(listOf("ica-prueba|2026-10-25", "ica-prueba|2026-09-30"), cortes.map { it["clave"].asString() })
        assertEquals(6, cortes[0]["total_fichas"].asInt())
        numero("670.5", cortes[0]["delta_impuesto"])
        assertEquals(2026, cortes[0]["anio"].asInt())
        assertTrue(cortes[0]["cargado_en"].asString().startsWith("2026-10-25"), cortes[0].toString())
    }

    @Test
    fun `cada filtro, cada orden y la paginación`() {
        cargarCorte("2026-10-25")
        decidir(listOf("01-01-0002"), "INSPECCIONADO")

        fun codigos(query: String): List<String> =
            arbol(send("GET", "/api/catastro/brechas/fichas?$query", null, HttpStatus.OK, org))["content"]
                .lista()
                .map { it["codigo_predio"].asString() }

        // delta_desc by default; a ficha without Δ last
        assertEquals(listOf("P1", "P2", "P5", "P4", "P3", "P6"), codigos(""))
        assertEquals(listOf("P3", "P4", "P5", "P2", "P1", "P6"), codigos("orden=delta_asc"))
        // by codigo_catastro, the SIN_CATASTRO without one last
        assertEquals(listOf("P1", "P2", "P3", "P4", "P5", "P6"), codigos("orden=codigo"))
        assertEquals(listOf("P1", "P2", "P5"), codigos("categoria=SUBVALUADO,OMISO"))
        assertEquals(listOf("P3", "P6"), codigos("confianza=DUDOSO"))
        assertEquals(listOf("P1", "P2"), codigos("sector=01"))
        assertEquals(listOf("P2"), codigos("estado=INSPECCIONADO"))
        assertEquals(listOf("P1", "P5", "P4", "P3", "P6"), codigos("estado=PENDIENTE"))
        assertEquals(listOf("P1", "P5"), codigos("supera_5_uit=true"))
        assertEquals(listOf("P2", "P4", "P3", "P6"), codigos("supera_5_uit=false"))
        // |Δ impuesto| >= 30: -30 is in, 0 and the one without Δ are out
        assertEquals(listOf("P1", "P2", "P5", "P3"), codigos("min_delta=30"))
        assertEquals(listOf("P1"), codigos("categoria=SUBVALUADO&supera_5_uit=true&confianza=CONFIABLE"))

        val pagina = arbol(send("GET", "/api/catastro/brechas/fichas?size=4&page=1", null, HttpStatus.OK, org))
        assertEquals(listOf("P3", "P6"), pagina["content"].lista().map { it["codigo_predio"].asString() })
        assertEquals(1, pagina["page"].asInt())
        assertEquals(4, pagina["size"].asInt())
        assertEquals(6, pagina["totalElements"].asInt())
        assertEquals(2, pagina["totalPages"].asInt())
        assertEquals(0, arbol(send("GET", "/api/catastro/brechas/fichas?size=4&page=5", null, HttpStatus.OK, org))["content"].size())

        // a row as the contract lists it
        val fila =
            arbol(send("GET", "/api/catastro/brechas/fichas?orden=codigo&size=2", null, HttpStatus.OK, org))["content"]
                .lista()[1]
        assertEquals("01-01-0002", fila["codigo_municipal"].asString())
        assertEquals("1-1-2", fila["codigo_catastro"].asString())
        assertEquals("INSPECCIONADO", fila["estado"].asString())
        assertEquals(email, fila["responsable"].asString())
        assertFalse(fila["decidido_en"].isNull)
        assertTrue(fila["con_geometria"].asBoolean())
        numero("120.5", fila["delta_impuesto"])
        assertEquals(CAMPOS_DE_FILA, fila.properties().map { it.key })

        for ((query, campo) in listOf(
            "categoria=RARO" to "categoria",
            "confianza=CONFIABLE,X" to "confianza",
            "estado=" to "estado",
            "supera_5_uit=si" to "supera_5_uit",
            "min_delta=abc" to "min_delta",
            "min_delta=-1" to "min_delta",
            "orden=precio" to "orden",
            "size=501" to "size",
            "size=0" to "size",
            "page=-1" to "page",
            "corte=" to "corte",
            "otro=1" to "otro"
        )) {
            val (status, cuerpo) = exchange("GET", "/api/catastro/brechas/fichas?$query", null, org)
            assertEquals(HttpStatus.BAD_REQUEST, status, "$query: $cuerpo")
            assertEquals(campo, arbol(cuerpo)["errors"][0]["field"].asString(), cuerpo)
        }
        val (status, cuerpo) = exchange("GET", "/api/catastro/brechas/lotes?page=1", null, org)
        assertEquals(HttpStatus.BAD_REQUEST, status, cuerpo)
        assertEquals("page", arbol(cuerpo)["errors"][0]["field"].asString(), cuerpo)
    }

    @Test
    fun `los lotes son solo los de las fichas empatadas con geometría`() {
        cargarCorte("2026-10-25")
        val coleccion = arbol(send("GET", "/api/catastro/brechas/lotes", null, HttpStatus.OK, org))
        assertEquals("FeatureCollection", coleccion["type"].asString())
        val features = coleccion["features"].lista().associateBy { it["id"].asString() }
        assertEquals(setOf("01-01-0001", "01-01-0002"), features.keys)
        val f = features.getValue("01-01-0001")
        assertEquals("Feature", f["type"].asString())
        assertEquals("Polygon", f["geometry"]["type"].asString())
        assertEquals(LOTE[0][0], f["geometry"]["coordinates"][0][0][0].asDouble(), 1e-6)
        val p = f["properties"]
        assertEquals(
            listOf("codigo_municipal", "codigo_catastro", "categoria", "confianza", "delta_impuesto", "estado", "supera_5_uit"),
            p.properties().map { it.key }
        )
        assertEquals("1-1-1", p["codigo_catastro"].asString())
        assertEquals("SUBVALUADO", p["categoria"].asString())
        assertEquals("PENDIENTE", p["estado"].asString())
        assertTrue(p["supera_5_uit"].asBoolean())
        numero("500", p["delta_impuesto"])
        // the same filters as the table
        val filtrada = arbol(send("GET", "/api/catastro/brechas/lotes?supera_5_uit=true&orden=codigo", null, HttpStatus.OK, org))
        assertEquals(listOf("01-01-0001"), filtrada["features"].lista().map { it["id"].asString() })
    }

    @Test
    fun `un lote de decisiones crea y actualiza, y descartar pide motivo`() {
        cargarCorte("2026-10-25")
        val primero = decidir(listOf("01-01-0001", "01-01-0002"), "A_INSPECCIONAR", nota = "ver frente")
        assertEquals(2, primero["creadas"].asInt())
        assertEquals(0, primero["actualizadas"].asInt())
        assertEquals(0, primero["errores"].size())

        val segundo = decidir(listOf("01-01-0002", "01-01-0003", "NO-EXISTE"), "DESCARTADO", motivo = "ya fiscalizado")
        assertEquals(1, segundo["creadas"].asInt())
        assertEquals(1, segundo["actualizadas"].asInt())
        assertEquals(listOf("NO-EXISTE"), segundo["errores"].lista().map { it["codigo"].asString() })

        val filas =
            arbol(send("GET", "/api/catastro/brechas/fichas?orden=codigo", null, HttpStatus.OK, org))["content"]
                .lista()
                .associateBy { it["codigo_predio"].asString() }
        assertEquals("A_INSPECCIONAR", filas.getValue("P1")["estado"].asString())
        assertEquals("ver frente", filas.getValue("P1")["nota"].asString())
        assertEquals("DESCARTADO", filas.getValue("P2")["estado"].asString())
        // a decision without nota keeps the one it had
        assertEquals("ver frente", filas.getValue("P2")["nota"].asString())
        assertEquals("DESCARTADO", filas.getValue("P3")["estado"].asString())
        assertEquals(email, filas.getValue("P3")["responsable"].asString())
        val decision =
            arbol(send("GET", "/api/objects/$DECISION_BRECHA/records?clave=01-01-0002|2026", null, HttpStatus.OK, org))["content"][0]["attributes"]
        assertEquals("ya fiscalizado", decision["motivo_descarte"].asString())
        assertEquals("ica-prueba|2026-10-25", decision["corte_origen"].asString())

        for ((cuerpo, campo) in listOf(
            mapOf("codigos" to listOf("01-01-0001"), "anio" to 2026, "estado" to "DESCARTADO") to "motivo_descarte",
            mapOf("codigos" to listOf("01-01-0001"), "anio" to 2026, "estado" to "DESCARTADO", "motivo_descarte" to " ") to "motivo_descarte",
            mapOf("codigos" to emptyList<String>(), "anio" to 2026, "estado" to "PENDIENTE") to "codigos",
            mapOf("codigos" to (1..501).map { "C$it" }, "anio" to 2026, "estado" to "PENDIENTE") to "codigos",
            mapOf("codigos" to listOf("01-01-0001"), "anio" to 2026, "estado" to "OTRO") to "estado",
            mapOf("codigos" to listOf("01-01-0001"), "estado" to "PENDIENTE") to "anio",
            mapOf("codigos" to listOf("01-01-0001"), "anio" to 2026, "estado" to "PENDIENTE", "responsable" to "x@y.z") to "responsable"
        )) {
            val (status, respuesta) = exchange("POST", "/api/catastro/brechas/decisiones", cuerpo, org)
            assertEquals(HttpStatus.BAD_REQUEST, status, "$cuerpo: $respuesta")
            assertEquals(campo, arbol(respuesta)["errors"][0]["field"].asString(), respuesta)
        }
    }

    @Test
    fun `el lector no decide, el analista sí, y sin READ no se ve nada`() {
        cargarCorte("2026-10-25")
        val cuerpo = mapOf("codigos" to listOf("01-01-0001"), "anio" to 2026, "estado" to "A_FISCALIZAR")
        val lector = cuentaDeServicio(listOf("CATASTRO_LECTOR"), org)
        assertEquals(HttpStatus.OK, exchange("GET", "/api/catastro/brechas/panel", null, lector).first)
        val (status, respuesta) = exchange("POST", "/api/catastro/brechas/decisiones", cuerpo, lector)
        assertEquals(HttpStatus.FORBIDDEN, status, respuesta)

        val analista = cuentaDeServicio(listOf("CATASTRO_ANALISTA"), org)
        val hecho = arbol(send("POST", "/api/catastro/brechas/decisiones", cuerpo, HttpStatus.OK, analista))
        assertEquals(1, hecho["creadas"].asInt())
        assertEquals(0, hecho["errores"].size(), hecho.toString())
        assertEquals(1, arbol(send("POST", "/api/catastro/brechas/decisiones", cuerpo, HttpStatus.OK, analista))["actualizadas"].asInt())

        val sinRol = cuentaDeServicio(emptyList(), org)
        for (ruta in listOf("cortes", "panel", "fichas", "lotes", "fichas.csv")) {
            assertEquals(HttpStatus.FORBIDDEN, exchange("GET", "/api/catastro/brechas/$ruta", null, sinRol).first, ruta)
        }
        assertEquals(HttpStatus.FORBIDDEN, exchange("POST", "/api/catastro/brechas/decisiones", cuerpo, sinRol).first)
        client
            .get()
            .uri("/api/catastro/brechas/panel")
            .exchange()
            .expectStatus()
            .isUnauthorized
    }

    @Test
    fun `una decisión sobrevive a un corte nuevo`() {
        cargarCorte("2026-09-30")
        decidir(listOf("01-01-0001"), "A_FISCALIZAR", nota = "prioridad")
        cargarCorte("2026-10-25")
        // without corte, the new one; the decision is by codigo_municipal and year, not by corte
        val panel = arbol(send("GET", "/api/catastro/brechas/panel", null, HttpStatus.OK, org))
        assertEquals("ica-prueba|2026-10-25", panel["corte"]["clave"].asString())
        val fila =
            arbol(send("GET", "/api/catastro/brechas/fichas?estado=A_FISCALIZAR", null, HttpStatus.OK, org))["content"]
                .lista()
                .single()
        assertEquals("01-01-0001", fila["codigo_municipal"].asString())
        assertEquals("prioridad", fila["nota"].asString())
        val viejo = arbol(send("GET", "/api/catastro/brechas/fichas?estado=A_FISCALIZAR&corte=ica-prueba|2026-09-30", null, HttpStatus.OK, org))
        assertEquals(1, viejo["totalElements"].asInt())
    }

    @Test
    fun `el csv trae el bom, la cabecera de la fila y el nombre del corte`() {
        cargarCorte("2026-10-25")
        val resultado =
            client
                .get()
                .uri("/api/catastro/brechas/fichas.csv?categoria=SUBVALUADO")
                .header(HttpHeaders.AUTHORIZATION, org)
                .exchange()
                .expectStatus()
                .isOk
                .expectBody(ByteArray::class.java)
                .returnResult()
        val tipo = resultado.responseHeaders.contentType!!
        assertTrue(tipo.isCompatibleWith(MediaType.parseMediaType("text/csv")), tipo.toString())
        val disposicion = resultado.responseHeaders.contentDisposition
        assertEquals("attachment", disposicion.type)
        assertEquals("brechas-ica-prueba|2026-10-25.csv", disposicion.filename)
        val bytes = resultado.responseBody!!
        assertEquals(listOf(0xEF, 0xBB, 0xBF), bytes.take(3).map { it.toInt() and 0xFF })
        val lineas = String(bytes, Charsets.UTF_8).removePrefix("\uFEFF").split("\r\n").filter { it.isNotEmpty() }
        assertEquals(CAMPOS_DE_FILA.joinToString(","), lineas[0])
        assertEquals(3, lineas.size)
        assertTrue(lineas[1].contains(",01-01-0001,"), lineas[1])
        // the nota with a comma is quoted
        decidir(listOf("01-01-0001"), "A_INSPECCIONAR", nota = "frente, fondo")
        val otra =
            client
                .get()
                .uri("/api/catastro/brechas/fichas.csv?categoria=SUBVALUADO&orden=codigo")
                .header(HttpHeaders.AUTHORIZATION, org)
                .exchange()
                .expectBody(String::class.java)
                .returnResult()
                .responseBody!!
        assertTrue(otra.contains(",\"frente, fondo\","), otra)
    }

    @Test
    fun `sin cortes, 404 con su mensaje`() {
        assertEquals(0, arbol(send("GET", "/api/catastro/brechas/cortes", null, HttpStatus.OK, org)).size())
        for (ruta in listOf("panel", "fichas", "lotes", "fichas.csv")) {
            val (status, cuerpo) = exchange("GET", "/api/catastro/brechas/$ruta", null, org)
            assertEquals(HttpStatus.NOT_FOUND, status, "$ruta: $cuerpo")
            assertEquals("No hay cortes de brecha cargados", arbol(cuerpo)["message"].asString(), cuerpo)
        }
    }

    // a corte of ica-prueba as importar_corte_brecha.py leaves it, with six fichas (two matched with a lote, one
    // matched without, two without ficha, one SIN_CATASTRO) and the three predios_catastrales they match: its clave
    private fun cargarCorte(fecha: String): String {
        val clave = "ica-prueba|$fecha"
        if (!predios) {
            registro(
                PREDIO_CATASTRAL,
                mapOf("codigo_municipal" to "01-01-0001"),
                mapOf("lote_geom" to mapOf("type" to "Polygon", "coordinates" to listOf(LOTE))),
                org
            )
            registro(
                PREDIO_CATASTRAL,
                mapOf("codigo_municipal" to "01-01-0002"),
                mapOf("lote_geom" to mapOf("type" to "Polygon", "coordinates" to listOf(OTRO_LOTE))),
                org
            )
            registro(PREDIO_CATASTRAL, mapOf("codigo_municipal" to "01-01-0003"), null, org)
            predios = true
        }
        val corte =
            registro(
                CORTE_BRECHA,
                mapOf(
                    "clave" to clave,
                    "org_slug" to "ica-prueba",
                    "fecha" to fecha,
                    "corrida" to "corrida-1",
                    "anio" to 2026,
                    "total_fichas" to 6,
                    "delta_impuesto" to "670.5",
                    "cargado_en" to "${fecha}T12:00:00Z"
                ),
                token = org
            )
        val fichas =
            listOf(
                ficha("P1", "1-1-1", "01-01-0001", "SUBVALUADO", "CONFIABLE", "01", "500", "30000", true),
                ficha("P2", "1-1-2", "01-01-0002", "SUBVALUADO", "CONFIABLE", "01", "120.5", "1000", false),
                ficha("P3", "1-1-3", "01-01-0003", "SOBREVALUADO", "DUDOSO", "02", "-30", "-900", false),
                ficha("P4", "9-9-4", null, "COINCIDE", "CONFIABLE", "03", "0", "0", false),
                ficha("P5", "9-9-5", null, "OMISO", "SIN_LEVANTAR", "03", "80", "-40000", true),
                ficha("P6", null, null, "SIN_CATASTRO", "DUDOSO", null, null, null, null)
            )
        for (atributos in fichas) {
            registro(BRECHA_FICHA, atributos + mapOf("corte" to corte, "clave" to "$corte|${atributos["codigo_predio"]}"), token = org)
        }
        return clave
    }

    private var predios = false

    private fun ficha(
        codigoPredio: String,
        codigoCatastro: String?,
        codigoMunicipal: String?,
        categoria: String,
        confianza: String,
        sector: String?,
        deltaImpuesto: String?,
        deltaAutoavaluo: String?,
        supera: Boolean?
    ): Map<String, Any?> =
        mapOf(
            "codigo_predio" to codigoPredio,
            "codigo_catastro" to codigoCatastro,
            "codigo_municipal" to codigoMunicipal,
            "categoria" to categoria,
            "confianza" to confianza,
            "sector" to sector,
            "delta_impuesto" to deltaImpuesto,
            "delta_autoavaluo" to deltaAutoavaluo,
            "supera_5_uit" to supera,
            "estimado" to (categoria == "OMISO")
        ).filterValues { it != null }

    private fun decidir(
        codigos: List<String>,
        estado: String,
        nota: String? = null,
        motivo: String? = null
    ): JsonNode {
        val cuerpo = mutableMapOf<String, Any?>("codigos" to codigos, "anio" to 2026, "estado" to estado)
        if (nota != null) cuerpo["nota"] = nota
        if (motivo != null) cuerpo["motivo_descarte"] = motivo
        return arbol(send("POST", "/api/catastro/brechas/decisiones", cuerpo, HttpStatus.OK, org))
    }

    private fun numero(
        esperado: String,
        nodo: JsonNode
    ) = assertEquals(0, BigDecimal(esperado).compareTo(nodo.decimalValue()), "$esperado != $nodo")

    private companion object {
        // two small lotes in Ica, EPSG:4326
        val LOTE = listOf(listOf(-75.7300, -14.0700), listOf(-75.7299, -14.0700), listOf(-75.7299, -14.0699), listOf(-75.7300, -14.0700))
        val OTRO_LOTE = listOf(listOf(-75.7290, -14.0700), listOf(-75.7289, -14.0700), listOf(-75.7289, -14.0699), listOf(-75.7290, -14.0700))
        val CAMPOS_DE_FILA =
            listOf(
                "id",
                "codigo_catastro",
                "codigo_municipal",
                "codigo_predio",
                "categoria",
                "confianza",
                "confianza_motivo",
                "sector",
                "manzana",
                "lote",
                "uso",
                "autoavaluo_declarado",
                "autoavaluo_catastro",
                "delta_autoavaluo",
                "impuesto_declarado",
                "impuesto_catastro",
                "delta_impuesto",
                "delta_arbitrios",
                "estimado",
                "motivo",
                "supera_5_uit",
                "estado",
                "responsable",
                "nota",
                "decidido_en",
                "con_geometria"
            )
    }
}
