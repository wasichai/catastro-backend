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
                registros
                    .conCampoEn(CONSTRUCCION, FichaConstruccion::class.java, PREDIO, ids, sort = "piso")
                    .groupBy { it.predio }
                    .mapValues { (_, delPredio) -> porSeccion(delPredio) }
            }
        val obras =
            if (ids.isEmpty()) {
                emptyMap()
            } else {
                registros.conCampoEn(OBRA_COMPLEMENTARIA, FichaObra::class.java, PREDIO, ids, sort = "codigo_vu").groupBy { it.predio }
            }
        val aranceles = aranceles(predios.content.mapNotNull { it.idAranc }, anio)
        val entregas = entregas(predios.content.mapNotNull { it.entrega })
        val items =
            predios.content.map { p ->
                item(p, anio, pisos[p.id].orEmpty(), obras[p.id].orEmpty(), p.idAranc?.let { aranceles[it] }, tablas, entregas)
            }
        return Valuaciones(anio, VERSION, tablas.region.name, page, size, predios.totalElements ?: 0L, items)
    }

    private fun item(
        p: PredioCatastral,
        anio: Int,
        pisos: List<FichaConstruccion>,
        obras: List<FichaObra>,
        arancel: Arancel?,
        tablas: Tablas,
        entregas: Map<String, EntregaCatastral>
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
                            techoIncluido = it.techoIncluido,
                            clasificacion = it.clasificacion,
                            seccion = it.seccion
                        )
                    },
                obras = obras.map { Obra(it.codigoVu, it.cantidad, it.anioConstruccion, it.material, it.estadoConservacion) },
                levantamiento = p.estadoLevantamiento
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
            loteGeom = p.loteGeom,
            estadoLevantamiento = p.estadoLevantamiento,
            fechaLevantamiento = p.fechaLevantamiento,
            entrega = p.entrega?.let { entregas[it]?.codigo },
            vinculoMetodo = p.vinculoMetodo,
            vinculoRevisado = p.vinculoRevisado,
            cuc = p.cuc,
            codigoReferenciaCatastral = p.codigoReferenciaCatastral
        )
    }

    // one predio's insumos sent whole (POST /api/catastro/valuacion), valued with the organization's tables like a
    // page. without arancelM2, the arancel of the stored ficha whose codigo_municipal the body names, as a page finds it;
    // a code the catastro does not have (or the caller cannot read) leaves it null, the engine's ARANCEL_FALTANTE
    suspend fun valuar(pedido: PedidoValuacion): ValuacionDeInsumos {
        val tablas = tablasDeLaOrganizacion()
        val dado = pedido.insumos.arancelM2
        val codigo = pedido.codigoMunicipal
        val deLaFicha =
            if (dado != null || codigo.isNullOrBlank()) {
                null
            } else {
                registros
                    .conCampoEn(PREDIO_CATASTRAL, PredioCatastral::class.java, "codigo_municipal", listOf(codigo))
                    .firstOrNull()
                    ?.idAranc
                    ?.let { aranceles(listOf(it), pedido.insumos.anio)[it]?.valorM2 }
            }
        val insumos = if (deLaFicha == null) pedido.insumos else pedido.insumos.copy(arancelM2 = deLaFicha)
        val v = Valorizacion.valorizar(insumos, tablas)
        val valor = v as? Valuacion.Valorizada
        val falta = v as? Valuacion.SinValorizar
        return ValuacionDeInsumos(
            anio = insumos.anio,
            version = VERSION,
            region = tablas.region.name,
            codigoMunicipal = codigo,
            arancelM2 = insumos.arancelM2,
            origenArancel =
                when {
                    dado != null -> ValuacionDeInsumos.CUERPO
                    deLaFicha != null -> ValuacionDeInsumos.FICHA
                    else -> null
                },
            terreno = valor?.terreno,
            construccion = valor?.construccion,
            obras = valor?.obras,
            autoavaluo = valor?.autoavaluo,
            motivo = falta?.motivo,
            llave = falta?.llave,
            detalle = valor?.detalle
        )
    }

    // the year's arancel of each vía, by id_aranc. unique per (id_aranc, anio); arancel.clave guards that pair on write
    private suspend fun aranceles(
        idsArancel: List<String>,
        anio: Int
    ): Map<String?, Arancel> =
        if (idsArancel.isEmpty()) {
            emptyMap()
        } else {
            registros
                .conCampoEn(ARANCEL, Arancel::class.java, "id_aranc", idsArancel.distinct(), filters = mapOf("anio" to anio.toString()))
                .associateBy { it.idAranc }
        }

    // the entregas the page's predios point at, read once by id (Registros.porIds): the item's "entrega" key is the
    // codigo, never the relation's own id
    private suspend fun entregas(idsEntrega: List<String>): Map<String, EntregaCatastral> =
        if (idsEntrega.isEmpty()) {
            emptyMap()
        } else {
            registros.porIds(ENTREGA_CATASTRAL, EntregaCatastral::class.java, idsEntrega.distinct().map { UUID.fromString(it) }).associateBy { it.id }
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

        // the engine's version: srtm stores it with each corrida, so a change in the arithmetic is visible there.
        // v1: the RNT tabla of the predio's uso, unrounded VU. v2: the tabla of each construction's clasificación, and the
        // costa's VU to the céntimo (Region.redondeaValorUnitario). a selva predio without clasificaciones keeps v1's figure
        const val VERSION = "valuacion-v2"

        const val TAMANO = 200
        const val TAMANO_MAXIMO = 500
    }
}

// core sorts by one field: the secciones of a piso keep the pisos' order and go by seccion (null is 1) among them
internal fun porSeccion(pisos: List<FichaConstruccion>): List<FichaConstruccion> {
    val orden =
        pisos
            .map { it.piso }
            .distinct()
            .withIndex()
            .associate { (n, piso) -> piso to n }
    return pisos.sortedWith(compareBy({ orden.getValue(it.piso) }, { it.seccion ?: 1 }))
}
