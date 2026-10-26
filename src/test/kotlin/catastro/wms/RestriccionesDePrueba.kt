package catastro.wms

import org.springframework.stereotype.Component
import wasichai.core.data.RecordCriterion
import wasichai.core.data.RecordReadMask
import wasichai.core.data.RecordReadScope
import wasichai.core.identity.AuthenticatedUser
import wasichai.core.metadata.ObjectDefinition

// test only: a read scope (ADR-048) that leaves a caller holding a role whose name starts with WMS_ALCANCE_ with
// nothing in scope, so AutorizacionWmsApiTest can show such a caller gets no tile. no real role carries that name
@Component
class AlcanceDePrueba : RecordReadScope {
    override suspend fun criterion(
        caller: AuthenticatedUser,
        definition: ObjectDefinition
    ): RecordCriterion? = if (caller.roles.any { it.startsWith(MARCA) }) RecordCriterion { _, _ -> "false" } else null

    companion object {
        const val MARCA = "WMS_ALCANCE_"
    }
}

// test only: a read mask (ADR-065) on the object OBJETO, which no real model has, rewriting nothing
@Component
class MascaraDePrueba : RecordReadMask {
    override fun appliesTo(definition: ObjectDefinition): Boolean = definition.obj.name == OBJETO

    override suspend fun mask(
        caller: AuthenticatedUser,
        definition: ObjectDefinition,
        stored: Map<String, Any?>,
        attributes: Map<String, Any?>
    ): Map<String, Any?> = attributes

    companion object {
        const val OBJETO = "capa_enmascarada"
    }
}
