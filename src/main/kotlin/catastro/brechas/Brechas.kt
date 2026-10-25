package catastro.brechas

import com.fasterxml.jackson.annotation.JsonProperty
import tools.jackson.databind.PropertyNamingStrategies
import tools.jackson.databind.annotation.JsonNaming
import java.math.BigDecimal

// the objects of model/model.json behind the brechas dashboard (importar_corte_brecha.py loads the first two)
const val CORTE_BRECHA = "corte_brecha"
const val BRECHA_FICHA = "brecha_ficha"
const val DECISION_BRECHA = "decision_brecha"

// the model's enums, in its order: categoria_brecha, confianza_brecha and estado_decision
val CATEGORIAS = listOf("OMISO", "SIN_CATASTRO", "SIN_VALOR", "SUBVALUADO", "SOBREVALUADO", "COINCIDE", "SIN_LEVANTAR")
val CONFIANZAS = listOf("CONFIABLE", "DUDOSO", "SIN_LEVANTAR")
val ESTADOS = listOf("PENDIENTE", "A_INSPECCIONAR", "INSPECCIONADO", "A_FISCALIZAR", "DESCARTADO")
const val PENDIENTE = "PENDIENTE"
const val DESCARTADO = "DESCARTADO"
const val OMISO = "OMISO"
const val CONFIABLE = "CONFIABLE"

// the cortes whose load finished (a corte without cargado_en is one importar_corte_brecha.py is still loading, or left
// half done: never shown), the most recent first: by fecha, two cortes of a day by clave. the dashboard and the map's
// copies (catastro.copias) read "the most recent corte" from here
fun completos(cortes: List<CorteBrecha>): List<CorteBrecha> =
    cortes
        .filter { !it.cargadoEn.isNullOrBlank() }
        .sortedWith(compareByDescending<CorteBrecha, String?>(nullsFirst()) { it.fecha }.thenByDescending { it.clave })

// the records as core returns them (fields by their model names); a DATE or DATETIME is read as its ISO text

@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy::class)
data class CorteBrecha(
    val id: String,
    val clave: String? = null,
    val fecha: String? = null,
    val corrida: String? = null,
    val anio: Int? = null,
    val totalFichas: Int? = null,
    val deltaImpuesto: BigDecimal? = null,
    val cargadoEn: String? = null
)

@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy::class)
data class BrechaFicha(
    val id: String,
    val codigoCatastro: String? = null,
    val codigoMunicipal: String? = null,
    val codigoPredio: String? = null,
    val categoria: String? = null,
    val confianza: String? = null,
    val confianzaMotivo: String? = null,
    val sector: String? = null,
    val manzana: String? = null,
    val lote: String? = null,
    val uso: String? = null,
    val autoavaluoDeclarado: BigDecimal? = null,
    val autoavaluoCatastro: BigDecimal? = null,
    val deltaAutoavaluo: BigDecimal? = null,
    val impuestoDeclarado: BigDecimal? = null,
    val impuestoCatastro: BigDecimal? = null,
    val deltaImpuesto: BigDecimal? = null,
    val deltaArbitrios: BigDecimal? = null,
    val estimado: Boolean? = null,
    val motivo: String? = null,
    @param:JsonProperty("supera_5_uit") val supera5Uit: Boolean? = null
)

@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy::class)
data class DecisionBrecha(
    val id: String,
    val clave: String? = null,
    val codigoMunicipal: String? = null,
    val estado: String? = null,
    val responsable: String? = null,
    val nota: String? = null,
    val decididoEn: String? = null
)

// a ficha read only for its code: whether it has a lote (the criterion asks for one) or exists at all
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy::class)
data class CodigoDePredio(
    val id: String,
    val codigoMunicipal: String? = null
)

// a ficha with its lote, GeoJSON in EPSG:4326 (wasichai-gis transforms it from the column's 32718)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy::class)
data class LoteDePredio(
    val id: String,
    val codigoMunicipal: String? = null,
    val loteGeom: Map<String, Any?>? = null
)

// what the API answers (contract of catastro-ui: snake_case keys)

