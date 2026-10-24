package catastro.tablas

import java.io.Reader
import java.math.BigDecimal
import java.util.concurrent.ConcurrentHashMap

// the regions of the R.M. 277-2025-VIVIENDA anexos (I.1-I.4, III.1-III.4) that have tables here. an organization's
// region is its configuracion_catastro record; there is no default. adding SIERRA or LIMA_CALLAO: an option of the
// model's region_catastro enum, a constant here and its two files. nombre is how the motivos call its cuadro.
// redondeaValorUnitario: a construction's VU is rounded to the céntimo (HALF_UP) after the edificio's 5 % and again
// after depreciation, before it is multiplied by the área. the costa does it as the padrón de Ica does
// (PADRON_CONSTRUCCION.xlsx: incremento_5 and valor_total_nivel; práctica del padrón de Ica, decisión del usuario
// 2026-10-20); the selva keeps kamayuk's unrounded product, the one Perené's figures were checked against
enum class Region(
    val nombre: String,
    val redondeaValorUnitario: Boolean
) {
    COSTA("costa", redondeaValorUnitario = true),
    SELVA("selva", redondeaValorUnitario = false);

    // file names: valores-unitarios-<region>-2026.csv, obras-complementarias-<region>-2026.csv (LIMA_CALLAO -> lima-callao)
    private val archivo = name.lowercase().replace('_', '-')
    val valoresUnitarios = "tablas/valores-unitarios-$archivo-2026.csv"
    val obras = "tablas/obras-complementarias-$archivo-2026.csv"
}

// the three partidas of every regional cuadro (anexos I.1-I.4); a construction's VU is their sum (D4, in the engine)
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

// the normative tables of one region, loaded once and never changed: its own VU cuadro and obras, the national RNT,
// usos and parámetros. lookups speak the sources' own vocabulary (RNT material and estado as written in
// depreciacion-rnt-2016.csv); mapping catastro's enums onto it (D2, D3) is the engine's job. obras null: the region's
// obras cuadro is not shipped (the engine then refuses to value an obra rather than skip it)
class Tablas(
    val region: Region,
    val valoresUnitarios: List<CeldaValorUnitario>,
    val depreciaciones: List<TramoDepreciacion>,
    val obras: List<ObraComplementaria>?,
    val usos: List<UsoTabla>,
    val parametros: List<Parametro>
) {
    private val vu = valoresUnitarios.associateBy { it.partida to it.categoria }
    private val series = depreciaciones.groupBy { Triple(it.tabla, it.material, it.estadoConservacion) }
    private val obrasPorCodigo = obras.orEmpty().associateBy { it.codigo }
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
        require(obrasPorCodigo.size == obras.orEmpty().size) { "obras: código repetido" }
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
        require(categoria in categorias) { "categoría $categoria no está en el cuadro de la ${region.nombre} (${categorias.joinToString("")})" }
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

    // codigo as "TIPO DE OBRA|numero"; null when the cuadro has no such partida, or the region has no obras cuadro
    fun obra(codigo: String): ObraComplementaria? = obrasPorCodigo[codigo]

    fun parametro(
        clave: String,
        anio: Int
    ): BigDecimal? = parametrosPorClave[clave to anio]?.valor

    companion object {
        const val DEPRECIACION = "tablas/depreciacion-rnt-2016.csv"
        const val USOS = "tablas/uso-tabla-depreciacion.csv"
        const val PARAMETROS = "tablas/parametros.csv"

        private val cargadas = ConcurrentHashMap<Region, Tablas>()

        fun cargar(
            region: Region,
            valoresUnitarios: Reader,
            depreciacion: Reader,
            obras: Reader?,
            usos: Reader,
            parametros: Reader
        ): Tablas =
            Tablas(
                region = region,
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
                    obras?.let { reader ->
                        Csv.leer(reader, "obras").map {
                            ObraComplementaria(
                                codigo = "${it.getValue("tipo_obra")}|${it.getValue("numero")}",
                                tipoObra = it.getValue("tipo_obra"),
                                numero = it.getValue("numero").toInt(),
                                descripcion = it.getValue("descripcion"),
                                unidadMedida = it.getValue("unidad_medida"),
                                material = it.getValue("material").ifEmpty { null },
                                valorUnitario = BigDecimal(it.getValue("valor_unitario"))
                            )
                        }
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

        // the region's tables from the classpath, read once per region. a missing obras file is a region without that
        // cuadro (null); any other missing or malformed file throws
        fun de(region: Region): Tablas = cargadas.computeIfAbsent(region, ::desdeClasspath)

        private fun desdeClasspath(region: Region): Tablas {
            fun talVez(ruta: String): Reader? =
                Tablas::class.java.classLoader
                    .getResourceAsStream(ruta)
                    ?.reader(Charsets.UTF_8)

            fun abrir(ruta: String): Reader = requireNotNull(talVez(ruta)) { "no está en el classpath: $ruta" }
            return cargar(
                region,
                abrir(region.valoresUnitarios),
                abrir(DEPRECIACION),
                talVez(region.obras),
                abrir(USOS),
                abrir(PARAMETROS)
            )
        }
    }
}
