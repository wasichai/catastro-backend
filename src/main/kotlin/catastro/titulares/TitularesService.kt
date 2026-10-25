package catastro.titulares

import catastro.Registros
import catastro.valuacion.TITULAR_CATASTRAL
import org.springframework.stereotype.Service
import wasichai.core.common.PageRequest
import wasichai.core.data.RecordQuery

// one page of titulares, by codigo_municipal and then by record id (core's own paging keeps the order stable):
// mirrors ValuacionesService's shape, with no other object to join
@Service
class TitularesService(
    private val registros: Registros
) {
    suspend fun pagina(
        page: Int,
        size: Int
    ): Titulares {
        val titulares =
            registros.pagina(
                TITULAR_CATASTRAL,
                TitularCatastral::class.java,
                RecordQuery(page = PageRequest(page, size), sort = "codigo_municipal")
            )
        val items =
            titulares.content.map {
                ItemTitular(
                    codigoMunicipal = it.codigoMunicipal,
                    tipoDocumento = it.tipoDocumento,
                    numeroDocumento = it.numeroDocumento,
                    nombre = it.nombre,
                    porcentaje = it.porcentaje,
                    condicion = it.condicion
                )
            }
        return Titulares(page, size, titulares.totalElements ?: 0L, items)
    }

    companion object {
        const val TAMANO = 200
        const val TAMANO_MAXIMO = 500
    }
}
