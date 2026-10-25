package catastro.vias

import catastro.Registros
import catastro.valuacion.arancelesDelAnio
import org.springframework.stereotype.Service
import wasichai.gis.FeatureCollection

// the tramos de vía with their arancel of a year, for catastro-ui's map. read as the caller through core: every
// tramo_via in one keyset pass, then their aranceles of that year in one batch by id_aranc, as the valuations read them
@Service
class ViasService(
    private val registros: Registros
) {
    suspend fun aranceles(anio: Int): FeatureCollection {
        // by clave (unique), so the order is the same on every call
        val tramos = registros.todas(TRAMO_VIA, TramoVia::class.java, sort = "clave")
        val aranceles = registros.arancelesDelAnio(tramos.mapNotNull { it.idAranc }, anio)
        return FeatureCollection(tramos.mapNotNull { feature(it, anio, it.idAranc?.let { id -> aranceles[id]?.valorM2 }) })
    }
}