@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy::class)
data class CorteResumen(
    val clave: String?,
    val fecha: String?,
    val anio: Int?,
    val corrida: String?,
    val totalFichas: Int?,
    val deltaImpuesto: BigDecimal?,
    val cargadoEn: String?
)

// one row of GET /fichas (and of the csv, in this order): the ficha of the corte, its decision of the corte's year
// (PENDIENTE without one) and whether its predio_catastral has a lote
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy::class)
data class FilaFicha(
    val id: String,
    val codigoCatastro: String?,
    val codigoMunicipal: String?,
    val codigoPredio: String?,
    val categoria: String?,
    val confianza: String?,
    val confianzaMotivo: String?,
    val sector: String?,
    val manzana: String?,
    val lote: String?,
    val uso: String?,
    val autoavaluoDeclarado: BigDecimal?,
    val autoavaluoCatastro: BigDecimal?,
    val deltaAutoavaluo: BigDecimal?,
    val impuestoDeclarado: BigDecimal?,
    val impuestoCatastro: BigDecimal?,
    val deltaImpuesto: BigDecimal?,
    val deltaArbitrios: BigDecimal?,
    val estimado: Boolean?,
    val motivo: String?,
    @get:JsonProperty("supera_5_uit") val supera5Uit: Boolean?,
    val estado: String,
    val responsable: String?,
    val nota: String?,
    val decididoEn: String?,
    val conGeometria: Boolean
) {
    // the csv's cells, in the json's order
    fun celdas(): List<Any?> =
        listOf(
            id,
            codigoCatastro,
            codigoMunicipal,
            codigoPredio,
            categoria,
            confianza,
            confianzaMotivo,
            sector,
            manzana,
            lote,
            uso,
            autoavaluoDeclarado,
            autoavaluoCatastro,
            deltaAutoavaluo,
            impuestoDeclarado,
            impuestoCatastro,
            deltaImpuesto,
            deltaArbitrios,
            estimado,
            motivo,
            supera5Uit,
            estado,
            // who decided, without the domain of the email: the csv carries no personal data
            responsable?.substringBefore('@'),
            nota,
            decididoEn,
            conGeometria
        )

    companion object {
        val COLUMNAS =
            listOf(
                "id",
                "codigo_catastro",
                "codigo_municipal",
                "codigo_predio",
                "categoria",
                "confianza",
                "confianza_motivo",
                "sector",
                "manzana",
                "lote",
                "uso",
                "autoavaluo_declarado",
                "autoavaluo_catastro",
                "delta_autoavaluo",
                "impuesto_declarado",
                "impuesto_catastro",
                "delta_impuesto",
                "delta_arbitrios",
                "estimado",
                "motivo",
                "supera_5_uit",
                "estado",
                "responsable",
                "nota",
                "decidido_en",
                "con_geometria"
            )
    }
}

data class CorteDelPanel(
    val clave: String?,
    val fecha: String?,
    val anio: Int?,
    val corrida: String?
)

@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy::class)
data class Kpis(
    val fichas: Int,
    val deltaImpuesto: BigDecimal,
    val deltaImpuestoConfiable: BigDecimal,
    val omisosEstimado: BigDecimal,
    @get:JsonProperty("supera_5_uit") val supera5Uit: Int,
    val pendientes: Int,
    val conGeometria: Int,
    // fichas without codigo_municipal: they cannot be decided, so they are not pendientes
    val sinFicha: Int
)

@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy::class)
data class Cuenta(
    val clave: String?,
    val fichas: Int,
    val deltaImpuesto: BigDecimal
)

data class CuentaDeEstado(
    val clave: String,
    val fichas: Int
)

@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy::class)
data class Sector(
    val sector: String,
    val fichas: Int,
    val deltaImpuesto: BigDecimal
)

@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy::class)
data class Panel(
    val corte: CorteDelPanel,
    val kpis: Kpis,
    val porCategoria: List<Cuenta>,
    val porConfianza: List<Cuenta>,
    val porEstado: List<CuentaDeEstado>,
    val topSectores: List<Sector>
)

data class ErrorDeDecision(
    val codigo: String,
    val error: String
)

data class ResultadoDecisiones(
    val actualizadas: Int,
    val creadas: Int,
    val errores: List<ErrorDeDecision>
)

