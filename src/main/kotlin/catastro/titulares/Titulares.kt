package catastro.titulares

import com.fasterxml.jackson.annotation.JsonInclude
import tools.jackson.databind.PropertyNamingStrategies
import tools.jackson.databind.annotation.JsonNaming
import java.math.BigDecimal

// the contract srtm-backend reads (GET /api/catastro/titulares): a dedicated, lighter endpoint than the generic
// record API, because srtm needs codigoMunicipal and the generic API only gives the predio's uuid (contract 2,
// wasichai/srtm-backend#202). datos personales (Ley 29733): SRTM_LECTOR is the only reader. every key is always
// written, null included, like Valuaciones
@JsonInclude(JsonInclude.Include.ALWAYS)
data class Titulares(
    val page: Int,
    val size: Int,
    // titulares the caller may read, in every page
    val total: Long,
    val items: List<ItemTitular>
)

// one titular of a predio. codigoMunicipal is the predio's own code, repeated here because core pages by one field
// of the object itself plus the id. porcentaje and the rest are null without data; a filler documento (000000000) is
// loaded empty by import_fichas.py, not sent here as "000000000"
@JsonInclude(JsonInclude.Include.ALWAYS)
data class ItemTitular(
    val codigoMunicipal: String?,
    val tipoDocumento: String?,
    val numeroDocumento: String?,
    val nombre: String?,
    val porcentaje: BigDecimal?,
    val condicion: String?
)

// the record as core returns it (model/model.json's titular_catastral), json keys in snake_case; every field
// nullable, as the admin or a field permission may leave any of them out
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy::class)
data class TitularCatastral(
    val id: String,
    val codigoMunicipal: String? = null,
    val tipoDocumento: String? = null,
    val numeroDocumento: String? = null,
    val nombre: String? = null,
    val porcentaje: BigDecimal? = null,
    val condicion: String? = null
)
