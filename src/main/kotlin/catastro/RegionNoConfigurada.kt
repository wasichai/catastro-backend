package catastro

import org.springframework.http.HttpStatus
import wasichai.core.common.FieldViolation
import wasichai.core.common.WasichaiException

// the caller's organization has no region to value with (no configuracion_catastro record, more than one, or a region
// the engine has no tables for): a 409 that names it. there is no default region, so nothing is valued
class RegionNoConfigurada(
    razon: String
) : WasichaiException(
        HttpStatus.CONFLICT,
        "La organización no tiene una región de valuación: $razon",
        listOf(FieldViolation(CAMPO, razon))
    ) {
    companion object {
        const val CAMPO = "configuracion_catastro.region"
    }
}
