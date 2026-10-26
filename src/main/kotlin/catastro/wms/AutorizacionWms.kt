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
import wasichai.core.data.RecordReadMasks
import wasichai.core.data.RecordReadScopes
import wasichai.core.identity.AccessPolicy
import wasichai.core.identity.AuthenticatedUser
import wasichai.core.identity.CurrentUser
import wasichai.core.metadata.MetadataService
import wasichai.core.metadata.ObjectDefinition
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
// table is that one) on which the caller has READ. GeoServer has no notion of either: it serves whatever it is asked.
// a tile draws every row of the layer and colours it by an attribute, so it cannot honour a rule that hides rows or
// fields: a caller under any of them is refused (403), fail closed, rather than shown what the API would not show.
// those are an owner filter (ownRecordsOnly), an app's read scope (ADR-048), a field it cannot read, or a read mask
// (ADR-065). such a caller reads the lotes and tramos as GeoJSON from the API, which applies them
@Service
class AutorizacionWms(
    private val currentUser: CurrentUser,
    private val metadata: MetadataService,
    private val geoserver: GeoServerProperties,
    private val access: AccessPolicy,
    private val readScopes: RecordReadScopes,
    private val masks: RecordReadMasks
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
            restriccion(usuario, definicion)?.let { throw ForbiddenException("La capa $nombre no se sirve por WMS a este usuario: $it") }
        }
    }

    // what keeps the caller from reading every row and field of the object, or null when nothing does
    private suspend fun restriccion(
        usuario: AuthenticatedUser,
        definicion: ObjectDefinition
    ): String? {
        if (access.ownerFilter(usuario) != null) return "solo lee sus propios registros"
        if (readScopes.criteria(usuario, definicion).isNotEmpty()) return "tiene un alcance de lectura"
        val campos = access.fieldAccess(usuario, definicion.obj.id)
        definicion.fields.firstOrNull { !campos.canRead(it.id) }?.let { return "no lee el campo ${it.name}" }
        if (masks.appliesTo(usuario, definicion)) return "una máscara de lectura reescribe sus registros"
        return null
    }
}
