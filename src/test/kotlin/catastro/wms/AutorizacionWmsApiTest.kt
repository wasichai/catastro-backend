package catastro.wms

import catastro.CatastroApiTest
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.springframework.http.HttpStatus

// GET /api/catastro/wms/autorizar end to end, as nginx's auth_request calls it (docs/deploy/nginx-catastro-ui.conf):
// the browser's Bearer and X-Original-URI. 204 only for the caller's own layers with READ on their object
class AutorizacionWmsApiTest : CatastroApiTest() {
    private val ruta = "/api/catastro/wms/autorizar"

    // the first 8 hex digits of the organization of `token`, as wasichai names its tables and layers
    private fun prefijo(token: String): String =
        arbol(send("GET", "/api/auth/me", null, HttpStatus.OK, token))["organizationId"].asString().replace("-", "").take(8)

    private fun estado(
        uri: String,
        token: String
    ): HttpStatus = exchange("GET", ruta, null, token, mapOf("X-Original-URI" to uri)).first

    private fun getMap(vararg capas: String) =
        "/geoserver/catastro/wms?service=WMS&version=1.1.1&request=GetMap&styles=&layers=${capas.joinToString(",")}" +
            "&bbox=-8430000,-1240000,-8420000,-1230000&width=256&height=256&srs=EPSG:3857&format=image/png&transparent=true"

    @Test
    fun `una capa de la organización pasa, y es la que gis publica`() {
        val p = prefijo(admin)
        val tramo = "catastro:tramo_via__${p}__geom"
        assertEquals(HttpStatus.NO_CONTENT, estado(getMap(tramo), admin))
        assertEquals(HttpStatus.NO_CONTENT, estado(getMap(tramo, "catastro:predio_catastral__${p}__lote_geom"), admin))
        // the same name /api/gis/layers gives catastro-ui
        val nombres = arbol(send("GET", "/api/gis/layers", null, HttpStatus.OK, admin)).lista().map { it["layerName"].asString() }
        assertTrue("tramo_via__${p}__geom" in nombres, nombres.toString())
        // the role catastro-ui's readers have
        assertEquals(HttpStatus.NO_CONTENT, estado(getMap(tramo), cuentaDeServicio(listOf("CATASTRO_LECTOR"))))
    }

    @Test
    fun `una capa de otra organización, o una lista que mezcla, es un 403`() {
        val (otra, _) = organizacionNueva()
        val mia = "catastro:tramo_via__${prefijo(admin)}__geom"
        val ajena = "catastro:tramo_via__${prefijo(otra)}__geom"
        assertEquals(HttpStatus.FORBIDDEN, estado(getMap(ajena), admin))
        assertEquals(HttpStatus.FORBIDDEN, estado(getMap(mia, ajena), admin))
        assertEquals(HttpStatus.FORBIDDEN, estado(getMap(ajena, mia), admin))
        // and the other way round: the other organization reads its own, not this one's
        assertEquals(HttpStatus.NO_CONTENT, estado(getMap(ajena), otra))
        assertEquals(HttpStatus.FORBIDDEN, estado(getMap(mia), otra))
    }

    @Test
    fun `sin token 401`() {
        val uri = getMap("catastro:tramo_via__${prefijo(admin)}__geom")
        client
            .get()
            .uri(ruta)
            .header("X-Original-URI", uri)
            .exchange()
            .expectStatus()
            .isUnauthorized
        assertEquals(HttpStatus.UNAUTHORIZED, estado(uri, "Bearer no-es-un-token"))
    }

    @Test
    fun `sin READ sobre el objeto de la capa 403`() {
        val p = prefijo(admin)
        val tramo = "catastro:tramo_via__${p}__geom"
        val brecha = "catastro:brecha_ficha__${p}__lote_geom"
        assertEquals(HttpStatus.FORBIDDEN, estado(getMap(tramo), cuentaDeServicio(emptyList())))
        // srtm's reader has READ on tramo_via but not on brecha_ficha: the list with both is a 403
        val srtm = cuentaDeServicio(listOf("SRTM_LECTOR"))
        assertEquals(HttpStatus.NO_CONTENT, estado(getMap(tramo), srtm))
        assertEquals(HttpStatus.FORBIDDEN, estado(getMap(brecha), srtm))
        assertEquals(HttpStatus.FORBIDDEN, estado(getMap(tramo, brecha), srtm))
    }

    @Test
    fun `los nombres de los parámetros no distinguen mayúsculas`() {
        val p = prefijo(admin)
        val tramo = "tramo_via__${p}__geom"
        val ajena = "tramo_via__0000000a__geom"
        val base = "/geoserver/catastro/wms?SERVICE=wms&Request=GETMAP&FORMAT=image/png&WIDTH=256&Height=256&BBOX=1,2,3,4"
        for (uri in listOf("$base&LAYERS=$tramo", "$base&Layers=catastro:$tramo", "$base&layers=catastro%3A$tramo&TILED=true")) {
            assertEquals(HttpStatus.NO_CONTENT, estado(uri, admin), uri)
        }
        // another organization's layer is caught in any casing and any of the parameters that name a layer
        for (uri in listOf("$base&layers=$tramo&LAYERS=$ajena", "$base&Layers=$tramo,$ajena", "$base&layers=$tramo&TYPENAME=$ajena")) {
            assertEquals(HttpStatus.FORBIDDEN, estado(uri, admin), uri)
        }
    }

