package catastro.copias

import catastro.Registros
import catastro.brechas.BRECHA_FICHA
import catastro.brechas.CORTE_BRECHA
import catastro.brechas.CorteBrecha
import catastro.brechas.DECISION_BRECHA
import catastro.brechas.DecisionBrecha
import catastro.brechas.PENDIENTE
import catastro.brechas.completos
import catastro.valuacion.ARANCEL
import catastro.valuacion.Arancel
import catastro.vias.TRAMO_VIA
import catastro.vias.anioEnCurso
import jakarta.annotation.PostConstruct
import jakarta.annotation.PreDestroy
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineName
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.cancel
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.supervisorScope
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withTimeout
import org.slf4j.LoggerFactory
import org.springframework.beans.factory.annotation.Value
import org.springframework.http.HttpStatus
import org.springframework.scheduling.annotation.Scheduled
import org.springframework.stereotype.Component
import org.springframework.web.server.ResponseStatusException
import tools.jackson.databind.PropertyNamingStrategies
import tools.jackson.databind.annotation.JsonNaming
import wasichai.core.common.NotFoundException
import wasichai.core.common.WasichaiException
import wasichai.core.data.RecordCriterion
import wasichai.core.data.RecordRequest
import wasichai.core.data.RecordService
import wasichai.core.metadata.MetadataService
import wasichai.core.metadata.ObjectDefinition
import wasichai.core.platform.ClusterLock
import wasichai.core.platform.SqlIdentifier
import java.math.BigDecimal
import java.time.Duration
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong

