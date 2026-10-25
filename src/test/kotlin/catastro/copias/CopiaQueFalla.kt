package catastro.copias

import catastro.vias.TRAMO_VIA
import org.springframework.stereotype.Component
import wasichai.core.common.ValidationException
import wasichai.core.data.RecordWrite
import wasichai.core.data.RecordWriteGuard

// test only: refuses the platform's write of a tramo whose cod_via_eje starts with FALLA-, so CopiasDelMapaApiTest can
// show that a record the job cannot write does not stop the others. no real record carries that mark
@Component
class CopiaQueFalla : RecordWriteGuard {
    override suspend fun beforeWrite(change: RecordWrite) {
        if (change.objectName == TRAMO_VIA && change.userId == null && change.before
                ?.get("cod_via_eje")
                ?.toString()
                ?.startsWith(MARCA) == true
        ) {
            throw ValidationException("tramo de prueba que no se copia", "valor_m2", "rechazado por la prueba")
        }
    }

    companion object {
        const val MARCA = "FALLA-"
    }
}
