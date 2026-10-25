package catastro.vias

import catastro.Registros
import catastro.copias.CopiasDelMapa
import catastro.copias.CopiasHechas
import catastro.valuacion.arancelesDelAnio
import org.springframework.stereotype.Service
import wasichai.core.common.ForbiddenException
import wasichai.core.identity.CurrentUser
import wasichai.gis.FeatureCollection

// the tramos de vía with their arancel of a year, for catastro-ui's map. read as the caller through core: every
// tramo_via in one keyset pass, then their aranceles of that year in one batch by id_aranc, as the valuations read them
@Service
class ViasService(
    private val registros: Registros,
    private val copias: CopiasDelMapa,
    private val currentUser: CurrentUser
) {
    suspend fun aranceles(anio: Int): FeatureCollection {
        // by clave (unique), so the order is the same on every call
        val tramos = registros.todas(TRAMO_VIA, TramoVia::class.java, sort = "clave")
        val aranceles = registros.arancelesDelAnio(tramos.mapNotNull { it.idAranc }, anio)
        return FeatureCollection(tramos.mapNotNull { feature(it, anio, it.idAranc?.let { id -> aranceles[id]?.valorM2 }) })
    }

    // a run of the map's copies for the caller's organization, awaited (CopiasDelMapa writes them, as the platform, in
    // its own scope): for the organization's admin only (a service account never is one)
    suspend fun recalcular(): CopiasHechas {
        val usuario = currentUser.require()
        if (!usuario.isAdmin) throw ForbiddenException("Solo el administrador de la organización recalcula las copias del mapa")
        return copias.ahora(usuario.organizationId)
    }
}
