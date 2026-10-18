package catastro

import org.springframework.http.HttpStatus
import wasichai.core.common.FieldViolation
import wasichai.core.common.WasichaiException

// a query parameter an endpoint cannot serve, or cannot read: a 422 that names it, never a filter silently dropped
// (srtm-backend's ParametroInvalido)
class ParametroInvalido(
    nombre: String,
    razon: String
) : WasichaiException(HttpStatus.UNPROCESSABLE_CONTENT, "El parámetro '$nombre' $razon", listOf(FieldViolation(nombre, razon)))
