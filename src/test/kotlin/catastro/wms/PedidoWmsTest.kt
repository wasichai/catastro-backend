package catastro.wms

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

// the uri nginx asks about (X-Original-URI) read into the layers it names, before anyone looks at the caller: what is
// not a raster GetMap of the workspace's own WMS is refused here
class PedidoWmsTest {
    private fun capas(uri: String): List<CapaPedida> {
        val pedido = PedidoWms.leer(uri, "catastro")
        assertTrue(pedido is PedidoWms.Capas, "$uri: $pedido")
        return (pedido as PedidoWms.Capas).capas
    }

    private fun rechazado(uri: String?) {
        val pedido = PedidoWms.leer(uri, "catastro")
        assertTrue(pedido is PedidoWms.Rechazado, "$uri: $pedido")
    }

    private val tramo = CapaPedida("tramo_via", "7c45fb26", "geom")
    private val lote = CapaPedida("predio_catastral", "7c45fb26", "lote_geom")
    private val ruta = "/geoserver/catastro/wms"

    // a tile as catastro-ui asks it (wmsTileUrl), with `extra` at the end
    private fun getMap(
        capas: String = "catastro:tramo_via__7c45fb26__geom",
        extra: String = ""
    ) = "$ruta?service=WMS&version=1.1.1&request=GetMap&styles=&layers=$capas" +
        "&bbox=-8430000,-1240000,-8420000,-1230000&width=256&height=256&srs=EPSG:3857&format=image/png&transparent=true$extra"

    @Test
    fun `un GetMap de una capa del workspace la nombra`() {
        assertEquals(listOf(tramo), capas(getMap()))
        assertEquals(listOf(tramo), capas(getMap("tramo_via__7c45fb26__geom")))
        assertEquals(listOf(tramo), capas(getMap("catastro%3Atramo_via__7c45fb26__geom")))
        assertEquals(listOf(tramo), capas(getMap(extra = "&tiled=true&format_options=dpi:180;antialias:full")))
    }

    @Test
    fun `los nombres de los parámetros no distinguen mayúsculas, y una lista nombra cada capa`() {
        val base = "$ruta?SERVICE=wms&Request=GETMAP&FORMAT=image/png&WIDTH=256&Height=512"
        for (uri in listOf(
            "$base&LAYERS=tramo_via__7c45fb26__geom,predio_catastral__7c45fb26__lote_geom",
            "$base&Layers=tramo_via__7c45fb26__geom,%20predio_catastral__7c45fb26__lote_geom",
            "$base&layers=tramo_via__7c45fb26__geom&LAYERS=predio_catastral__7c45fb26__lote_geom",
            "$base&layers=tramo_via__7c45fb26__geom&typeName=predio_catastral__7c45fb26__lote_geom"
        )) {
            assertEquals(listOf(tramo, lote), capas(uri), uri)
        }
    }

    @Test
    fun `la capa de antes de ADR-019 de wasichai, sin columna, es la de la primera geometría`() {
        assertEquals(listOf(CapaPedida("tramo_via", "7c45fb26", null)), capas(getMap("tramo_via__7c45fb26")))
    }

    @Test
    fun `solo GetMap de WMS, con capas`() {
        rechazado(null)
        rechazado("")
        rechazado(getMap(""))
        rechazado(getMap().replace("request=GetMap", "request=GetCapabilities"))
        rechazado(getMap().replace("request=GetMap", "request=GetFeatureInfo") + "&query_layers=tramo_via__7c45fb26__geom&x=1&y=1")
        rechazado(getMap().replace("request=GetMap", "request=GetLegendGraphic"))
        rechazado(getMap().replace("request=GetMap", "request=DescribeLayer"))
        rechazado(getMap().replace("&request=GetMap", ""))
        rechazado(getMap(extra = "&request=GetCapabilities"))
        rechazado(getMap().replace("service=WMS", "service=WFS"))
        rechazado(getMap().replace("service=WMS&", ""))
    }