// GET /fichas, /lotes and /fichas.csv: every filter given must hold. a set holds when the ficha's value is one of it;
// min_delta compares against |delta_impuesto|, so a ficha without one is out
data class Filtro(
    val categorias: Set<String>? = null,
    val confianzas: Set<String>? = null,
    val sector: String? = null,
    val estados: Set<String>? = null,
    val supera5Uit: Boolean? = null,
    val minDelta: BigDecimal? = null
) {
    fun admite(fila: FilaFicha): Boolean =
        (categorias == null || fila.categoria in categorias) &&
            (confianzas == null || fila.confianza in confianzas) &&
            (sector == null || fila.sector == sector) &&
            (estados == null || fila.estado in estados) &&
            (supera5Uit == null || (fila.supera5Uit ?: false) == supera5Uit) &&
            (minDelta == null || (fila.deltaImpuesto != null && fila.deltaImpuesto.abs() >= minDelta))
}

enum class Orden(
    val parametro: String,
    val comparador: Comparator<FilaFicha>
) {
    // the largest Δ impuesto first, a ficha without one last; then by code, so a page is the same on every call
    DELTA_DESC("delta_desc", compareBy<FilaFicha, BigDecimal?>(nullsLast(reverseOrder())) { it.deltaImpuesto }.then(porCodigo())),
    DELTA_ASC("delta_asc", compareBy<FilaFicha, BigDecimal?>(nullsLast()) { it.deltaImpuesto }.then(porCodigo())),
    CODIGO("codigo", porCodigo());

    companion object {
        fun de(parametro: String): Orden? = entries.firstOrNull { it.parametro == parametro }
    }
}

// codigo_catastro, a ficha without one (SIN_CATASTRO) last by its srtm code; the record id breaks a tie
private fun porCodigo(): Comparator<FilaFicha> =
    compareBy<FilaFicha, String?>(nullsLast()) { it.codigoCatastro }
        .thenBy(nullsLast()) { it.codigoPredio }
        .thenBy { it.id }

// a corte read whole: its fichas joined with their decision and their lote, in srtm's order
data class Vista(
    val corte: CorteBrecha,
    val filas: List<FilaFicha>
)

internal fun fila(
    ficha: BrechaFicha,
    decision: DecisionBrecha?,
    conGeometria: Boolean
): FilaFicha =
    FilaFicha(
        id = ficha.id,
        codigoCatastro = ficha.codigoCatastro,
        codigoMunicipal = ficha.codigoMunicipal,
        codigoPredio = ficha.codigoPredio,
        categoria = ficha.categoria,
        confianza = ficha.confianza,
        confianzaMotivo = ficha.confianzaMotivo,
        sector = ficha.sector,
        manzana = ficha.manzana,
        lote = ficha.lote,
        uso = ficha.uso,
        autoavaluoDeclarado = ficha.autoavaluoDeclarado?.limpio(),
        autoavaluoCatastro = ficha.autoavaluoCatastro?.limpio(),
        deltaAutoavaluo = ficha.deltaAutoavaluo?.limpio(),
        impuestoDeclarado = ficha.impuestoDeclarado?.limpio(),
        impuestoCatastro = ficha.impuestoCatastro?.limpio(),
        deltaImpuesto = ficha.deltaImpuesto?.limpio(),
        deltaArbitrios = ficha.deltaArbitrios?.limpio(),
        estimado = ficha.estimado,
        motivo = ficha.motivo,
        supera5Uit = ficha.supera5Uit,
        estado = decision?.estado ?: PENDIENTE,
        responsable = decision?.responsable,
        nota = decision?.nota,
        decididoEn = decision?.decididoEn,
        conGeometria = conGeometria
    )

