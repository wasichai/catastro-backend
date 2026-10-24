package catastro

import org.springframework.http.HttpStatus
import wasichai.core.common.FieldViolation
import wasichai.core.common.WasichaiException

// a field of a request body an endpoint cannot read: a 422 that names it (its path, e.g. construcciones[0].muros),
// never a datum silently dropped. ParametroInvalido is the same for a query parameter
class CampoInvalido(
    nombre: String,
    razon: String
) : WasichaiException(HttpStatus.UNPROCESSABLE_CONTENT, "El campo '$nombre' $razon", listOf(FieldViolation(nombre, razon)))