    @Test
    fun `solo formatos de imagen`() {
        for (formato in listOf("image/png8", "image/jpeg", "image/webp", "IMAGE/PNG")) {
            assertEquals(listOf(tramo), capas(getMap().replace("format=image/png", "format=$formato")), formato)
        }
        for (formato in listOf(
            "application/vnd.google-earth.kml%2Bxml",
            "application/json;type=utfgrid",
            "application/rss%2Bxml",
            "application/atom%2Bxml",
            "image/svg%2Bxml",
            "application/pdf",
            "application/openlayers",
            "text/html"
        )) {
            rechazado(getMap().replace("format=image/png", "format=$formato"))
        }
        rechazado(getMap().replace("&format=image/png", ""))
        rechazado(getMap(extra = "&format=application/pdf"))
        rechazado(getMap(extra = "&format_options=kmattr:true"))
        rechazado(getMap(extra = "&format_options=dpi:90;kmscore:0"))
    }

    @Test
    fun `el tamaño va de 1 a 2048 y a lo más 10 capas`() {
        assertEquals(listOf(tramo), capas(getMap().replace("width=256&height=256", "width=2048&height=2048")))
        for (tamano in listOf("width=2049&height=256", "width=256&height=8192", "width=0&height=256", "width=x&height=256", "height=256")) {
            rechazado(getMap().replace("width=256&height=256", tamano))
        }
        rechazado(getMap(extra = "&width=512"))
        val once = (1..11).joinToString(",") { "o$it" + "__7c45fb26__geom" }
        rechazado(getMap(once))
        assertEquals(10, capas(getMap((1..10).joinToString(",") { "o$it" + "__7c45fb26__geom" })).size)
    }

    @Test
    fun `un parámetro que puede leer otra capa, o que no se conoce, se rechaza`() {
        for (extra in listOf(
            "sld_body=%3CStyledLayerDescriptor%3E",
            "SLD=http://x/y.sld",
            "cql_filter=INCLUDE",
            "filter=x",
            "featureid=1",
            "viewparams=a:b",
            "feature_count=1000",
            "info_format=text/html",
            "query_layers=tramo_via__7c45fb26__geom",
            "exceptions=text/xml",
            "otro=1"
        )) {
            rechazado(getMap(extra = "&$extra"))
        }
    }

    @Test
    fun `un estilo es vacío o el de una de sus capas`() {
        assertEquals(listOf(tramo), capas(getMap().replace("styles=", "styles=tramo_via__7c45fb26__geom")))
        assertEquals(listOf(tramo), capas(getMap().replace("styles=", "styles=catastro:tramo_via__7c45fb26__geom")))
        rechazado(getMap().replace("styles=", "styles=brecha_ficha__0a0b0c0d__lote_geom"))
        rechazado(getMap().replace("styles=", "styles=polygon"))
    }

    @Test
    fun `una capa de otro workspace, o con un nombre que no es de wasichai, se rechaza`() {
        rechazado(getMap("otro:tramo_via__7c45fb26__geom"))
        rechazado(getMap("un_grupo"))
        rechazado(getMap("tramo_via__7C45FB26__geom"))
        rechazado(getMap("tramo_via__7c45fb2__geom"))
        rechazado(getMap("catastro:a:tramo_via__7c45fb26__geom"))
    }

    @Test
    fun `solo la ruta del WMS del workspace`() {
        for (otra in listOf(
            "/geoserver/wms",
            "/geoserver/ows",
            "/geoserver/catastro/ows",
            "/geoserver/gwc/service/wms",
            "/geoserver/catastro/gwc/service/wms",
            "/geoserver/otro/wms",
            "/geoserver/rest/layers",
            "/geoserver/catastro/wfs",
            "/geoserver/catastro/wms/../../rest",
            "/geoserver/catastro/wms%2F..%2Frest",
            "/geoserver/catastro/wmsx",
            "/geoserver//catastro/wms",
            "/geoserver/catastro/wms;jsessionid=1"
        )) {
            rechazado(getMap().replace(ruta, otra))
        }
        rechazado(getMap(extra = "&layers=%ZZ"))
    }
}
