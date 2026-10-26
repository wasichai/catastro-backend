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
        for (uri in listOf(
            "/geoserver/catastro/wms?REQUEST=GetMap&LAYERS=$tramo",
            "/geoserver/catastro/wms?Request=getmap&Layers=catastro:$tramo",
            "/geoserver/wms?request=GETMAP&layers=catastro%3A$tramo",
            "/geoserver/gwc/service/wms?SERVICE=wms&REQUEST=GetMap&LAYERS=catastro:$tramo&TILED=true",
            "/geoserver/catastro/wms?request=GetFeatureInfo&layers=$tramo&QUERY_LAYERS=$tramo&info_format=application/json&x=1&y=1",
            "/geoserver/catastro/ows?service=WMS&request=GetLegendGraphic&LAYER=$tramo&format=image/png"
        )) {
            assertEquals(HttpStatus.NO_CONTENT, estado(uri, admin), uri)
        }
        // another organization's layer is caught in any casing and any of the parameters that name a layer
        for (uri in listOf(
            "/geoserver/catastro/wms?request=GetMap&layers=$tramo&LAYERS=$ajena",
            "/geoserver/catastro/wms?request=GetMap&Layers=$tramo,$ajena",
            "/geoserver/catastro/wms?request=GetFeatureInfo&layers=$tramo&Query_Layers=$ajena",
            "/geoserver/catastro/wms?request=GetMap&layers=$tramo&TYPENAME=$ajena",
            "/geoserver/catastro/wms?request=GetLegendGraphic&Layer=$ajena"
        )) {
            assertEquals(HttpStatus.FORBIDDEN, estado(uri, admin), uri)
        }
    }

    @Test
    fun `sin capas, GetCapabilities, o sin X-Original-URI, 403`() {
        assertEquals(HttpStatus.FORBIDDEN, estado("/geoserver/catastro/wms?request=GetMap", admin))
        assertEquals(HttpStatus.FORBIDDEN, estado("/geoserver/catastro/wms?service=WMS&request=GetCapabilities", admin))
        assertEquals(HttpStatus.FORBIDDEN, estado("/geoserver/ows?service=WFS&request=GetFeature&typeName=catastro:tramo_via__${prefijo(admin)}__geom", admin))
        assertEquals(HttpStatus.FORBIDDEN, exchange("GET", ruta, null, admin).first)
        // a name that looks like one of its layers but is not a geometry of an object it has
        val p = prefijo(admin)
        assertEquals(HttpStatus.FORBIDDEN, estado(getMap("catastro:tramo_via__${p}__clave"), admin))
        assertEquals(HttpStatus.FORBIDDEN, estado(getMap("catastro:no_existe__${p}__geom"), admin))
    }
}
