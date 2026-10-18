package catastro.tablas

import java.io.Reader
import java.math.BigDecimal

// the three partidas of the selva cuadro (anexo I.4); a construction's VU is their sum (D4, in the engine)
enum class Partida { MUROS_COLUMNAS, TECHOS, PUERTAS_VENTANAS }

// valorM2 null is a "....." cell: the cuadro gives no value there, which is not zero (D5)
data class CeldaValorUnitario(
    val partida: Partida,
    val categoria: String,
    val valorM2: BigDecimal?
)

// antiguedadHasta null is the open-ended "más de 50" tramo, as the RNT csv encodes it
data class TramoDepreciacion(
    val tabla: String,
    val material: String,
    val estadoConservacion: String,
    val antiguedadHasta: Int?,
    val porcentaje: BigDecimal
)

// codigo is "tipo_obra|numero", the same key as obra_complementaria.codigo_vu. valorUnitario is at direct cost
data class ObraComplementaria(
    val codigo: String,
    val tipoObra: String,
    val numero: Int,
    val descripcion: String,
    val unidadMedida: String,
    val material: String?,
    val valorUnitario: BigDecimal
)

data class UsoTabla(
    val prefijo: String,
    val tabla: String,
    val descripcion: String
)

data class Parametro(
    val clave: String,
    val anio: Int,
    val valor: BigDecimal,
    val fuente: String
)

// the claves parametros.csv ships, so the engine does not spell them twice
object ClaveParametro {
    const val FACTOR_OFICIALIZACION = "FACTOR_OFICIALIZACION"
    const val PORCENTAJE_ACTUALIZACION = "PORCENTAJE_ACTUALIZACION"
    const val INCREMENTO_PISO_DESDE = "INCREMENTO_PISO_DESDE"
    const val INCREMENTO_PISO_PORCENTAJE = "INCREMENTO_PISO_PORCENTAJE"
}

