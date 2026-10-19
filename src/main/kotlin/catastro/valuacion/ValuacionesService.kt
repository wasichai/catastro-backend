package catastro.valuacion

import catastro.RegionNoConfigurada
import catastro.Registros
import catastro.tablas.Region
import catastro.tablas.Tablas
import catastro.tablas.TablasPorRegion
import org.springframework.stereotype.Service
import wasichai.core.common.PageRequest
import wasichai.core.data.RecordQuery
import java.math.BigDecimal
import java.util.UUID

// the autoavalúo of one page of predios for a year, valued on the fly (nothing is stored). every read goes through
// core as the caller: the organization's region, the predios, then their construcciones, obras and aranceles in one
// batch per object
@Service
class ValuacionesService(
    private val registros: Registros,
    private val tablasPorRegion: TablasPorRegion
) {
    suspend fun pagina(
        anio: Int,
        page: Int,
        size: Int
    ): Valuaciones {
        val tablas = tablasDeLaOrganizacion()
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
                item(p, anio, pisos[p.id].orEmpty(), obras[p.id].orEmpty(), p.idAranc?.let { aranceles[it] }, tablas)
            }
        return Valuaciones(anio, VERSION, tablas.region.name, page, size, predios.totalElements ?: 0L, items)
    }

    private fun item(
        p: PredioCatastral,
        anio: Int,
        pisos: List<FichaConstruccion>,
        obras: List<FichaObra>,
        arancel: Arancel?,
        tablas: Tablas
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

    // the tables of the region in the caller's configuracion_catastro (core scopes the read to its organization)
    private suspend fun tablasDeLaOrganizacion(): Tablas {
        val configuraciones =
            registros
                .pagina(CONFIGURACION_CATASTRO, ConfiguracionCatastro::class.java, RecordQuery(page = PageRequest(0, 2), count = false))
                .content
        return tablasPorRegion.de(regionDe(configuraciones))
    }

    companion object {
        // the region an organization's configuracion_catastro records give: exactly one record, with a region the
        // engine has tables for. no record, two, a blank region (or one the caller may not read: core leaves it out)
        // or an option of region_catastro without tables here: RegionNoConfigurada, never a default region
        internal fun regionDe(configuraciones: List<ConfiguracionCatastro>): Region {
            val conocidas = Region.entries.joinToString(" o ")
            val region =
                when (configuraciones.size) {
                    0 -> throw RegionNoConfigurada("no hay un registro de $CONFIGURACION_CATASTRO con la región ($conocidas)")
                    1 -> configuraciones.single().region
                    else -> throw RegionNoConfigurada("hay más de un registro de $CONFIGURACION_CATASTRO; debe haber uno solo ($conocidas)")
                } ?: throw RegionNoConfigurada(
                    "el registro de $CONFIGURACION_CATASTRO no tiene región, o quien llama no puede leer el campo ($conocidas)"
                )
            return Region.entries.firstOrNull { it.name == region }
                ?: throw RegionNoConfigurada("$CONFIGURACION_CATASTRO dice la región «$region», sin tablas en el motor ($conocidas)")
        }

        // the engine's version: srtm stores it with each corrida, so a change in the arithmetic is visible there
        const val VERSION = "valuacion-v1"

        const val TAMANO = 200
        const val TAMANO_MAXIMO = 500
    }
}
