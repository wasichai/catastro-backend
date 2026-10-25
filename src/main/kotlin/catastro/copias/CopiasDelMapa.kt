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
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.cancel
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.sync.withPermit
import org.slf4j.LoggerFactory
import org.springframework.beans.factory.annotation.Value
import org.springframework.scheduling.annotation.Scheduled
import org.springframework.stereotype.Component
import tools.jackson.databind.PropertyNamingStrategies
import tools.jackson.databind.annotation.JsonNaming
import wasichai.core.common.NotFoundException
import wasichai.core.data.RecordCriterion
import wasichai.core.data.RecordRequest
import wasichai.core.data.RecordService
import wasichai.core.metadata.MetadataService
import wasichai.core.metadata.ObjectDefinition
import wasichai.core.platform.ClusterLock
import java.math.BigDecimal
import java.time.Duration
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.ConcurrentLinkedQueue

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
    @param:Value("\${catastro.copias.espera:PT2S}") private val espera: Duration
) {
    private val log = LoggerFactory.getLogger(javaClass)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default + CoroutineName("copias-del-mapa"))
    private val senal = Channel<Unit>(Channel.CONFLATED)
    private val pendientes: MutableSet<UUID> = ConcurrentHashMap.newKeySet()
    private val esperando = ConcurrentLinkedQueue<Pair<UUID, CompletableDeferred<CopiasHechas>>>()

    // one run at a time in this instance; the cluster lock keeps the other replicas out
    private val enCurso = Mutex()

    @PostConstruct
    fun iniciar() {
        scope.launch {
            for (aviso in senal) {
                delay(espera.toMillis())
                try {
                    atenderPendientes()
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    log.warn("copias del mapa: {}", e.message, e)
                }
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

    // a run for the organization, awaited: what it wrote. the run itself is the job's, not the caller's
    suspend fun ahora(organizacion: UUID): CopiasHechas {
        val hecho = CompletableDeferred<CopiasHechas>()
        // the waiter before the organization: a run that takes the organization always finds its waiter
        esperando += organizacion to hecho
        avisar(organizacion)
        return hecho.await()
    }

    // every organization, every `periodo` from the start
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

    private suspend fun atenderPendientes() {
        enCurso.withLock {
            val lease = clusterLock.tryLock(LLAVE)
            if (lease == null) {
                // another replica is running: try again after it
                senal.trySend(Unit)
                return
            }
            lease.use {
                val organizaciones = pendientes.toList().also { pendientes.removeAll(it.toSet()) }
                for (organizacion in organizaciones) {
                    val resultado =
                        try {
                            Result.success(records.asPlatform(organizacion, FUENTE) { CopiasHechas(anioEnCurso(), tramos(organizacion), fichas(organizacion)) })
                        } catch (e: CancellationException) {
                            throw e
                        } catch (e: Exception) {
                            log.warn("copias del mapa de {}: {}", organizacion, e.message, e)
                            Result.failure(e)
                        }
                    esperando.filter { it.first == organizacion }.forEach { espera ->
                        esperando.remove(espera)
                        resultado.fold({ espera.second.complete(it) }, { espera.second.completeExceptionally(it) })
                    }
                }
            }
        }
    }

    // the tramos whose copy differs from the arancel of the current year, patched: how many
    private suspend fun tramos(organizacion: UUID): Int {
        val definicion = definicion(organizacion, TRAMO_VIA, VALOR_M2, ANIO_VALOR, ID_ARANC) ?: return 0
        if (definicion(organizacion, ARANCEL, VALOR_M2, ANIO, ID_ARANC) == null) return 0
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
                criteria = listOf(tramoDistinto(definicion, valores, anio))
            )
        return escribir(TRAMO_VIA, distintos.mapNotNull { t -> copiaDeTramo(t, valores, anio)?.let { t.id to it } })
    }

    // the fichas of the most recent corte whose estado differs from their decision, patched: how many
    private suspend fun fichas(organizacion: UUID): Int {
        val definicion = definicion(organizacion, BRECHA_FICHA, ESTADO, CODIGO_MUNICIPAL) ?: return 0
        val corte = completos(registros.todas(CORTE_BRECHA, CorteBrecha::class.java, sort = "clave")).firstOrNull() ?: return 0
        val anio = corte.anio ?: return 0
        val decididos =
            registros
                .todas(DECISION_BRECHA, DecisionBrecha::class.java, sort = "clave", filters = mapOf(ANIO to anio.toString()))
                .mapNotNull { d -> d.codigoMunicipal?.let { c -> d.estado?.let { c to it } } }
                .toMap()
        val candidatas =
            registros.todas(
                BRECHA_FICHA,
                CopiaDeFicha::class.java,
                sort = "clave",
                filters = mapOf("corte" to corte.id),
                criteria = listOf(fichaCandidata(definicion, decididos.keys))
            )
        return escribir(BRECHA_FICHA, candidatas.mapNotNull { f -> copiaDeFicha(f, decididos)?.let { f.id to it } })
    }

    private suspend fun escribir(
        objeto: String,
        cambios: List<Pair<String, Map<String, Any?>>>
    ): Int {
        val limite = Semaphore(ESCRITURAS_A_LA_VEZ)
        coroutineScope {
            cambios
                .map { (id, atributos) -> async { limite.withPermit { records.patch(objeto, UUID.fromString(id), RecordRequest(atributos), RAZON) } } }
                .awaitAll()
        }
        return cambios.size
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

        private fun ObjectDefinition.columna(campo: String) = "\"${fields.first { it.name == campo }.columnName}\""

        // a tramo whose valor_m2 or anio_valor is not what `valores` (id_aranc -> valor_m2 of `anio`) says
        fun tramoDistinto(
            definicion: ObjectDefinition,
            valores: Map<String, BigDecimal>,
            anio: Int
        ) = RecordCriterion { _, bind ->
            val ids = valores.keys.toTypedArray()
            val textos = valores.values.map { it.toPlainString() }.toTypedArray()
            val id = definicion.columna(ID_ARANC)
            "(${definicion.columna(VALOR_M2)} IS DISTINCT FROM (SELECT CAST(v.valor AS numeric) FROM unnest(CAST(${bind(ids)} AS text[]), " +
                "CAST(${bind(textos)} AS text[])) AS v(id, valor) WHERE v.id = $id) " +
                "OR ${definicion.columna(
                    ANIO_VALOR
                )} IS DISTINCT FROM (SELECT CAST(${bind(anio)} AS bigint) FROM unnest(CAST(${bind(ids.copyOf())} AS text[])) " +
                "AS i(id) WHERE i.id = $id))"
        }

        // a ficha that may differ: any estado but PENDIENTE (an empty one too), or a decided code
        fun fichaCandidata(
            definicion: ObjectDefinition,
            decididos: Collection<String>
        ) = RecordCriterion { _, bind ->
            "(${definicion.columna(
                ESTADO
            )} IS DISTINCT FROM ${bind(PENDIENTE)} OR ${definicion.columna(CODIGO_MUNICIPAL)} = ANY(CAST(${bind(decididos.toTypedArray())} AS text[])))"
        }
    }
}

// what a run wrote for one organization: tramos and fichas patched
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy::class)
data class CopiasHechas(
    val anio: Int,
    val tramos: Int,
    val fichas: Int
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
