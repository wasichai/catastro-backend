package catastro.valuacion

import catastro.Registros
import catastro.tablas.Tablas
import org.springframework.stereotype.Service
import wasichai.core.common.PageRequest
import wasichai.core.data.RecordQuery
import java.math.BigDecimal
import java.util.UUID

// the autoavalúo of one page of predios for a year, valued on the fly (nothing is stored). every read goes through
// core as the caller: the predios, then their construcciones, obras and aranceles in one batch per object
@Service
class ValuacionesService(
    private val registros: Registros,
    private val tablas: Tablas
) {
    suspend fun pagina(
        anio: Int,
        page: Int,
        size: Int
    ): Valuaciones {
        // by codigo_municipal (unique) so pages are stable. PageRequest's own guard stops at 200; this endpoint allows 500
        val predios =
            registros.pagina(PREDIO_CATASTRAL, PredioCatastral::class.java, RecordQuery(page = PageRequest(page, size), sort = "codigo_municipal"))
        val ids = predios.content.map { UUID.fromString(it.id) }
        // sorted, so the first missing datum of a predio (its motivo) is the same on every call
        val pisos =
            if (ids.isEmpty()) {
                emptyMap()
            } else {
                registros.conCampoEn(CONSTRUCCION, FichaConstruccion::class.java, PREDIO, ids, sort = "piso").groupBy { it.predio }
            }
        val obras =
            if (ids.isEmpty()) {
                emptyMap()
            } else {
                registros.conCampoEn(OBRA_COMPLEMENTARIA, FichaObra::class.java, PREDIO, ids, sort = "codigo_vu").groupBy { it.predio }
            }
        // the arancel is unique per (id_aranc, anio); arancel.clave guards that pair on write
        val idsArancel = predios.content.mapNotNull { it.idAranc }.distinct()
        val aranceles =
            if (idsArancel.isEmpty()) {
                emptyMap()
            } else {
                registros
                    .conCampoEn(ARANCEL, Arancel::class.java, "id_aranc", idsArancel, filters = mapOf("anio" to anio.toString()))
                    .associateBy { it.idAranc }
            }
        val items =
            predios.content.map { p ->
                item(p, anio, pisos[p.id].orEmpty(), obras[p.id].orEmpty(), p.idAranc?.let { aranceles[it] })
            }
        return Valuaciones(anio, VERSION, page, size, predios.totalElements ?: 0L, items)
    }

    private fun item(
        p: PredioCatastral,
        anio: Int,
        pisos: List<FichaConstruccion>,
        obras: List<FichaObra>,
        arancel: Arancel?
    ): ItemValuacion {
        val insumos =
            Insumos(
                anio = anio,
                areaTerreno = p.areaTerreno,
                arancelM2 = arancel?.valorM2,
                uso = p.uso,
                esEdificio = p.esEdificio ?: false,
                construcciones =
                    pisos.map {
                        Construccion(
                            piso = it.piso.orEmpty(),
                            areaConstruida = it.areaConstruida,
                            anioConstruccion = it.anioConstruccion,
                            material = it.material,
                            estado = it.estadoConservacion,
                            muros = it.murosColumnas?.singleOrNull(),
                            techos = it.techos?.singleOrNull(),
                            puertas = it.puertasVentanas?.singleOrNull(),
                            techoIncluido = it.techoIncluido
                        )
                    },
                obras = obras.map { Obra(it.codigoVu, it.cantidad, it.anioConstruccion, it.material, it.estadoConservacion) }
            )
        val v = Valorizacion.valorizar(insumos, tablas)
        val valor = v as? Valuacion.Valorizada
        val falta = v as? Valuacion.SinValorizar
        return ItemValuacion(
            codigoMunicipal = p.codigoMunicipal,
            codigoCpu = p.codigoCpu,
            sector = p.sector,
            manzana = p.manzana,
            lote = p.lote,
            uso = p.uso,
            areaTerreno = p.areaTerreno,
            areaConstruida = pisos.mapNotNull { it.areaConstruida }.fold(BigDecimal.ZERO, BigDecimal::add),
            longitudFrente = p.longitudFrente,
            terreno = valor?.terreno,
            construccion = valor?.construccion,
            obras = valor?.obras,
            autoavaluo = valor?.autoavaluo,
            motivo = falta?.motivo,
            llave = falta?.llave,
            loteGeom = p.loteGeom
        )
    }

    companion object {
        // the engine's version: srtm stores it with each corrida, so a change in the arithmetic is visible there
        const val VERSION = "valuacion-v1"

        const val TAMANO = 200
        const val TAMANO_MAXIMO = 500
    }
}
