package catastro.wms

import org.springframework.http.ResponseEntity
import org.springframework.stereotype.Service
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.RequestHeader
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController
import wasichai.core.common.Actions
import wasichai.core.common.ForbiddenException
import wasichai.core.common.NotFoundException
import wasichai.core.identity.CurrentUser
import wasichai.core.metadata.MetadataService
import wasichai.gis.GeoServerProperties
import wasichai.gis.geometryFields

// nginx's auth_request in front of GeoServer's WMS (docs/deploy/nginx-catastro-ui.conf): one call per tile, with the
// browser's Authorization and the request's uri in X-Original-URI. 204 lets it through; without a token (or with a bad
// one) core answers 401, and anything else this does not allow is a 403. nginx turns any other status into a 500, so
// every refusal here is one of the two
@RestController
@RequestMapping("/api/catastro/wms")
class AutorizacionWmsController(
    private val autorizacion: AutorizacionWms
) {
    @GetMapping("/autorizar")
    suspend fun autorizar(
        @RequestHeader("X-Original-URI", required = false) uri: String?
    ): ResponseEntity<Void> {
        autorizacion.autorizar(uri)
        return ResponseEntity.noContent().build()
    }
}

// a WMS request passes when the caller is signed in, and every layer it names (PedidoWms) is a geometry of an object
// of the caller's organization (its prefix is the first 8 hex digits of the organizationId, and the object's physical
// table is that one) on which the caller has READ. GeoServer has no notion of either: it serves whatever it is asked
@Service
class AutorizacionWms(
    private val currentUser: CurrentUser,
    private val metadata: MetadataService,
    private val geoserver: GeoServerProperties
) {
    suspend fun autorizar(uri: String?) {
        val usuario = currentUser.require()
        val capas =
            when (val pedido = PedidoWms.leer(uri, geoserver.workspace)) {
                is PedidoWms.Rechazado -> throw ForbiddenException("Pedido WMS no permitido: ${pedido.motivo}")
                is PedidoWms.Capas -> pedido.capas
            }
        val prefijo =
            usuario.organizationId
                .toString()
                .replace("-", "")
                .take(8)
        for (capa in capas) {
            val nombre = listOfNotNull(capa.objeto, capa.prefijo, capa.geometria).joinToString("__")
            if (capa.prefijo != prefijo) throw ForbiddenException("La capa $nombre no es de esta organización")
            val definicion =
                try {
                    metadata.loadDefinition(usuario.organizationId, capa.objeto)
                } catch (_: NotFoundException) {
                    throw ForbiddenException("La capa $nombre no existe")
                }
            val geometrias = definicion.geometryFields.map { it.columnName }
            val existe =
                definicion.obj.physicalTable == "${capa.objeto}__$prefijo" &&
                    if (capa.geometria == null) geometrias.isNotEmpty() else capa.geometria in geometrias
            if (!existe) throw ForbiddenException("La capa $nombre no existe")
            if (!currentUser.hasPermission(usuario, Actions.READ, definicion.obj.id)) {
                throw ForbiddenException("Missing permission ${Actions.READ} on ${capa.objeto}")
            }
        }
    }
}
