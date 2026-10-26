package catastro.wms

import java.net.URLDecoder
import java.nio.charset.StandardCharsets

// a layer a WMS request names, as wasichai-gis names it: `<objeto>__<prefijo>__<geometría>`, the object's physical
// table (its name and the first 8 hex digits of its organization) plus the geometry's column. geometria is null for a
// layer published before ADR-019 of wasichai, named after the table alone (the first geometry's)
data class CapaPedida(
    val objeto: String,
    val prefijo: String,
    val geometria: String?
)

// what nginx asks about (X-Original-URI, the browser's request uri as it came), read from the uri alone, before anyone
// looks at the caller. it lets through only a GetMap, GetFeatureInfo or GetLegendGraphic of WMS, on the paths the
// proxy protects, naming at least one layer of `workspace`, with no parameter that could reach another layer (an SLD,
// a CQL filter) or that it does not know. everything else is Rechazado, never passed on: fail closed
sealed interface PedidoWms {
    data class Capas(
        val capas: List<CapaPedida>
    ) : PedidoWms

    data class Rechazado(
        val motivo: String
    ) : PedidoWms

    companion object {
        fun leer(
            uri: String?,
            workspace: String
        ): PedidoWms {
            if (uri.isNullOrBlank()) return Rechazado("sin X-Original-URI")
            val corte = uri.indexOf('?')
            val ruta = decodificar(if (corte < 0) uri else uri.substring(0, corte), ruta = true) ?: return Rechazado("ruta ilegible")
            val servicio = RUTA.matchEntire(ruta) ?: return Rechazado("ruta que no es de WMS: $ruta")
            val enLaRuta = servicio.groupValues[1].ifEmpty { null }
            if (enLaRuta != null && enLaRuta != workspace) return Rechazado("workspace $enLaRuta")

            val params = mutableMapOf<String, MutableList<String>>()
            for (par in (if (corte < 0) "" else uri.substring(corte + 1)).split('&')) {
                if (par.isEmpty()) continue
                val igual = par.indexOf('=')
                val nombre = decodificar(if (igual < 0) par else par.substring(0, igual)) ?: return Rechazado("parámetro ilegible")
                val valor = (if (igual < 0) "" else decodificar(par.substring(igual + 1))) ?: return Rechazado("valor ilegible de $nombre")
                params.getOrPut(nombre.lowercase()) { mutableListOf() } += valor
            }
            params.keys.firstOrNull { it !in PERMITIDOS }?.let { return Rechazado("parámetro $it") }
            params["service"]?.firstOrNull { !it.equals("WMS", ignoreCase = true) }?.let { return Rechazado("servicio $it") }
            val pedido = params["request"].orEmpty().map { it.lowercase() }.toSet()
            if (pedido.size != 1 || pedido.single() !in PEDIDOS) return Rechazado("request ${params["request"]}")

            // every name of a layer in the request, qualified or not, without its workspace
            fun nombres(claves: Set<String>): List<String>? =
                claves.flatMap { params[it].orEmpty() }.flatMap { it.split(',') }.map { it.trim() }.filter { it.isNotEmpty() }.map { nombre ->
                    val partes = nombre.split(':')
                    when {
                        partes.size == 1 && enLaRuta != null -> nombre
                        partes.size == 2 && partes[0] == workspace -> partes[1]
                        else -> return null
                    }
                }

            val nombresDeCapas = nombres(CAPAS) ?: return Rechazado("capa de otro workspace, o sin workspace")
            if (nombresDeCapas.isEmpty()) return Rechazado("sin capas")
            val capas = nombresDeCapas.distinct().map { capa(it) ?: return Rechazado("capa $it") }
            // a layer's style is named after it (wasichai-gis): one of its layers', or none (the default)
            val estilos = nombres(ESTILOS) ?: return Rechazado("estilo de otro workspace")
            estilos.firstOrNull { it !in nombresDeCapas }?.let { return Rechazado("estilo $it") }
            return Capas(capas)
        }

        private fun capa(nombre: String): CapaPedida? =
            CAPA.matchEntire(nombre)?.let { CapaPedida(it.groupValues[1], it.groupValues[2], it.groupValues[3].ifEmpty { null }) }

        // percent-decoding; a '+' is a space only in the query. null when it cannot be read
        private fun decodificar(
            texto: String,
            ruta: Boolean = false
        ): String? =
            try {
                URLDecoder.decode(if (ruta) texto.replace("+", "%2B") else texto, StandardCharsets.UTF_8)
            } catch (_: IllegalArgumentException) {
                null
            }

        // the locations of the proxy: GeoServer's WMS, of a workspace or global, its OWS endpoint and the tile cache's
        private val RUTA = Regex("/geoserver/(?:([A-Za-z0-9_-]+)/)?(?:wms|ows|gwc/service/wms)")
        private val CAPA = Regex("([a-z][a-z0-9_]*?)__([0-9a-f]{8})(?:__([a-z][a-z0-9_]*))?")
        private val PEDIDOS = setOf("getmap", "getfeatureinfo", "getlegendgraphic")
        private val CAPAS = setOf("layers", "query_layers", "layer", "typename", "typenames")
        private val ESTILOS = setOf("styles", "style")
        private val PERMITIDOS =
            CAPAS + ESTILOS +
                setOf(
                    "service",
                    "version",
                    "request",
                    "format",
                    "transparent",
                    "bgcolor",
                    "exceptions",
                    "width",
                    "height",
                    "srs",
                    "crs",
                    "bbox",
                    "tiled",
                    "tilesorigin",
                    "format_options",
                    "info_format",
                    "feature_count",
                    "x",
                    "y",
                    "i",
                    "j",
                    "legend_options",
                    "scale",
                    "sld_version"
                )
    }
}
