package catastro.brechas

import catastro.Registros
import catastro.valuacion.PREDIO_CATASTRAL
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext
import org.springframework.stereotype.Service
import wasichai.core.common.Actions
import wasichai.core.common.ForbiddenException
import wasichai.core.common.ValidationException
import wasichai.core.common.WasichaiException
import wasichai.core.data.RecordCriterion
import wasichai.core.data.RecordRequest
import wasichai.core.data.RecordService
import wasichai.core.identity.AuthenticatedUser
import wasichai.core.identity.CurrentUser
import wasichai.core.metadata.MetadataService
import wasichai.gis.Feature
import wasichai.gis.FeatureCollection
import java.math.BigDecimal
import java.time.Duration
import java.time.Instant
import java.time.temporal.ChronoUnit
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong

// the brechas dashboard of catastro-ui (GET/POST /api/catastro/brechas), read as the caller through core.
//
// a corte of Ica is some 25 000 fichas, and every endpoint but /cortes filters, counts or orders all of them: core's
// equality filters cannot say "categoria in (a, b)", "|delta| >= x" or "the decision's estado", and an estado lives
// in another object. so what each request needs is kept in memory, in two parts that change at different paces:
//
// - the Base of a corte: its fichas (one keyset pass by clave) and the lotes of their predios (batches of 200 codes,
//   4 at a time, read once: they give both con_geometria and /lotes' geometries). it changes only when the corte is
//   reloaded, so it is kept VIGENCIA_BASE from the end of its read, keyed by organization, the caller's roles (a field a role may not read never
//   reaches another role), the corte's id and its cargado_en (a reload writes a new one);
// - the decisions of a year: few rows, one keyset pass, kept VIGENCIA_DECISIONES and keyed by the organization's
//   generation, which a POST /decisiones moves on. so a decision shows at once here, never drops a Base, and one
//   taken through another instance shows within VIGENCIA_DECISIONES.
//
// both are read once per key however many requests ask at the same time (single-flight): the first starts the read,
// the others await it. each request joins them into its Vista (a pass over the fichas, no read)
@Service
class BrechasService(
    private val registros: Registros,
    private val records: RecordService,
    private val metadata: MetadataService,
    private val currentUser: CurrentUser
) {
    private val bases = ConcurrentHashMap<LlaveBase, EnVuelo<Base>>()
    private val decisiones = ConcurrentHashMap<LlaveDecisiones, EnVuelo<Map<String?, DecisionBrecha>>>()
    private val generaciones = ConcurrentHashMap<UUID, AtomicLong>()

    // how many Bases this instance read from core: the tests check that simultaneous requests share one
    internal val basesLeidas = AtomicInteger()

    // every corte whose load finished, the most recent first
    suspend fun cortes(): List<CorteResumen> {
        exigir(BRECHA_FICHA, Actions.READ)
        return cortesCompletos().map { CorteResumen(it.clave, it.fecha, it.anio, it.corrida, it.totalFichas, it.deltaImpuesto?.limpio(), it.cargadoEn) }
    }

    suspend fun panel(corte: String?): Panel = panel(vista(corte).vista)

    suspend fun fichas(
        corte: String?,
        filtro: Filtro,
        orden: Orden,
        page: Int,
        size: Int
    ): Pagina {
        val filas =
            vista(corte)
                .vista.filas
                .filter(filtro::admite)
                .sortedWith(orden.comparador)
        val desde = page.toLong() * size
        val contenido = if (desde >= filas.size) emptyList() else filas.subList(desde.toInt(), minOf(filas.size, (desde + size).toInt()))
        return Pagina(contenido, page, size, filas.size.toLong(), (filas.size + size - 1) / size)
    }

    // one ficha of the corte, its row as /fichas gives it, and its niveles. a ficha that is not of the corte is a 404;
    // the niveles are read only when the caller may read brecha_nivel_ficha (SRTM_LECTOR may not, on purpose), and a
    // refusal of core is no niveles either: what the niveles lack never takes the ficha with it
    suspend fun ficha(
        corte: String?,
        id: String
    ): DetalleFicha {
        val vista = vista(corte).vista
        val fila =
            vista.filas.firstOrNull { it.id == id }
                ?: throw BrechaNoEncontrada("No existe la ficha '$id' en el corte '${vista.corte.clave ?: vista.corte.id}'")
        return DetalleFicha(fila, nivelesDe(id))
    }

    private suspend fun nivelesDe(ficha: String): List<Nivel> {
        val usuario = currentUser.require()
        return try {
            val definicion = metadata.loadDefinition(usuario.organizationId, BRECHA_NIVEL_FICHA)
            if (!currentUser.hasPermission(usuario, Actions.READ, definicion.obj.id)) return emptyList()
            niveles(registros.todas(BRECHA_NIVEL_FICHA, NivelDeFicha::class.java, sort = "clave", filters = mapOf("ficha" to ficha)))
        } catch (e: WasichaiException) {
            // an organization without the object (a model older than #72) or a 403 of core: no niveles
            if (e.status.value() !in setOf(403, 404)) throw e
            emptyList()
        }
    }

    // the lotes of the fichas that match and have one, from the Base: one Feature per codigo_municipal (the ficha of
    // largest Δ), with `fichas`, how many fichas of the corte share that code
    suspend fun lotes(
        corte: String?,
        filtro: Filtro
    ): FeatureCollection {
        val (vista, base) = vista(corte)
        val porCodigo = vista.filas.groupingBy { it.codigoMunicipal }.eachCount()
        val filas = vista.filas.filter { it.codigoMunicipal != null && it.conGeometria && filtro.admite(it) }.distinctBy { it.codigoMunicipal }
        return FeatureCollection(
            filas.mapNotNull { fila ->
                val geometria = base.lotes[fila.codigoMunicipal] ?: return@mapNotNull null
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
                            "supera_5_uit" to fila.supera5Uit,
                            "fichas" to porCodigo.getValue(fila.codigoMunicipal)
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
        val vista = vista(corte).vista
        return (vista.corte.clave ?: vista.corte.id) to csv(vista.filas.filter(filtro::admite).sortedWith(orden.comparador))
    }

    // a batch of decisions of one year: each codigo_municipal gets its decision_brecha created or updated, by clave
    // codigo|anio, DECISIONES_A_LA_VEZ at a time. responsable, decidido_en and corte_origen (the most recent corte of that year) are
    // the server's. a code that is no ficha, or one core refuses, is reported in errores and the others are still
    // written; a 403 of core stops the batch (what was written stays written). the writes carry EscrituraDeBrechas:
    // DecisionesSoloPorLaApi refuses any other write of decision_brecha
    suspend fun decidir(pedido: PedidoDecision): ResultadoDecisiones {
        val usuario = exigir(DECISION_BRECHA, Actions.UPDATE)
        exigir(BRECHA_FICHA, Actions.READ, usuario)
        val cortes = cortesCompletos()
        if (cortes.none { it.anio == pedido.anio }) {
            throw ValidationException("No hay un corte de brecha de ${pedido.anio}", "anio", "no hay un corte cargado de ese año")
        }
        val codigos = pedido.codigos
        val claves = codigos.associateWith { "$it|${pedido.anio}" }
        val existentes =
            registros
                .conCampoEn(DECISION_BRECHA, DecisionBrecha::class.java, "clave", claves.values)
                .associateBy { it.clave }
        val fichas =
            registros
                .conCampoEn(PREDIO_CATASTRAL, CodigoDePredio::class.java, CODIGO_MUNICIPAL, codigos, concurrencia = 2)
                .mapNotNull { it.codigoMunicipal }
                .toSet()
        // a role with UPDATE but not CREATE is refused before anything is written, not half way
        if (codigos.any { it in fichas && claves.getValue(it) !in existentes }) exigir(DECISION_BRECHA, Actions.CREATE, usuario)
        val atributos =
            buildMap<String, Any?> {
                put("estado", pedido.estado)
                put("motivo_descarte", if (pedido.estado == DESCARTADO) pedido.motivoDescarte else null)
                if (pedido.nota != null) put("nota", pedido.nota.valor)
                put("responsable", usuario.email.takeIf { '@' in it })
                put("decidido_en", Instant.now().truncatedTo(ChronoUnit.SECONDS).toString())
                // the most recent corte of the decision's year (there is one: checked above)
                put("corte_origen", cortes.first { it.anio == pedido.anio }.clave)
            }
        val creadas = AtomicInteger()
        val actualizadas = AtomicInteger()
        val errores = ConcurrentLinkedQueue<ErrorDeDecision>()
        val limite = Semaphore(DECISIONES_A_LA_VEZ)
        try {
            withContext(EscrituraDeBrechas()) {
                codigos
                    .map { codigo ->
                        async {
                            if (codigo !in fichas) {
                                errores += ErrorDeDecision(codigo, "no hay una ficha con ese código municipal")
                                return@async
                            }
                            val clave = claves.getValue(codigo)
                            val existente = existentes[clave]
                            limite.withPermit {
                                try {
                                    if (existente == null) {
                                        val nueva = atributos + mapOf("clave" to clave, "codigo_municipal" to codigo, "anio" to pedido.anio)
                                        records.create(DECISION_BRECHA, RecordRequest(nueva), RAZON)
                                        creadas.incrementAndGet()
                                    } else {
                                        records.patch(DECISION_BRECHA, UUID.fromString(existente.id), RecordRequest(atributos), RAZON)
                                        actualizadas.incrementAndGet()
                                    }
                                } catch (e: WasichaiException) {
                                    if (e.status.value() == 403) throw e
                                    errores += ErrorDeDecision(codigo, e.message ?: "rechazado")
                                }
                            }
                        }
                    }.awaitAll()
            }
        } finally {
            // the decisions of every year of the organization are read anew; the Bases stay
            generaciones.computeIfAbsent(usuario.organizationId) { AtomicLong() }.incrementAndGet()
            decisiones.keys.removeIf { it.organizacion == usuario.organizationId }
        }
        val orden = codigos.withIndex().associate { (i, c) -> c to i }
        return ResultadoDecisiones(actualizadas.get(), creadas.get(), errores.sortedBy { orden.getValue(it.codigo) })
    }

    // the corte `clave` names, or the most recent one, joined with the decisions of its year
    private suspend fun vista(clave: String?): VistaConBase {
        val usuario = exigir(BRECHA_FICHA, Actions.READ)
        val cortes = cortesCompletos()
        val corte =
            if (clave == null) {
                cortes.firstOrNull() ?: throw BrechaNoEncontrada(SIN_CORTES)
            } else {
                cortes.firstOrNull { it.clave == clave } ?: throw BrechaNoEncontrada("No existe el corte de brecha '$clave'")
            }
        val roles = usuario.roles.sorted()
        val (base, delAnio) =
            coroutineScope {
                val base = async { unaVez(bases, LlaveBase(usuario.organizationId, roles, corte.id, corte.cargadoEn), VIGENCIA_BASE) { leerBase(corte) } }
                val delAnio =
                    async {
                        val anio = corte.anio ?: return@async emptyMap()
                        val generacion = generaciones.computeIfAbsent(usuario.organizationId) { AtomicLong() }.get()
                        unaVez(decisiones, LlaveDecisiones(usuario.organizationId, roles, anio, generacion), VIGENCIA_DECISIONES) { leerDecisiones(anio) }
                    }
                base.await() to delAnio.await()
            }
        val filas = base.fichas.map { fila(it, it.codigoMunicipal?.let(delAnio::get), it.codigoMunicipal in base.lotes) }
        return VistaConBase(Vista(corte, filas), base)
    }

    private suspend fun leerBase(corte: CorteBrecha): Base {
        basesLeidas.incrementAndGet()
        val fichas = registros.todas(BRECHA_FICHA, BrechaFicha::class.java, sort = "clave", filters = mapOf("corte" to corte.id))
        val codigos = fichas.mapNotNull { it.codigoMunicipal }
        val lotes =
            if (codigos.isEmpty()) {
                emptyMap()
            } else {
                registros
                    .conCampoEn(
                        PREDIO_CATASTRAL,
                        LoteDePredio::class.java,
                        CODIGO_MUNICIPAL,
                        codigos,
                        criteria = listOf(CON_LOTE),
                        concurrencia = LOTES_A_LA_VEZ
                    ).mapNotNull { p -> p.codigoMunicipal?.let { c -> p.loteGeom?.let { c to it } } }
                    .toMap()
            }
        // by Δ impuesto, /fichas' default: /lotes keeps the largest Δ of a codigo_municipal that two fichas share
        val ordenadas = fichas.sortedWith(compareBy<BrechaFicha, BigDecimal?>(nullsLast(reverseOrder())) { it.deltaImpuesto }.thenBy { it.id })
        return Base(ordenadas, lotes)
    }

    private suspend fun leerDecisiones(anio: Int): Map<String?, DecisionBrecha> =
        registros
            .todas(DECISION_BRECHA, DecisionBrecha::class.java, sort = "clave", filters = mapOf("anio" to anio.toString()))
            .associateBy { it.codigoMunicipal }

    // `leer` once per key while it lasts: concurrent callers await the same read, which runs in the first caller's
    // context (as that caller: the key carries the roles) but outlives it, so a client that goes away does not fail
    // the others. a read that failed is forgotten. `vigencia` counts from when the read finished, not from when it
    // started: a cold read of a big corte takes seconds of it otherwise
    private suspend fun <K : Any, T> unaVez(
        mapa: ConcurrentHashMap<K, EnVuelo<T>>,
        llave: K,
        vigencia: Duration,
        leer: suspend () -> T
    ): T {
        val ahora = Instant.now()
        mapa.entries.removeIf { !it.value.hasta.isAfter(ahora) }
        val contexto = currentCoroutineContext().minusKey(Job)
        val enVuelo =
            mapa.compute(llave) { _, actual ->
                actual?.takeIf { it.hasta.isAfter(ahora) }
                    ?: EnVuelo(CoroutineScope(contexto + SupervisorJob()).async(start = CoroutineStart.LAZY) { leer() }).also { nuevo ->
                        nuevo.valor.invokeOnCompletion { nuevo.hasta = Instant.now().plus(vigencia) }
                    }
            }!!
        return try {
            enVuelo.valor.await()
        } catch (e: Exception) {
            if (enVuelo.valor.isCompleted) mapa.remove(llave, enVuelo)
            throw e
        }
    }

    // by fecha, the most recent first; two cortes of a day by clave. a corte without cargado_en is one
    // importar_corte_brecha.py is still loading (or left half done): never shown
    private suspend fun cortesCompletos(): List<CorteBrecha> = completos(registros.todas(CORTE_BRECHA, CorteBrecha::class.java, sort = "clave"))

    // the caller, once it holds `accion` on `objeto` (403 otherwise)
    private suspend fun exigir(
        objeto: String,
        accion: String,
        usuario: AuthenticatedUser? = null
    ): AuthenticatedUser {
        val quien = usuario ?: currentUser.require()
        val definicion = metadata.loadDefinition(quien.organizationId, objeto)
        if (!currentUser.hasPermission(quien, accion, definicion.obj.id)) throw ForbiddenException("Missing permission $accion on $objeto")
        return quien
    }

    private data class LlaveBase(
        val organizacion: UUID,
        val roles: List<String>,
        val corte: String,
        val cargadoEn: String?
    )

    private data class LlaveDecisiones(
        val organizacion: UUID,
        val roles: List<String>,
        val anio: Int,
        val generacion: Long
    )

    // until its read finishes it never expires; then it lasts its vigencia
    private class EnVuelo<T>(
        val valor: Deferred<T>
    ) {
        @Volatile var hasta: Instant = Instant.MAX
    }

    // a corte's fichas (by Δ impuesto) and the lote of each codigo_municipal that has one, GeoJSON in 4326
    class Base(
        val fichas: List<BrechaFicha>,
        val lotes: Map<String, Map<String, Any?>>
    )

    data class VistaConBase(
        val vista: Vista,
        val base: Base
    )

    companion object {
        val VIGENCIA_BASE: Duration = Duration.ofMinutes(5)
        val VIGENCIA_DECISIONES: Duration = Duration.ofSeconds(15)
        const val LOTES_A_LA_VEZ = 4
        const val DECISIONES_A_LA_VEZ = 8
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
