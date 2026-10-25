package catastro.brechas

import catastro.Copias
import org.springframework.r2dbc.core.DatabaseClient
import org.springframework.r2dbc.core.awaitRowsUpdated
import org.springframework.stereotype.Component
import java.util.UUID

// brecha_ficha.estado, the copy of the decision the map view brechas_estado and the WMS layer colour by: POST
// /decisiones writes it on the fichas of the decided codes in the most recent corte of the decision's year (the corte
// the map shows; importar_corte_brecha.py copies every decision when it loads one). through Copias, not as the
// caller: CATASTRO_ANALISTA holds no UPDATE on brecha_ficha, and DecisionesSoloPorLaApi, which guards decision_brecha
// alone, never sees this write, so the loader's own writes of brecha_ficha through core keep working
@Component
class EstadoDeFichas(
    private val db: DatabaseClient,
    private val copias: Copias
) {
    // how many fichas changed
    suspend fun copiar(
        organizacion: UUID,
        corte: UUID,
        estado: String,
        codigos: Collection<String>
    ): Long {
        if (codigos.isEmpty()) return 0
        val t = copias.tabla(organizacion, BRECHA_FICHA, listOf(CORTE, CODIGO_MUNICIPAL, ESTADO)) ?: return 0
        return db
            .sql(
                """
                UPDATE ${t.nombre} SET ${t.columna(ESTADO)} = :estado
                WHERE organization_id = :organizacion AND ${t.columna(CORTE)} = :corte
                  AND ${t.columna(CODIGO_MUNICIPAL)} = ANY(:codigos) AND ${t.columna(ESTADO)} IS DISTINCT FROM :estadoNuevo
                """.trimIndent()
            ).bind("estado", estado)
            .bind("organizacion", organizacion)
            .bind("corte", corte)
            .bind("codigos", codigos.distinct().toTypedArray())
            .bind("estadoNuevo", estado)
            .fetch()
            .awaitRowsUpdated()
    }

    private companion object {
        const val CORTE = "corte"
        const val CODIGO_MUNICIPAL = "codigo_municipal"
        const val ESTADO = "estado"
    }
}