// the panel in one pass over every ficha of the corte: the kpis, the counts by categoria, confianza and estado (every
// option of the model, also those without fichas; a confianza left empty by a corte older than srtm-backend#204 as a
// clave null, only when there is one) and the 10 sectores of largest Δ impuesto. pendientes and por_estado count only
// the fichas that can be decided (with codigo_municipal); sin_ficha counts the others
internal fun panel(vista: Vista): Panel {
    var delta = BigDecimal.ZERO
    var confiable = BigDecimal.ZERO
    var omisos = BigDecimal.ZERO
    var supera = 0
    var pendientes = 0
    var conGeometria = 0
    var sinFicha = 0
    val categorias = linkedMapOf<String?, Acumulado>().apply { CATEGORIAS.forEach { put(it, Acumulado()) } }
    val confianzas = linkedMapOf<String?, Acumulado>().apply { CONFIANZAS.forEach { put(it, Acumulado()) } }
    val estados = linkedMapOf<String, Int>().apply { ESTADOS.forEach { put(it, 0) } }
    val sectores = hashMapOf<String, Acumulado>()
    for (fila in vista.filas) {
        val d = fila.deltaImpuesto ?: BigDecimal.ZERO
        delta += d
        if (fila.confianza == CONFIABLE) confiable += d
        if (fila.categoria == OMISO) omisos += d
        if (fila.supera5Uit == true) supera++
        if (fila.codigoMunicipal == null) {
            sinFicha++
        } else if (fila.estado == PENDIENTE) {
            pendientes++
        }
        if (fila.conGeometria) conGeometria++
        categorias.getOrPut(fila.categoria) { Acumulado() }.suma(d)
        confianzas.getOrPut(fila.confianza) { Acumulado() }.suma(d)
        if (fila.codigoMunicipal != null) estados.merge(fila.estado, 1, Int::plus)
        fila.sector?.let { sectores.getOrPut(it) { Acumulado() }.suma(d) }
    }
    val corte = vista.corte
    return Panel(
        corte = CorteDelPanel(corte.clave, corte.fecha, corte.anio, corte.corrida),
        kpis = Kpis(vista.filas.size, delta.limpio(), confiable.limpio(), omisos.limpio(), supera, pendientes, conGeometria, sinFicha),
        porCategoria = categorias.map { (clave, a) -> Cuenta(clave, a.fichas, a.delta.limpio()) },
        porConfianza = confianzas.filter { (clave, a) -> clave != null || a.fichas > 0 }.map { (clave, a) -> Cuenta(clave, a.fichas, a.delta.limpio()) },
        porEstado = estados.map { (clave, n) -> CuentaDeEstado(clave, n) },
        topSectores =
            sectores.entries
                .sortedWith(compareByDescending<Map.Entry<String, Acumulado>> { it.value.delta }.thenBy { it.key })
                .take(TOP_SECTORES)
                .map { (sector, a) -> Sector(sector, a.fichas, a.delta.limpio()) }
    )
}

private const val TOP_SECTORES = 10

private class Acumulado {
    var fichas = 0
    var delta: BigDecimal = BigDecimal.ZERO

    fun suma(d: BigDecimal) {
        fichas++
        delta += d
    }
}

// core reads a DECIMAL with the column's scale (120.5000000000): answered without the trailing zeros, never in
// exponent notation (100, not 1E+2)
internal fun BigDecimal.limpio(): BigDecimal = stripTrailingZeros().let { if (it.scale() < 0) it.setScale(0) else it }

private val FORMULA = setOf('=', '+', '-', '@', '\t', '\r')

// rfc 4180 with a utf-8 bom, so a spreadsheet opens the accents right: a header, then one line per row, crlf
internal fun csv(filas: List<FilaFicha>): ByteArray {
    val texto = StringBuilder("\uFEFF")
    texto.append(FilaFicha.COLUMNAS.joinToString(",")).append("\r\n")
    for (fila in filas) {
        texto.append(fila.celdas().joinToString(",") { celda(it) }).append("\r\n")
    }
    return texto.toString().toByteArray(Charsets.UTF_8)
}

private fun celda(valor: Any?): String {
    val texto =
        when (valor) {
            null -> ""
            is BigDecimal -> valor.toPlainString()
            is Boolean -> valor.toString()
            // a text a spreadsheet would take for a formula (=, +, -, @, a tab or a carriage return first: csv
            // injection) goes with a leading quote; numbers and booleans never do, so a Δ of -120.5 stays a number
            else -> valor.toString().let { if (it.isNotEmpty() && it[0] in FORMULA) "'$it" else it }
        }
    return if (texto.any { it == ',' || it == '"' || it == '\n' || it == '\r' }) "\"${texto.replace("\"", "\"\"")}\"" else texto
}
