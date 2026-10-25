package catastro.valuacion

import catastro.Registros

// the year's arancel of each vía, by id_aranc, in one batch (Registros.conCampoEn). unique per (id_aranc, anio);
// arancel.clave guards that pair on write. another year's arancel is never taken: a vía without one that year is
// absent from the map. the valuations and the map of vías (catastro.vias) read it the same way
internal suspend fun Registros.arancelesDelAnio(
    idsArancel: Collection<String>,
    anio: Int
): Map<String?, Arancel> =
    if (idsArancel.isEmpty()) {
        emptyMap()
    } else {
        conCampoEn(ARANCEL, Arancel::class.java, "id_aranc", idsArancel.distinct(), filters = mapOf("anio" to anio.toString()))
            .associateBy { it.idAranc }
    }
