package catastro.copias

import catastro.brechas.BRECHA_FICHA
import catastro.brechas.CORTE_BRECHA
import catastro.brechas.DECISION_BRECHA
import catastro.valuacion.ARANCEL
import catastro.vias.TRAMO_VIA
import catastro.vias.anioEnCurso
import org.slf4j.LoggerFactory
import org.springframework.beans.factory.ObjectProvider
import org.springframework.core.Ordered
import org.springframework.core.annotation.Order
import org.springframework.scheduling.annotation.EnableScheduling
import org.springframework.stereotype.Component
import wasichai.core.data.RecordChange
import wasichai.core.data.RecordChangeKind
import wasichai.core.data.RecordChangeListener

// wasichai's after-write hook (RecordChangeListener, ADR-025): a write that changes what a map copy should hold nudges
// CopiasDelMapa for its organization, and nothing else. it writes nothing, never suspends on the job and never throws,
// so it cannot fail or slow the write that triggered it (srtm's sync of aranceles, a decision), nor the listeners after
// it: it runs last. a miss is healed by the next periodic run anyway
@Component
@Order(Ordered.LOWEST_PRECEDENCE)
@EnableScheduling
class AvisosDeCopias(
    // a provider: RecordService takes every listener, and CopiasDelMapa takes RecordService
    private val copias: ObjectProvider<CopiasDelMapa>
) : RecordChangeListener {
    private val log = LoggerFactory.getLogger(javaClass)

    override suspend fun recordChanged(change: RecordChange) {
        try {
            if (avisa(change, anioEnCurso())) copias.getObject().avisar(change.organizationId)
        } catch (e: Exception) {
            log.warn("copias del mapa: no se avisó {} {}: {}", change.objectName, change.recordId, e.message)
        }
    }
}

// whether a write may change a copy: an arancel of the year, a tramo new or with another id_aranc, any decision, a corte
// that becomes visible or is deleted, a ficha new or with another estado (the loader may write an older one). the platform's own
// writes (the copies themselves) never nudge, or each run would ask for the next
fun avisa(
    change: RecordChange,
    anio: Int
): Boolean {
    if (change.userId == null) return false
    val cambio = { campo: String -> change.kind == RecordChangeKind.CREATED || change.before?.get(campo) != change.after?.get(campo) }
    return when (change.objectName) {
        ARANCEL -> arancelesDelAnio(change, anio).isNotEmpty()
        TRAMO_VIA -> change.kind != RecordChangeKind.DELETED && cambio("id_aranc")
        DECISION_BRECHA -> true
        // a corte that shows, or goes: the most recent one may be another
        CORTE_BRECHA -> change.kind == RecordChangeKind.DELETED || cambio("cargado_en")
        BRECHA_FICHA -> change.kind != RecordChangeKind.DELETED && cambio("estado")
        else -> false
    }
}

// the id_aranc an arancel's write touched in `anio`: the one it had and the one it has, when their anio is `anio`
fun arancelesDelAnio(
    change: RecordChange,
    anio: Int
): Set<String> =
    listOfNotNull(change.before, change.after)
        .filter { it["anio"]?.toString()?.trim()?.toIntOrNull() == anio }
        .mapNotNull { it["id_aranc"]?.toString()?.trim()?.ifEmpty { null } }
        .toSet()