// the normative tables, loaded once and never changed. lookups speak the sources' own vocabulary (RNT material and
// estado as written in depreciacion-rnt-2016.csv); mapping catastro's enums onto it (D2, D3) is the engine's job
class Tablas(
    val valoresUnitarios: List<CeldaValorUnitario>,
    val depreciaciones: List<TramoDepreciacion>,
    val obras: List<ObraComplementaria>,
    val usos: List<UsoTabla>,
    val parametros: List<Parametro>
) {
    private val vu = valoresUnitarios.associateBy { it.partida to it.categoria }
    private val series = depreciaciones.groupBy { Triple(it.tabla, it.material, it.estadoConservacion) }
    private val obrasPorCodigo = obras.associateBy { it.codigo }
    private val usosPorPrefijo = usos.associateBy { it.prefijo }
    private val parametrosPorClave = parametros.associateBy { it.clave to it.anio }

    // the RNT's tramos (hasta 5, 10 … 50) taken from the whole table: a series missing its tail ('*' cells) must not
    // shift an age into another tramo
    private val topes = depreciaciones.mapNotNull { it.antiguedadHasta }.distinct().sorted()

    val categorias: List<String> = valoresUnitarios.map { it.categoria }.distinct().sorted()

    init {
        require(vu.size == valoresUnitarios.size) { "valores unitarios: partida y categoría repetidas" }
        require(vu.size == Partida.entries.size * categorias.size) { "valores unitarios: faltan celdas del cuadro" }
        series.forEach { (llave, tramos) ->
            require(tramos.map { it.antiguedadHasta }.distinct().size == tramos.size) { "depreciación $llave: tramo repetido" }
        }
        require(obrasPorCodigo.size == obras.size) { "obras: código repetido" }
        require(usosPorPrefijo.size == usos.size) { "usos: prefijo repetido" }
        val tablasRnt = depreciaciones.map { it.tabla }.toSet()
        usos.forEach { require(it.tabla in tablasRnt) { "uso ${it.prefijo}: tabla ${it.tabla} no está en el RNT" } }
        require(parametrosPorClave.size == parametros.size) { "parámetros: clave y año repetidos" }
    }

    // null when the cell is "....."; an unknown categoría is a caller error, not a missing value
    fun valorUnitario(
        partida: Partida,
        categoria: String
    ): BigDecimal? {
        require(categoria in categorias) { "categoría $categoria no está en el cuadro de la selva (${categorias.joinToString("")})" }
        return vu.getValue(partida to categoria).valorM2
    }

    // the RNT percentage for an age in whole years: the first tramo whose tope is >= the age, else "más de 50".
    // null when that cell is a '*' (no row): the engine applies D3. an unknown tabla/material/estado throws
    fun depreciacion(
        tabla: String,
        material: String,
        estado: String,
        antiguedadAnios: Int
    ): BigDecimal? {
        require(antiguedadAnios >= 0) { "antigüedad negativa: $antiguedadAnios" }
        val tope = topes.firstOrNull { it >= antiguedadAnios }
        return serieDepreciacion(tabla, material, estado).firstOrNull { it.antiguedadHasta == tope }?.porcentaje
    }

    // the published tramos of one row, in order: what D3 needs to take the last published percentage
    fun serieDepreciacion(
        tabla: String,
        material: String,
        estado: String
    ): List<TramoDepreciacion> =
        requireNotNull(series[Triple(tabla, material, estado)]) {
            "depreciación: no hay tabla $tabla, material $material, estado $estado en el RNT"
        }

    // longest prefix of the srtm usos_predio code; null when no prefix matches
    fun tablaPorUso(usoCodigo: String): String? = (usoCodigo.length downTo 1).firstNotNullOfOrNull { usosPorPrefijo[usoCodigo.take(it)] }?.tabla

    // codigo as "TIPO DE OBRA|numero"; null when the cuadro has no such partida
    fun obra(codigo: String): ObraComplementaria? = obrasPorCodigo[codigo]

    fun parametro(
        clave: String,
        anio: Int
    ): BigDecimal? = parametrosPorClave[clave to anio]?.valor

    companion object {
        const val VALORES_UNITARIOS = "tablas/valores-unitarios-selva-2026.csv"
        const val DEPRECIACION = "tablas/depreciacion-rnt-2016.csv"
        const val OBRAS = "tablas/obras-complementarias-selva-2026.csv"
        const val USOS = "tablas/uso-tabla-depreciacion.csv"
        const val PARAMETROS = "tablas/parametros.csv"

        fun cargar(
            valoresUnitarios: Reader,
            depreciacion: Reader,
            obras: Reader,
            usos: Reader,
            parametros: Reader
        ): Tablas =
            Tablas(
                valoresUnitarios =
                    Csv.leer(valoresUnitarios, "valores unitarios").map {
                        CeldaValorUnitario(
                            partida = Partida.valueOf(it.getValue("partida")),
                            categoria = it.getValue("categoria"),
                            valorM2 = it.getValue("valor_m2").ifEmpty { null }?.let(::BigDecimal)
                        )
                    },
                depreciaciones =
                    Csv.leer(depreciacion, "depreciación").map {
                        TramoDepreciacion(
                            tabla = it.getValue("tabla"),
                            material = it.getValue("material"),
                            estadoConservacion = it.getValue("estado_conservacion"),
                            antiguedadHasta = it.getValue("antiguedad_hasta").ifEmpty { null }?.toInt(),
                            porcentaje = BigDecimal(it.getValue("porcentaje"))
                        )
                    },
                obras =
                    Csv.leer(obras, "obras").map {
                        ObraComplementaria(
                            codigo = "${it.getValue("tipo_obra")}|${it.getValue("numero")}",
                            tipoObra = it.getValue("tipo_obra"),
                            numero = it.getValue("numero").toInt(),
                            descripcion = it.getValue("descripcion"),
                            unidadMedida = it.getValue("unidad_medida"),
                            material = it.getValue("material").ifEmpty { null },
                            valorUnitario = BigDecimal(it.getValue("valor_unitario"))
                        )
                    },
                usos =
                    Csv.leer(usos, "usos").map {
                        UsoTabla(it.getValue("prefijo"), it.getValue("tabla"), it.getValue("descripcion"))
                    },
                parametros =
                    Csv.leer(parametros, "parámetros").map {
                        Parametro(
                            clave = it.getValue("clave"),
                            anio = it.getValue("anio").toInt(),
                            valor = BigDecimal(it.getValue("valor")),
                            fuente = it.getValue("fuente")
                        )
                    }
            )

        fun desdeClasspath(): Tablas {
            fun abrir(ruta: String): Reader =
                requireNotNull(Tablas::class.java.classLoader.getResourceAsStream(ruta)) { "no está en el classpath: $ruta" }
                    .reader(Charsets.UTF_8)
            return cargar(abrir(VALORES_UNITARIOS), abrir(DEPRECIACION), abrir(OBRAS), abrir(USOS), abrir(PARAMETROS))
        }
    }
}
