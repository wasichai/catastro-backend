package catastro.cambios

import catastro.Registros
import catastro.valuacion.ENTREGA_CATASTRAL
import catastro.valuacion.EntregaCatastral
import org.springframework.stereotype.Service
import wasichai.core.common.Actions
import wasichai.core.identity.CurrentUser
import wasichai.core.metadata.MetadataService

// one page of the catastro's changes after a cursor (contract 3). the audit log is read in-process, so the
// permission core would check is checked here first: READ on each object srtm follows and on entrega_catastral (whose
// codigos name the entregas), core's 403 otherwise. SRTM_LECTOR holds all five
@Service
class CambiosService(
    private val currentUser: CurrentUser,
    private val metadata: MetadataService,
    private val bitacora: BitacoraDeCambios,
    private val registros: Registros
) {
    suspend fun pagina(
        desde: String?,
        size: Int
    ): Cambios {
        val usuario = currentUser.require()
        val organizacion = usuario.organizationId
        val definiciones = (LecturaDeCambios.OBJETOS + ENTREGA_CATASTRAL).associateWith { metadata.loadDefinition(organizacion, it) }
        definiciones.values.forEach { currentUser.requirePermission(usuario, Actions.READ, it.obj.id) }
        val cursor = desde?.let { CursorCambios.leer(it) }

        // one row more than the page tells whether there is more
        val filas = bitacora.filas(organizacion, cursor, size + 1)
        val pagina = filas.take(size)
        val codigos = bitacora.codigosDePredios(organizacion, pagina.mapNotNull { LecturaDeCambios.predioDe(it) })
        val entregas = entregas(pagina)
        val camposDe = LecturaDeCambios.OBJETOS.associateWith { objeto -> definiciones.getValue(objeto).fields.map { it.name } }
        return Cambios(
            items = pagina.map { LecturaDeCambios.cambio(it, codigos, entregas, camposDe) },
            cursor = pagina.lastOrNull()?.let { CursorCambios(it.en, it.id).codificar() } ?: desde,
            hayMas = filas.size > size
        )
    }

    // the razones of a page that are an existing entrega's codigo, read as the caller (Registros.conCampoEn)
    private suspend fun entregas(pagina: List<FilaBitacora>): Set<String> {
        val razones = pagina.mapNotNull { it.razon }.distinct()
        if (razones.isEmpty()) return emptySet()
        return registros.conCampoEn(ENTREGA_CATASTRAL, EntregaCatastral::class.java, "codigo", razones).mapNotNull { it.codigo }.toSet()
    }

    companion object {
        const val TAMANO = 200
        const val TAMANO_MAXIMO = 500
    }
}
