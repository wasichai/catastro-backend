package catastro.brechas

import kotlinx.coroutines.currentCoroutineContext
import org.springframework.stereotype.Component
import wasichai.core.common.ForbiddenException
import wasichai.core.data.RecordWrite
import wasichai.core.data.RecordWriteGuard
import kotlin.coroutines.AbstractCoroutineContextElement
import kotlin.coroutines.CoroutineContext

// POST /api/catastro/brechas/decisiones is the only door into decision_brecha. CATASTRO_ANALISTA needs CREATE and UPDATE
// on it, because the endpoint writes as the caller (so core's permissions, audit and field rules apply to that
// person), but with them alone it could write a decision straight through /api/objects/decision_brecha/records with
// any responsable, decidido_en or corte_origen, or a DESCARTADO without motivo. wasichai's way to keep an app's own
// rules (ADR-040, RecordWriteGuard): the app marks its in-process writes with a coroutine context element and a guard
// refuses every write of the object without it. the generic record api, the admin, automations and the platform
// carry none: they get a 403, also to delete. (RecordService.asPlatform, the other way to write past the caller's
// permissions, is refused inside a request by design.)
@Component
class DecisionesSoloPorLaApi : RecordWriteGuard {
    override suspend fun beforeWrite(change: RecordWrite) {
        if (change.objectName == DECISION_BRECHA && currentCoroutineContext()[EscrituraDeBrechas] == null) {
            throw ForbiddenException("decision_brecha se escribe solo con POST /api/catastro/brechas/decisiones")
        }
    }
}

// the mark of BrechasService.decidir's writes
class EscrituraDeBrechas : AbstractCoroutineContextElement(EscrituraDeBrechas) {
    companion object Key : CoroutineContext.Key<EscrituraDeBrechas>
}