// the copies catastro keeps of another object's value, so that a map view and a WMS layer of wasichai-gis (which colour
// an object only by its own fields, ADR-072 of wasichai) can colour by them:
// - tramo_via.valor_m2 and anio_valor: the valor_m2 of the arancel of its id_aranc in the current year (America/Lima),
//   both empty without one;
// - brecha_ficha.estado on the fichas of each organization's most recent corte: the estado of its decision_brecha of
//   the corte's year, PENDIENTE without one.
//
// background work, as wasichai supports it (ADR-039): every write goes through RecordService as the platform
// (asPlatform, audit source copia:mapa), so it is audited, moves the record's version (ADR-051) and reaches the
// listeners, and no caller needs UPDATE on tramo_via or brecha_ficha. a run reads only the rows whose copy differs
// (RecordCriterion), so a run with nothing to do costs a few reads per organization. it runs
// - every `catastro.copias.periodo` (5 minutes by default) over every organization, under a cluster lock: this is what
//   heals any missed copy and turns the year over on 1 January;
// - `catastro.copias.espera` (2 s) after a nudge, over the organizations nudged: AvisosDeCopias nudges on the writes
//   that change a copy (an arancel of the year, a decision...), POST /api/catastro/vias/valores asks for a run and
//   awaits it. a nudge only queues the organization; the run is collected in this component's own scope, never in the
//   request's, so a request never becomes the platform.
// GET /api/catastro/cambios never lists these writes: it follows predios, construcciones, obras and titulares only
@Component
class CopiasDelMapa(
    private val records: RecordService,
    private val registros: Registros,
    private val metadata: MetadataService,
    private val clusterLock: ClusterLock,
    @param:Value("\${catastro.copias.espera:PT2S}") private val espera: Duration,
    @param:Value("\${catastro.copias.periodo:PT5M}") private val periodo: Duration,
    @param:Value("\${catastro.copias.limite:PT10M}") private val limite: Duration
) {
    private val log = LoggerFactory.getLogger(javaClass)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default + CoroutineName("copias-del-mapa"))
    private val senal = Channel<Unit>(Channel.CONFLATED)
    private val pendientes: MutableSet<UUID> = ConcurrentHashMap.newKeySet()
    private val esperando = ConcurrentLinkedQueue<Espera>()

    // each waiter's number: a run answers only those registered before it read anything (N5)
    private val turnos = AtomicLong()

    // one run at a time in this instance; the cluster lock keeps the other replicas out
    private val enCurso = Mutex()

    @PostConstruct
    fun iniciar() {
        scope.launch {
            var intentos = 0
            try {
                for (aviso in senal) {
                    // a trailing debounce: a burst of writes (srtm's sync, a batch in a transaction that commits later)
                    // waits until `espera` passes without a new nudge, up to `periodo`
                    val hasta = System.nanoTime() + periodo.toNanos()
                    do {
                        delay(espera.toMillis())
                    } while (senal.tryReceive().isSuccess && System.nanoTime() < hasta)
                    intentos =
                        try {
                            if (atenderPendientes()) 0 else intentos + 1
                        } catch (e: CancellationException) {
                            throw e
                        } catch (e: Exception) {
                            log.warn("copias del mapa: {}", e.message, e)
                            intentos + 1
                        }
                    if (intentos > 0) {
                        // the lock was held by another replica, or the run could not start: back off, then retry
                        // (each tryLock is a new connection, ADR-039)
                        scope.launch {
                            delay(minOf(espera.toMillis() * intentos, periodo.toMillis()))
                            senal.trySend(Unit)
                        }
                    }
                }
            } finally {
                // the scope is cancelled (shutdown) or the loop died: nobody is left to answer the waiters
                esperando.forEach { it.hecho.completeExceptionally(IllegalStateException("las copias del mapa se detuvieron")) }
                esperando.clear()
            }
        }
    }

    @PreDestroy
    fun detener() {
        scope.cancel()
    }

    // queues the organization for a run soon. never suspends, never throws: a listener calls it
    fun avisar(organizacion: UUID) {
        pendientes += organizacion
        senal.trySend(Unit)
    }

    // a run for the organization, awaited: what it wrote. the run itself is the job's, not the caller's. after
    // `catastro.copias.limite` (10 minutes) it gives up with a 503; the run, if it comes, still writes
    suspend fun ahora(organizacion: UUID): CopiasHechas {
        val espera = Espera(organizacion, turnos.incrementAndGet(), CompletableDeferred())
        // the waiter before the organization: a run that takes the organization always finds its waiter
        esperando += espera
        avisar(organizacion)
        return try {
            withTimeout(limite.toMillis()) { espera.hecho.await() }
        } catch (e: TimeoutCancellationException) {
            esperando.remove(espera)
            throw ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Las copias del mapa no corrieron en $limite; correrán solas más tarde", e)
        }
    }

    // every organization, every `periodo` from the start. a failure of one organization is logged by
    // forEachOrganization and the others go on; a failed record is retried on the next tick
    @Scheduled(fixedDelayString = "\${catastro.copias.periodo:PT5M}", initialDelayString = "\${catastro.copias.periodo:PT5M}")
    suspend fun periodica() {
        enCurso.withLock {
            val lease = clusterLock.tryLock(LLAVE) ?: return
            lease.use {
                records.forEachOrganization(TRAMO_VIA, FUENTE) { tramos(it) }
                records.forEachOrganization(BRECHA_FICHA, FUENTE) { fichas(it) }
            }
        }
    }

    // the nudged organizations: false when it could not take the lock (another replica runs)
    private suspend fun atenderPendientes(): Boolean {
        enCurso.withLock {
            val lease = clusterLock.tryLock(LLAVE) ?: return false
            lease.use {
                val tope = turnos.get()
                val organizaciones = pendientes.toList().also { pendientes.removeAll(it.toSet()) }
                for (organizacion in organizaciones) {
                    val resultado =
                        try {
                            Result.success(records.asPlatform(organizacion, FUENTE) { copiar(organizacion) })
                        } catch (e: CancellationException) {
                            throw e
                        } catch (e: Exception) {
                            log.warn("copias del mapa de {}: {}", organizacion, e.message, e)
                            Result.failure(e)
                        }
                    esperando.filter { it.organizacion == organizacion }.forEach { espera ->
                        if (espera.turno > tope) {
                            // registered after this run had begun: it gets the next one
                            avisar(organizacion)
                        } else {
                            esperando.remove(espera)
                            resultado.fold({ espera.hecho.complete(it) }, { espera.hecho.completeExceptionally(it) })
                        }
                    }
                }
            }
        }
        return true
    }

    // the two copies of one organization, each on its own: a failure of the tramos still copies the fichas
    private suspend fun copiar(organizacion: UUID): CopiasHechas {
        val tramos = parte(organizacion, TRAMO_VIA) { tramos(organizacion) }
        val fichas = parte(organizacion, BRECHA_FICHA) { fichas(organizacion) }
        return CopiasHechas(anioEnCurso(), tramos.escritas, fichas.escritas, tramos.fallidas + fichas.fallidas)
    }

    private suspend fun parte(
        organizacion: UUID,
        objeto: String,
        copia: suspend () -> Escritura
    ): Escritura =
        try {
            copia()
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            log.warn("copias del mapa de {}, {}: {}", organizacion, objeto, e.message, e)
            Escritura(0, 1)
        }

    // the tramos whose copy differs from the arancel of the current year, patched
    private suspend fun tramos(organizacion: UUID): Escritura {
        if (definicion(organizacion, TRAMO_VIA, VALOR_M2, ANIO_VALOR, ID_ARANC) == null) return Escritura(0, 0)
        if (definicion(organizacion, ARANCEL, VALOR_M2, ANIO, ID_ARANC) == null) return Escritura(0, 0)
        val anio = anioEnCurso()
        val valores =
            registros
                .todas(ARANCEL, Arancel::class.java, sort = "clave", filters = mapOf(ANIO to anio.toString()))
                .mapNotNull { a -> a.idAranc?.let { id -> a.valorM2?.let { id to it } } }
                .toMap()
        val distintos =
            registros.todas(
                TRAMO_VIA,
                CopiaDeTramo::class.java,
                sort = "clave",
                filters = emptyMap(),
                criteria = listOf(tramoDistinto(valores, anio))
            )
        return escribir(TRAMO_VIA, distintos.mapNotNull { t -> copiaDeTramo(t, valores, anio)?.let { t.id to it } })
    }

    // the fichas of the most recent corte whose estado differs from their decision, patched
    private suspend fun fichas(organizacion: UUID): Escritura {
        if (definicion(organizacion, BRECHA_FICHA, ESTADO, CODIGO_MUNICIPAL) == null) return Escritura(0, 0)
        val corte = completos(registros.todas(CORTE_BRECHA, CorteBrecha::class.java, sort = "clave")).firstOrNull() ?: return Escritura(0, 0)
        val anio = corte.anio ?: return Escritura(0, 0)
        val decididos =
            registros
                .todas(DECISION_BRECHA, DecisionBrecha::class.java, sort = "clave", filters = mapOf(ANIO to anio.toString()))
                .mapNotNull { d -> d.codigoMunicipal?.let { c -> d.estado?.let { c to it } } }
                .toMap()
        val distintas =
            registros.todas(
                BRECHA_FICHA,
                CopiaDeFicha::class.java,
                sort = "clave",
                filters = mapOf("corte" to corte.id),
                criteria = listOf(fichaDistinta(decididos))
            )
        return escribir(BRECHA_FICHA, distintas.mapNotNull { f -> copiaDeFicha(f, decididos)?.let { f.id to it } })
    }

    // each patch on its own: one that fails (a record deleted meanwhile, a rule it breaks) is logged with the object,
    // the id and the error, never the values, and counted; the others are still written, and the next run retries it
    private suspend fun escribir(
        objeto: String,
        cambios: List<Pair<String, Map<String, Any?>>>
    ): Escritura {
        val limite = Semaphore(ESCRITURAS_A_LA_VEZ)
        val fallidas = AtomicInteger()
        supervisorScope {
            cambios
                .map { (id, atributos) ->
                    async {
                        limite.withPermit {
                            try {
                                records.patch(objeto, UUID.fromString(id), RecordRequest(atributos), RAZON)
                            } catch (e: CancellationException) {
                                throw e
                            } catch (e: Exception) {
                                fallidas.incrementAndGet()
                                log.warn("copias del mapa: no se escribió {} {}: {}", objeto, id, causa(e))
                            }
                        }
                    }
                }.awaitAll()
        }
        return Escritura(cambios.size - fallidas.get(), fallidas.get())
    }

    // the definition when the organization has the object and every field (a model not applied yet copies nothing)
    private suspend fun definicion(
        organizacion: UUID,
        objeto: String,
        vararg campos: String
    ): ObjectDefinition? {
        val definicion =
            try {
                metadata.loadDefinition(organizacion, objeto)
            } catch (_: NotFoundException) {
                return null
            }
        return definicion.takeIf { d -> campos.all { c -> d.fields.any { it.name == c } } }
    }

    // a waiter of ahora: its organization, its turn, its answer
    private class Espera(
        val organizacion: UUID,
        val turno: Long,
        val hecho: CompletableDeferred<CopiasHechas>
    )

    // what a copy wrote, and how many records it could not
    private data class Escritura(
        val escritas: Int,
        val fallidas: Int
    )

    companion object {
        const val LLAVE = "catastro.copias"
        const val FUENTE = "copia:mapa"
        const val RAZON = "Copia para el mapa"
        const val ESCRITURAS_A_LA_VEZ = 4
        private const val VALOR_M2 = "valor_m2"
        private const val ANIO_VALOR = "anio_valor"
        private const val ID_ARANC = "id_aranc"
        private const val ANIO = "anio"
        private const val ESTADO = "estado"
        private const val CODIGO_MUNICIPAL = "codigo_municipal"

        // the error of a refused patch as the log shows it: its kind and status, never its message (it may echo a value)
        private fun causa(e: Exception): String = if (e is WasichaiException) "${e.javaClass.simpleName} ${e.status.value()}" else e.javaClass.simpleName

        // the column of a field in the definition core hands the criterion
        private fun ObjectDefinition.columna(campo: String) = SqlIdentifier.quote(fields.first { it.name == campo }.columnName)

        // a tramo whose valor_m2 or anio_valor is not what `valores` (id_aranc -> valor_m2 of `anio`) says
        fun tramoDistinto(
            valores: Map<String, BigDecimal>,
            anio: Int
        ) = RecordCriterion { definicion, bind ->
            val ids = valores.keys.toTypedArray()
            val textos = valores.values.map { it.toPlainString() }.toTypedArray()
            val id = definicion.columna(ID_ARANC)
            val valor = definicion.columna(VALOR_M2)
            val anioValor = definicion.columna(ANIO_VALOR)
            "($valor IS DISTINCT FROM (SELECT CAST(v.valor AS numeric) FROM unnest(CAST(${bind(ids)} AS text[]), " +
                "CAST(${bind(textos)} AS text[])) AS v(id, valor) WHERE v.id = $id) " +
                "OR $anioValor IS DISTINCT FROM (SELECT CAST(${bind(anio)} AS bigint) FROM unnest(CAST(${bind(ids.copyOf())} AS text[])) " +
                "AS i(id) WHERE i.id = $id))"
        }

        // a ficha whose estado is not its decision's (`decididos`: codigo_municipal -> estado), PENDIENTE without one:
        // the comparison is the database's, so a run reads only the fichas it writes
        fun fichaDistinta(decididos: Map<String, String>) =
            RecordCriterion { definicion, bind ->
                val codigos = decididos.keys.toTypedArray()
                val estados = codigos.map { decididos.getValue(it) }.toTypedArray()
                "(${definicion.columna(ESTADO)} IS DISTINCT FROM COALESCE((SELECT d.estado FROM unnest(CAST(${bind(codigos)} AS text[]), " +
                    "CAST(${bind(estados)} AS text[])) AS d(codigo, estado) WHERE d.codigo = ${definicion.columna(CODIGO_MUNICIPAL)}), " +
                    "CAST(${bind(PENDIENTE)} AS text)))"
            }
    }
}

