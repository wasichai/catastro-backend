package catastro.brechas

import catastro.Registros
import catastro.valuacion.PREDIO_CATASTRAL
import org.springframework.stereotype.Service
import wasichai.core.common.Actions
import wasichai.core.common.WasichaiException
import wasichai.core.data.RecordCriterion
import wasichai.core.data.RecordRequest
import wasichai.core.data.RecordService
import wasichai.core.identity.AuthenticatedUser
import wasichai.core.identity.CurrentUser
import wasichai.core.metadata.MetadataService
import wasichai.gis.Feature
import wasichai.gis.FeatureCollection
import java.time.Duration
import java.time.Instant
import java.time.temporal.ChronoUnit
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

// the brechas dashboard of catastro-ui (GET/POST /api/catastro/brechas), read as the caller through core.
//
// a corte of Ica is some 25 000 fichas, and every endpoint but /cortes filters, counts or orders all of them: core's
// equality filters cannot say "categoria in (a, b)", "|delta| >= x" or "the decision's estado", and an estado lives
// in another object (decision_brecha, by codigo_municipal and year). so a corte is read once, whole: its fichas in one
// keyset pass (Registros.todas, by clave), the decisions of its year in another, and which of its fichas' predios
// have a lote in batches of 200 codes (Registros.conCampoEn), joined into a Vista that /panel, /fichas, /lotes and
// /fichas.csv filter in memory. the Vista is kept for VIGENCIA, keyed by organization, the caller's roles (a field
// a role may not read never reaches another role) and the corte's id and cargado_en (a reloaded corte is read anew);
// a decision drops the organization's vistas, so its own estado shows at once. a decision taken through another
// instance shows here within VIGENCIA
@Service
class BrechasService(
    private val registros: Registros,
    private val records: RecordService,
    private val metadata: MetadataService,
    private val currentUser: CurrentUser
) {
    private val vistas = ConcurrentHashMap<Llave, Guardada>()

    // every corte, the most recent first
    suspend fun cortes(): List<CorteResumen> {
        exigir(BRECHA_FICHA, Actions.READ)
        return todosLosCortes().map { CorteResumen(it.clave, it.fecha, it.anio, it.corrida, it.totalFichas, it.deltaImpuesto?.limpio(), it.cargadoEn) }
    }

    suspend fun panel(corte: String?): Panel = panel(vista(corte))

    suspend fun fichas(
        corte: String?,
        filtro: Filtro,
        orden: Orden,
        page: Int,
        size: Int
    ): Pagina {
        val filas = vista(corte).filas.filter(filtro::admite).sortedWith(orden.comparador)
        val desde = page.toLong() * size
        val contenido = if (desde >= filas.size) emptyList() else filas.subList(desde.toInt(), minOf(filas.size, (desde + size).toInt()))
        return Pagina(contenido, page, size, filas.size.toLong(), (filas.size + size - 1) / size)
    }

    // the lotes of the fichas that match and have one, read in batches of 200 codes; one Feature per codigo_municipal
    suspend fun lotes(
        corte: String?,
        filtro: Filtro
    ): FeatureCollection {
        val filas =
            vista(corte)
                .filas
                .filter { it.codigoMunicipal != null && it.conGeometria && filtro.admite(it) }
                .distinctBy { it.codigoMunicipal }
        val lotes =
            registros
                .conCampoEn(PREDIO_CATASTRAL, LoteDePredio::class.java, CODIGO_MUNICIPAL, filas.map { it.codigoMunicipal!! })
                .associateBy { it.codigoMunicipal }
        return FeatureCollection(
            filas.mapNotNull { fila ->
                val geometria = lotes[fila.codigoMunicipal]?.loteGeom ?: return@mapNotNull null
                Feature(
                    id = fila.codigoMunicipal!!,
                    geometry = geometria,
                    properties =
                        linkedMapOf(
                            "codigo_municipal" to fila.codigoMunicipal,
                            "codigo_catastro" to fila.codigoCatastro,
                            "categoria" to fila.categoria,
                            "confianza" to fila.confianza,
                            "delta_impuesto" to fila.deltaImpuesto,
                            "estado" to fila.estado,
                            "supera_5_uit" to fila.supera5Uit
                        )
                )
            }
        )
    }

    suspend fun csv(
        corte: String?,
        filtro: Filtro,
        orden: Orden
    ): Pair<String, ByteArray> {
        val vista = vista(corte)
        return (vista.corte.clave ?: vista.corte.id) to csv(vista.filas.filter(filtro::admite).sortedWith(orden.comparador))
    }

    // a batch of decisions of one year: each codigo_municipal gets its decision_brecha created or updated, by clave
    // codigo|anio. responsable, decidido_en and corte_origen (the most recent corte) are the server's. a code that is
    // no ficha, or one core refuses, is reported in errores and the others are still written
    suspend fun decidir(pedido: PedidoDecision): ResultadoDecisiones {
        val usuario = exigir(DECISION_BRECHA, Actions.UPDATE)
        exigir(BRECHA_FICHA, Actions.READ, usuario)
        val codigos = pedido.codigos
        val claves = codigos.associateWith { "$it|${pedido.anio}" }
        val existentes =
            registros
                .conCampoEn(DECISION_BRECHA, DecisionBrecha::class.java, "clave", claves.values)
                .associateBy { it.clave }
        val fichas = registros.conCampoEn(PREDIO_CATASTRAL, CodigoDePredio::class.java, CODIGO_MUNICIPAL, codigos).mapNotNull { it.codigoMunicipal }.toSet()
        val origen = todosLosCortes().firstOrNull()?.clave
        val ahora = Instant.now().truncatedTo(ChronoUnit.SECONDS).toString()
        val atributos =
            buildMap<String, Any?> {
                put("estado", pedido.estado)
                put("motivo_descarte", if (pedido.estado == DESCARTADO) pedido.motivoDescarte else null)
                if (pedido.nota != null) put("nota", pedido.nota.valor)
                put("responsable", usuario.email.takeIf { '@' in it })
                put("decidido_en", ahora)
                put("corte_origen", origen)
            }
        var creadas = 0
        var actualizadas = 0
        val errores = mutableListOf<ErrorDeDecision>()
        try {
            for (codigo in codigos) {
                if (codigo !in fichas) {
                    errores += ErrorDeDecision(codigo, "no hay una ficha con ese código municipal")
                    continue
                }
                val clave = claves.getValue(codigo)
                val existente = existentes[clave]
                try {
                    if (existente == null) {
                        val nueva = atributos + mapOf("clave" to clave, "codigo_municipal" to codigo, "anio" to pedido.anio)
                        records.create(DECISION_BRECHA, RecordRequest(nueva), RAZON)
                        creadas++
                    } else {
                        records.patch(DECISION_BRECHA, UUID.fromString(existente.id), RecordRequest(atributos), RAZON)
                        actualizadas++
                    }
                } catch (e: WasichaiException) {
                    // a 403 stops the batch: the caller may not write at all
                    if (e.status.value() == 403) throw e
                    errores += ErrorDeDecision(codigo, e.message ?: "rechazado")
                }
            }
        } finally {
            olvidar(usuario.organizationId)
        }
        return ResultadoDecisiones(actualizadas, creadas, errores)
    }

    // the corte `clave` names, or the most recent one; read whole, or from the vistas while VIGENCIA lasts
    private suspend fun vista(clave: String?): Vista {
        val usuario = exigir(BRECHA_FICHA, Actions.READ)
        val cortes = todosLosCortes()
        val corte =
            if (clave == null) {
                cortes.firstOrNull() ?: throw BrechaNoEncontrada(SIN_CORTES)
            } else {
                cortes.firstOrNull { it.clave == clave } ?: throw BrechaNoEncontrada("No existe el corte de brecha '$clave'")
            }
        val llave = Llave(usuario.organizationId, usuario.roles.sorted(), corte.id, corte.cargadoEn)
        val ahora = Instant.now()
        vistas[llave]?.takeIf { it.hasta.isAfter(ahora) }?.let { return it.vista }
        val vista = leer(corte)
        vistas.entries.removeIf { !it.value.hasta.isAfter(ahora) }
        vistas[llave] = Guardada(vista, ahora.plus(VIGENCIA))
        return vista
    }

    private suspend fun leer(corte: CorteBrecha): Vista {
        val fichas = registros.todas(BRECHA_FICHA, BrechaFicha::class.java, sort = "clave", filters = mapOf("corte" to corte.id))
        val decisiones =
            corte.anio
                ?.let { anio -> registros.todas(DECISION_BRECHA, DecisionBrecha::class.java, sort = "clave", filters = mapOf("anio" to anio.toString())) }
                .orEmpty()
                .associateBy { it.codigoMunicipal }
        val codigos = fichas.mapNotNull { it.codigoMunicipal }
        val conLote =
            if (codigos.isEmpty()) {
                emptySet()
            } else {
                registros
                    .conCampoEn(PREDIO_CATASTRAL, CodigoDePredio::class.java, CODIGO_MUNICIPAL, codigos, criteria = listOf(CON_LOTE))
                    .mapNotNull { it.codigoMunicipal }
                    .toSet()
            }
        // by Δ impuesto, /fichas' default: /lotes keeps the largest Δ of a codigo_municipal that two fichas share
        val filas =
            fichas
                .map { fila(it, it.codigoMunicipal?.let(decisiones::get), it.codigoMunicipal in conLote) }
                .sortedWith(Orden.DELTA_DESC.comparador)
        return Vista(corte, filas)
    }

    // by fecha, the most recent first; two cortes of a day by clave
    private suspend fun todosLosCortes(): List<CorteBrecha> =
        registros
            .todas(CORTE_BRECHA, CorteBrecha::class.java, sort = "clave")
            .sortedWith(compareByDescending<CorteBrecha, String?>(nullsFirst()) { it.fecha }.thenByDescending { it.clave })

    // the caller, once it holds `accion` on `objeto` (core's 403 otherwise)
    private suspend fun exigir(
        objeto: String,
        accion: String,
        usuario: AuthenticatedUser? = null
    ): AuthenticatedUser {
        val quien = usuario ?: currentUser.require()
        val definicion = metadata.loadDefinition(quien.organizationId, objeto)
        currentUser.requirePermission(quien, accion, definicion.obj.id)
        return quien
    }

    private fun olvidar(organizacion: UUID) {
        vistas.keys.removeIf { it.organizacion == organizacion }
    }

    private data class Llave(
        val organizacion: UUID,
        val roles: List<String>,
        val corte: String,
        val cargadoEn: String?
    )

    private class Guardada(
        val vista: Vista,
        val hasta: Instant
    )

    companion object {
        val VIGENCIA: Duration = Duration.ofMinutes(2)
        const val SIN_CORTES = "No hay cortes de brecha cargados"
        const val CODIGO_MUNICIPAL = "codigo_municipal"
        const val RAZON = "Dashboard de brechas"

        // a predio_catastral with its lote
        private val CON_LOTE =
            RecordCriterion { definition, _ -> "\"${definition.fields.first { it.name == "lote_geom" }.columnName}\" IS NOT NULL" }
    }
}

// POST /decisiones, read and checked by the controller. nota: absent leaves the stored one, present (null too) sets it
data class PedidoDecision(
    val codigos: List<String>,
    val anio: Int,
    val estado: String,
    val nota: Nota?,
    val motivoDescarte: String?
) {
    data class Nota(
        val valor: String?
    )
}

// wasichai's PageResponse shape: {content, page, size, totalElements, totalPages}
data class Pagina(
    val content: List<FilaFicha>,
    val page: Int,
    val size: Int,
    val totalElements: Long,
    val totalPages: Int
)

// a 404 the controller answers with its message (contract: {message})
class BrechaNoEncontrada(
    mensaje: String
) : RuntimeException(mensaje)