    @Test
    fun `sin capas, GetCapabilities, GetFeatureInfo, un formato que no es imagen, o sin X-Original-URI, 403`() {
        val p = prefijo(admin)
        val tramo = "catastro:tramo_via__${p}__geom"
        assertEquals(HttpStatus.FORBIDDEN, estado(getMap(), admin))
        assertEquals(HttpStatus.FORBIDDEN, estado("/geoserver/catastro/wms?service=WMS&request=GetCapabilities", admin))
        assertEquals(
            HttpStatus.FORBIDDEN,
            estado(getMap(tramo).replace("request=GetMap", "request=GetFeatureInfo") + "&query_layers=$tramo&x=0&y=0&info_format=application/json", admin)
        )
        assertEquals(HttpStatus.FORBIDDEN, estado(getMap(tramo).replace("format=image/png", "format=application/vnd.google-earth.kml%2Bxml"), admin))
        assertEquals(HttpStatus.FORBIDDEN, estado(getMap(tramo).replace("width=256", "width=4096"), admin))
        assertEquals(HttpStatus.FORBIDDEN, estado("/geoserver/ows?service=WFS&request=GetFeature&typeName=$tramo", admin))
        assertEquals(HttpStatus.FORBIDDEN, exchange("GET", ruta, null, admin).first)
        // a name that looks like one of its layers but is not a geometry of an object it has
        assertEquals(HttpStatus.FORBIDDEN, estado(getMap("catastro:tramo_via__${p}__clave"), admin))
        assertEquals(HttpStatus.FORBIDDEN, estado(getMap("catastro:no_existe__${p}__geom"), admin))
    }

    // a role of this organization with READ on tramo_via, and the Bearer of a service account holding only it
    private fun conRol(
        ownRecordsOnly: Boolean = false,
        prefijoDelRol: String = "WMS_",
        camposOcultos: List<String> = emptyList()
    ): String {
        val rol = uniqueName(prefijoDelRol).uppercase()
        send("POST", "/api/roles", mapOf("name" to rol, "label" to rol, "ownRecordsOnly" to ownRecordsOnly), HttpStatus.CREATED, admin)
        send("PUT", "/api/roles/$rol/permissions", mapOf("permissions" to listOf(mapOf("objectName" to "tramo_via", "action" to "READ"))), HttpStatus.OK, admin)
        if (camposOcultos.isNotEmpty()) {
            val campos = camposOcultos.map { mapOf("objectName" to "tramo_via", "fieldName" to it, "read" to false, "write" to false) }
            send("PUT", "/api/roles/$rol/field-permissions", mapOf("fields" to campos), HttpStatus.OK, admin)
        }
        return cuentaDeServicio(listOf(rol))
    }

    @Test
    fun `un usuario que no lee todas las filas o todos los campos no recibe teselas`() {
        val tramo = getMap("catastro:tramo_via__${prefijo(admin)}__geom")
        // the same role with no rule passes: what refuses is the rule
        assertEquals(HttpStatus.NO_CONTENT, estado(tramo, conRol()))
        assertEquals(HttpStatus.FORBIDDEN, estado(tramo, conRol(ownRecordsOnly = true)), "owner filter")
        assertEquals(HttpStatus.FORBIDDEN, estado(tramo, conRol(camposOcultos = listOf("nom_via"))), "field rule")
        assertEquals(HttpStatus.FORBIDDEN, estado(tramo, conRol(prefijoDelRol = AlcanceDePrueba.MARCA)), "read scope")
    }

    @Test
    fun `un objeto con una máscara de lectura no se sirve por WMS, ni al administrador`() {
        val (otra, _) = organizacionNueva()
        val objeto = MascaraDePrueba.OBJETO
        val geometria = mapOf("name" to "geom", "label" to "Geometría", "type" to "GEOMETRY", "geometryType" to "POLYGON", "srid" to 4326)
        send(
            "POST",
            "/api/objects",
            mapOf("name" to objeto, "label" to "Enmascarada", "pluralLabel" to "Enmascaradas", "fields" to listOf(geometria)),
            HttpStatus.CREATED,
            otra
        )
        val p = prefijo(otra)
        assertEquals(HttpStatus.FORBIDDEN, estado(getMap("catastro:${objeto}__${p}__geom"), otra))
        assertEquals(HttpStatus.NO_CONTENT, estado(getMap("catastro:tramo_via__${p}__geom"), otra))
    }
}