// what a run wrote for one organization: tramos and fichas patched, and the records it could not write (retried on
// the next run)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy::class)
data class CopiasHechas(
    val anio: Int,
    val tramos: Int,
    val fichas: Int,
    val fallidas: Int
)

@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy::class)
data class CopiaDeTramo(
    val id: String,
    val idAranc: String? = null,
    val valorM2: BigDecimal? = null,
    val anioValor: Int? = null
)

@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy::class)
data class CopiaDeFicha(
    val id: String,
    val codigoMunicipal: String? = null,
    val estado: String? = null
)

// the attributes that make the tramo's copy right, or null when it already is
fun copiaDeTramo(
    tramo: CopiaDeTramo,
    valores: Map<String, BigDecimal>,
    anio: Int
): Map<String, Any?>? {
    val valor = tramo.idAranc?.let { valores[it] }
    val anioValor = valor?.let { anio }
    val igual =
        (valor == null && tramo.valorM2 == null || valor != null && tramo.valorM2 != null && valor.compareTo(tramo.valorM2) == 0) &&
            anioValor == tramo.anioValor
    return if (igual) null else mapOf("valor_m2" to valor, "anio_valor" to anioValor)
}

// the estado that makes the ficha's copy right, or null when it already is
fun copiaDeFicha(
    ficha: CopiaDeFicha,
    decididos: Map<String, String>
): Map<String, Any?>? {
    val estado = ficha.codigoMunicipal?.let { decididos[it] } ?: PENDIENTE
    return if (estado == ficha.estado) null else mapOf("estado" to estado)
}
