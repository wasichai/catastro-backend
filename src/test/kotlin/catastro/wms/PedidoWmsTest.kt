package catastro.wms

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

// the uri nginx asks about (X-Original-URI) read into the layers it names, before anyone looks at the caller: what is
// not a GetMap, GetFeatureInfo or GetLegendGraphic of the workspace's own layers is refused here
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

    @Test
    fun `un GetMap de una capa del workspace la nombra`() {
        assertEquals(
            listOf(tramo),
            capas("/geoserver/catastro/wms?service=WMS&version=1.1.1&request=GetMap&styles=&layers=catastro:tramo_via__7c45fb26__geom&bbox=1,2,3,4")
        )
        // the service of the workspace with the bare name, the global one with the qualified name, and the tile cache
        assertEquals(listOf(tramo), capas("/geoserver/catastro/wms?request=GetMap&layers=tramo_via__7c45fb26__geom"))
        assertEquals(listOf(tramo), capas("/geoserver/wms?request=GetMap&layers=catastro:tramo_via__7c45fb26__geom"))
        assertEquals(listOf(tramo), capas("/geoserver/ows?service=WMS&request=GetMap&layers=catastro%3Atramo_via__7c45fb26__geom"))
        assertEquals(listOf(tramo), capas("/geoserver/gwc/service/wms?request=GetMap&layers=catastro:tramo_via__7c45fb26__geom&tiled=true"))
    }

    @Test
    fun `los nombres de los parámetros no distinguen mayúsculas, y una lista nombra cada capa`() {
        val lote = CapaPedida("predio_catastral", "7c45fb26", "lote_geom")
        for (uri in listOf(
            "/geoserver/catastro/wms?REQUEST=GetMap&LAYERS=tramo_via__7c45fb26__geom,predio_catastral__7c45fb26__lote_geom",
            "/geoserver/catastro/wms?Request=getmap&Layers=tramo_via__7c45fb26__geom,%20predio_catastral__7c45fb26__lote_geom",
            "/geoserver/catastro/wms?request=GETMAP&layers=tramo_via__7c45fb26__geom&LAYERS=predio_catastral__7c45fb26__lote_geom"
        )) {
            assertEquals(listOf(tramo, lote), capas(uri), uri)
        }
        // GetFeatureInfo names them in query_layers too, and GetLegendGraphic in layer; typeName also counts
        assertEquals(
            listOf(tramo, lote),
            capas("/geoserver/catastro/wms?request=GetFeatureInfo&layers=tramo_via__7c45fb26__geom&QUERY_LAYERS=predio_catastral__7c45fb26__lote_geom")
        )
        assertEquals(listOf(tramo), capas("/geoserver/catastro/wms?request=GetLegendGraphic&LAYER=tramo_via__7c45fb26__geom&format=image/png"))
        assertEquals(
            listOf(tramo, lote),
            capas("/geoserver/catastro/wms?request=GetMap&layers=tramo_via__7c45fb26__geom&typeName=predio_catastral__7c45fb26__lote_geom")
        )
    }

    @Test
    fun `la capa de antes de ADR-019 de wasichai, sin columna, es la de la primera geometría`() {
        assertEquals(listOf(CapaPedida("tramo_via", "7c45fb26", null)), capas("/geoserver/catastro/wms?request=GetMap&layers=tramo_via__7c45fb26"))
    }

    @Test
    fun `sin capas, o con otro pedido que un mapa, una leyenda o una consulta, se rechaza`() {
        rechazado(null)
        rechazado("")
        rechazado("/geoserver/catastro/wms?request=GetMap")
        rechazado("/geoserver/catastro/wms?request=GetMap&layers=")
        rechazado("/geoserver/catastro/wms?request=GetCapabilities&service=WMS")
        rechazado("/geoserver/catastro/wms?REQUEST=getcapabilities")
        rechazado("/geoserver/catastro/wms?layers=tramo_via__7c45fb26__geom")
        rechazado("/geoserver/catastro/wms?request=DescribeLayer&layers=tramo_via__7c45fb26__geom")
        rechazado("/geoserver/catastro/ows?service=WFS&request=GetFeature&typeName=tramo_via__7c45fb26__geom")
        rechazado("/geoserver/catastro/ows?service=WFS&request=GetMap&layers=tramo_via__7c45fb26__geom")
    }

    @Test
    fun `un parámetro que puede leer otra capa, o que no se conoce, se rechaza`() {
        val base = "/geoserver/catastro/wms?request=GetMap&layers=tramo_via__7c45fb26__geom"
        // an SLD names its own layers (and SLD= makes GeoServer fetch a url); a CQL filter can query another layer
        for (extra in listOf(
            "sld_body=%3CStyledLayerDescriptor%3E",
            "SLD=http://x/y.sld",
            "cql_filter=INCLUDE",
            "filter=x",
            "featureid=1",
            "viewparams=a:b",
            "otro=1"
        )) {
            rechazado("$base&$extra")
        }
    }

    @Test
    fun `un estilo es vacío o el de una de sus capas`() {
        assertEquals(listOf(tramo), capas("/geoserver/catastro/wms?request=GetMap&layers=tramo_via__7c45fb26__geom&styles=tramo_via__7c45fb26__geom"))
        assertEquals(
            listOf(tramo),
            capas("/geoserver/catastro/wms?request=GetMap&layers=catastro:tramo_via__7c45fb26__geom&styles=catastro:tramo_via__7c45fb26__geom")
        )
        rechazado("/geoserver/catastro/wms?request=GetMap&layers=tramo_via__7c45fb26__geom&styles=brecha_ficha__0a0b0c0d__lote_geom")
        rechazado("/geoserver/catastro/wms?request=GetMap&layers=tramo_via__7c45fb26__geom&styles=polygon")
    }

    @Test
    fun `una capa de otro workspace, sin workspace, o con un nombre que no es de wasichai, se rechaza`() {
        rechazado("/geoserver/otro/wms?request=GetMap&layers=tramo_via__7c45fb26__geom")
        rechazado("/geoserver/catastro/wms?request=GetMap&layers=otro:tramo_via__7c45fb26__geom")
        rechazado("/geoserver/wms?request=GetMap&layers=tramo_via__7c45fb26__geom")
        rechazado("/geoserver/catastro/wms?request=GetMap&layers=un_grupo")
        rechazado("/geoserver/catastro/wms?request=GetMap&layers=tramo_via__7C45FB26__geom")
        rechazado("/geoserver/catastro/wms?request=GetMap&layers=tramo_via__7c45fb2__geom")
        rechazado("/geoserver/catastro/wms?request=GetMap&layers=catastro:a:tramo_via__7c45fb26__geom")
    }

    @Test
    fun `solo las rutas de WMS que nginx protege`() {
        rechazado("/geoserver/rest/layers?request=GetMap&layers=tramo_via__7c45fb26__geom")
        rechazado("/geoserver/catastro/wfs?request=GetMap&layers=tramo_via__7c45fb26__geom")
        rechazado("/geoserver/catastro/wms/../../rest?request=GetMap&layers=tramo_via__7c45fb26__geom")
        rechazado("/geoserver/catastro/wms%2F..%2Frest?request=GetMap&layers=tramo_via__7c45fb26__geom")
        rechazado("/geoserver/catastro/wmsx?request=GetMap&layers=tramo_via__7c45fb26__geom")
        rechazado("/geoserver/catastro/wms?request=GetMap&layers=%ZZ")
    }
}
