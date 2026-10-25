package catastro.valuacion

import catastro.tablas.ClaveParametro
import catastro.tablas.Partida
import catastro.tablas.Tablas
import java.math.BigDecimal
import java.math.RoundingMode

// what the engine needs of one predio and year, already read from the catastro records. nullable where the ficha may
// leave a field blank: a blank is a motivo, never a zero
data class Insumos(
    val anio: Int,
    val areaTerreno: BigDecimal?,
    val arancelM2: BigDecimal?,
    // six-digit srtm usos_predio code; picks the RNT tabla (D1)
    val uso: String?,
    val esEdificio: Boolean,
    val construcciones: List<Construccion>,
    val obras: List<Obra>,
    // predio_catastral.estado_levantamiento (SIN_LEVANTAR, PARCIAL, COMPLETO); SIN_LEVANTAR is the first motivo asked
    val levantamiento: String? = null,
    // URBANO or RUSTICO (model's tipo_predio); read by #26, not yet by this task
    val tipoPredio: String? = null
)

// one piso, or one seccion of a piso. material and estado in catastro's enum spelling (CONCRETO, MUY BUENO …); the
// letters are the three partidas every regional cuadro prices (the other four categorías do not enter the VU).
// techoIncluido marks the muros D that are drywall including the techo (llamada 5 of anexos I.1-I.4); null is "not
// declared", the ladrillo case. clasificacion, an option of the model's enum clasificacion, is the RNT tabla this
// construction depreciates with; null takes the predio's uso tabla (D1). seccion null is 1; piso keeps only the floor
data class Construccion(
    val piso: String,
    val areaConstruida: BigDecimal?,
    val anioConstruccion: Int?,
    val material: String?,
    val estado: String?,
    val muros: Char?,
    val techos: Char?,
    val puertas: Char?,
    val techoIncluido: Boolean? = null,
    val clasificacion: String? = null,
    val seccion: Int? = null
)

// codigoVu is "TIPO DE OBRA|numero", the key of Tablas.obra
data class Obra(
    val codigoVu: String?,
    val cantidad: BigDecimal?,
    val anioConstruccion: Int?,
    val material: String?,
    val estado: String?
)

sealed interface Valuacion {
    // soles, scale 2 HALF_UP. autoavaluo = (terreno + construccion + obras) x (1 + actualización)
    data class Valorizada(
        val terreno: BigDecimal,
        val construccion: BigDecimal,
        val obras: BigDecimal,
        val autoavaluo: BigDecimal,
        // how the engine got to construccion and obras; Σ valor of each list is that total
        val detalle: Detalle = Detalle(emptyList(), emptyList())
    ) : Valuacion

    // motivo is for a person; llave groups predios by what is missing (e.g. "VU_SIN_VALOR:TECHOS:I")
    data class SinValorizar(
        val motivo: String,
        val llave: String
    ) : Valuacion
}

// the steps of a valued predio, in the order of its construcciones and obras
data class Detalle(
    val pisos: List<DetallePiso>,
    val obras: List<DetalleObra>
)

// one construction: valorUnitario is the cuadro's Σ of its partidas; incremento the amount the edificio's 5 % adds
// (0 below its floor); valorUnitarioDepreciado = (valorUnitario + incremento) x (1 - porcentajeDepreciacion / 100), to
// the céntimo where the region rounds; valor = valorUnitarioDepreciado x areaConstruida, 2 decimals
data class DetallePiso(
    val piso: String,
    val seccion: Int?,
    val areaConstruida: BigDecimal,
    val valorUnitario: BigDecimal,
    val incremento: BigDecimal,
    val tablaDepreciacion: String,
    val antiguedad: Int,
    val porcentajeDepreciacion: BigDecimal,
    val valorUnitarioDepreciado: BigDecimal,
    val valor: BigDecimal
)

// one obra: valor = valorUnitario x cantidad x factorOficializacion x (1 - porcentajeDepreciacion / 100), 2 decimals
data class DetalleObra(
    val codigoVu: String,
    val cantidad: BigDecimal,
    val valorUnitario: BigDecimal,
    val factorOficializacion: BigDecimal,
    val tablaDepreciacion: String,
    val antiguedad: Int,
    val porcentajeDepreciacion: BigDecimal,
    val valor: BigDecimal
)

// the autoavalúo of one predio: pure, no clock, no db. the first thing that keeps the predio from a value wins, in the
// order of kamayuk's ValorizacionDelPredio: the ficha's land, the arancel, the year's parameters, every construction's
// cuadro cells, then the depreciation tablas (the uso's, RT-004, then each construction's clasificación), then the obras
object Valorizacion {
    // the model's enum clasificacion (srtm-backend's same four options) to the RNT's tables of anexo I, by their titles
    val TABLA_POR_CLASIFICACION: Map<String, String> =
        linkedMapOf(
            "CASA HABITACION Y DEPARTAMENTOS PARA VIVIENDA" to "01",
            "TIENDAS DEPOSITOS CENTROS DE RECREACION CLUBES E INSTITUCIONES" to "02",
            "EDIFICIO-OFICINAS" to "03",
            "CLINICAS HOSPITALES CINES INDUSTRIAS COLEGIOS TALLERES" to "04"
        )

    // predio_catastral.estado_levantamiento = SIN_LEVANTAR: a ficha not yet surveyed has no insumos worth asking for
    const val SIN_LEVANTAMIENTO = "SIN_LEVANTAMIENTO"

    private const val ESCALA = 2
    private const val MUROS_SIN_TECHOS = 'A'
    private const val MUROS_DRYWALL = 'D'
    private val CIEN = BigDecimal(100)

    fun valorizar(
        i: Insumos,
        t: Tablas
    ): Valuacion =
        try {
            calcular(i, t)
        } catch (falta: Falta) {
            Valuacion.SinValorizar(falta.motivo, falta.llave)
        }

    // a missing datum surfaces from deep in the arithmetic; unwinding to valorizar keeps each step a straight line
    private class Falta(
        val motivo: String,
        val llave: String
    ) : RuntimeException(motivo, null, false, false)

    private fun falta(
        llave: String,
        motivo: String
    ): Nothing = throw Falta(motivo, llave)

    private fun calcular(
        i: Insumos,
        t: Tablas
    ): Valuacion.Valorizada {
        // checked first: an unsurveyed ficha has nothing worth asking for, not even its área
        if (i.levantamiento == "SIN_LEVANTAR") falta(SIN_LEVANTAMIENTO, SIN_LEVANTAMIENTO)
        val area = i.areaTerreno?.takeIf { it.signum() > 0 } ?: falta("AREA_TERRENO_FALTANTE", "El predio no tiene área de terreno")
        val arancel =
            i.arancelM2?.takeIf { it.signum() > 0 }
                ?: falta("ARANCEL_FALTANTE", "La vía del predio no tiene arancel por m² para ${i.anio}: sin él no hay valor de terreno")
        val actualizacion = parametro(t, ClaveParametro.PORCENTAJE_ACTUALIZACION, i.anio)
        // asked only when they can apply: a bare lot does not need the oficialización factor
        val incremento = incrementoPorPiso(i, t)
        val factor = if (i.obras.isEmpty()) BigDecimal.ONE else parametro(t, ClaveParametro.FACTOR_OFICIALIZACION, i.anio)

        val terreno = area.multiply(arancel).redondeado()

        val unitarios = i.construcciones.map { valorUnitario(it, t) }
        // right after every construction's cells (java order) and before anything a piso or an obra declares. the uso's
        // tabla is asked only when something depreciates with it: an obra, or a construction without a clasificación (a
        // bare lot needs none, and the empty one is never read)
        val tabla =
            if (i.construcciones.all { it.clasificacion != null } && i.obras.isEmpty()) {
                ""
            } else {
                i.uso?.let { t.tablaPorUso(it) } ?: falta(
                    "TABLA_DE_DEPRECIACION:${i.uso.orEmpty()}",
                    "No hay tabla de depreciación del RNT para el uso «${i.uso ?: "sin uso"}» (D1): sin ella lo construido no se deprecia"
                )
            }
        val tablas = i.construcciones.map { c -> c.clasificacion?.let { tablaPorClasificacion(it, donde(c)) } ?: tabla }

        val pisos =
            i.construcciones.indices
                .map { n ->
                    val c = i.construcciones[n]
                    val vu = unitarios[n]
                    val donde = donde(c)
                    val areaConstruida = c.areaConstruida ?: falta("AREA_CONSTRUIDA_FALTANTE", "$donde no declara área construida")
                    if (areaConstruida.signum() < 0) falta("AREA_CONSTRUIDA_INVALIDA", "$donde declara un área construida negativa ($areaConstruida)")
                    val conIncremento =
                        incremento?.takeIf { aplicaIncremento(c.piso, it.desde) }?.let { vu.multiply(it.factor).alCentimo(t) } ?: vu
                    val dep = depreciacion(t, tablas[n], c.material, c.estado, c.anioConstruccion, i.anio, donde)
                    val depreciado = conIncremento.multiply(dep.factor).alCentimo(t)
                    DetallePiso(
                        piso = c.piso,
                        seccion = c.seccion,
                        areaConstruida = areaConstruida,
                        valorUnitario = vu,
                        incremento = conIncremento - vu,
                        tablaDepreciacion = tablas[n],
                        antiguedad = dep.antiguedad,
                        porcentajeDepreciacion = dep.porcentaje,
                        valorUnitarioDepreciado = depreciado,
                        valor = depreciado.multiply(areaConstruida).redondeado()
                    )
                }
        val construccion = pisos.sumOf { it.valor }

        // a region whose obras cuadro is not shipped cannot value an obra: skipping it would undervalue the predio
        if (i.obras.isNotEmpty() && t.obras == null) {
            falta(
                "OBRAS_SIN_CUADRO:${t.region}",
                "No hay cuadro de obras complementarias de la ${t.region.nombre} (${t.region.obras}): el predio declara obras y sin él no se valorizan"
            )
        }
        val detalleObras =
            i.obras.map { o ->
                val codigo = o.codigoVu.orEmpty()
                val donde = "la obra complementaria $codigo"
                val partida =
                    t.obra(codigo) ?: falta(
                        "OBRA_DESCONOCIDA:$codigo",
                        "El cuadro de obras complementarias de la ${t.region.nombre} no tiene la partida «$codigo»"
                    )
                val cantidad = o.cantidad ?: falta("OBRA_CANTIDAD_FALTANTE", "$donde no declara cantidad")
                if (cantidad.signum() < 0) falta("OBRA_CANTIDAD_INVALIDA", "$donde declara una cantidad negativa ($cantidad)")
                // the partida itself names a material (a "muro de concreto"); the ficha's, when given, wins
                val dep = depreciacion(t, tabla, o.material ?: partida.material, o.estado, o.anioConstruccion, i.anio, donde)
                DetalleObra(
                    codigoVu = codigo,
                    cantidad = cantidad,
                    valorUnitario = partida.valorUnitario,
                    factorOficializacion = factor,
                    tablaDepreciacion = tabla,
                    antiguedad = dep.antiguedad,
                    porcentajeDepreciacion = dep.porcentaje,
                    valor =
                        partida.valorUnitario
                            .multiply(cantidad)
                            .multiply(factor)
                            .multiply(dep.factor)
                            .redondeado()
                )
            }
        val obras = detalleObras.sumOf { it.valor }

        val suma = terreno + construccion + obras
        // a zero increment leaves the figure as it is (kamayuk: x + x·0 is x, without touching the scale)
        val autoavaluo =
            if (actualizacion.signum() == 0) suma else suma.add(suma.multiply(actualizacion).divide(CIEN)).redondeado()
        return Valuacion.Valorizada(terreno, construccion.redondeado(), obras.redondeado(), autoavaluo, Detalle(pisos, detalleObras))
    }

    private fun donde(c: Construccion): String = "la construcción del piso ${c.piso}" + (c.seccion?.takeIf { it != 1 }?.let { ", sección $it" } ?: "")

    private fun tablaPorClasificacion(
        clasificacion: String,
        donde: String
    ): String =
        TABLA_POR_CLASIFICACION[clasificacion.trim().uppercase()] ?: falta(
            "CLASIFICACION_DESCONOCIDA:$clasificacion",
            "$donde declara la clasificación «$clasificacion», que no es ninguna de las tablas de depreciación 01 a 04 del RNT"
        )

    private fun parametro(
        t: Tablas,
        clave: String,
        anio: Int
    ): BigDecimal =
        t.parametro(clave, anio)
            ?: falta("PARAMETRO_FALTANTE:$clave:$anio", "Las tablas no traen el parámetro $clave para $anio")

    private class Incremento(
        val desde: Int,
        val factor: BigDecimal
    )

    // the cuadro's note «EN EDIFICIOS AUMENTAR EL VALOR POR M2 EN 5 % A PARTIR DEL 5° PISO»: edificios only, once
    // (not compounding per floor), before depreciation
    private fun incrementoPorPiso(
        i: Insumos,
        t: Tablas
    ): Incremento? {
        if (!i.esEdificio || i.construcciones.isEmpty()) return null
        val desde = parametro(t, ClaveParametro.INCREMENTO_PISO_DESDE, i.anio).intValueExact()
        val porcentaje = parametro(t, ClaveParametro.INCREMENTO_PISO_PORCENTAJE, i.anio)
        return Incremento(desde, BigDecimal.ONE + porcentaje.divide(CIEN))
    }

    // "S1" (sótano), "AZ" and the like carry no floor number, so they never reach the increment
    private fun aplicaIncremento(
        piso: String,
        desde: Int
    ): Boolean = piso.trim().toIntOrNull()?.let { it >= desde } ?: false

    // D4: muros y columnas + techos + puertas y ventanas. a "....." cell is no value (D5), not zero. muros A
    // (estructuras laminares curvadas, cimentación y techo en una sola armadura) leaves techos out: «PARA ESTE CASO NO SE
    // CONSIDERA LOS VALORES DE LA COLUMNA N° 2», so its letter is neither asked nor added. muros D is the same only for
    // «DRYWALL O SIMILAR INCLUYE TECHO (5)», which the ficha flags with techoIncluido (the ladrillo, also D, keeps its
    // techos); the flag on any other muros is a capture error, not something to guess
    private fun valorUnitario(
        c: Construccion,
        t: Tablas
    ): BigDecimal {
        val donde = donde(c)
        if (c.anioConstruccion == null) {
            falta("ANIO_CONSTRUCCION_FALTANTE", "$donde no declara año de construcción: sin él no hay antigüedad con que depreciar")
        }
        if (c.techoIncluido == true && c.muros != null && c.muros != MUROS_SIN_TECHOS && c.muros != MUROS_DRYWALL) {
            falta(
                "TECHO_INCLUIDO_INVALIDO:${c.muros}",
                "$donde marca el techo incluido en los muros, pero sus muros son de categoría ${c.muros}: " +
                    "solo la A y la D (drywall) lo incluyen según el cuadro"
            )
        }
        val sinTecho = c.muros == MUROS_SIN_TECHOS || (c.muros == MUROS_DRYWALL && c.techoIncluido == true)
        val letras =
            mapOf(Partida.MUROS_COLUMNAS to c.muros, Partida.TECHOS to c.techos, Partida.PUERTAS_VENTANAS to c.puertas)
                .filterKeys { !(it == Partida.TECHOS && sinTecho) }
        return letras.entries.sumOf { (partida, letra) ->
            val categoria =
                letra?.toString() ?: falta(
                    "CATEGORIA_FALTANTE:$partida",
                    "$donde no declara la categoría de $partida; una categoría sin declarar no es «sin techo» ni «sin puertas»"
                )
            if (categoria !in t.categorias) {
                falta(
                    "CATEGORIA_INVALIDA:$partida:$categoria",
                    "$donde declara la categoría $categoria en $partida, fuera de ${t.categorias.first()} a ${t.categorias.last()} (cuadro de la ${t.region.nombre})"
                )
            }
            t.valorUnitario(partida, categoria) ?: falta(
                "VU_SIN_VALOR:$partida:$categoria",
                "El cuadro de la ${t.region.nombre} no publica valor para $partida categoría $categoria ($donde): la celda es «.....», que no es cero"
            )
        }
    }

    // the RNT row's percentage at an age; factor = 1 - porcentaje/100 is what multiplies the VU
    private class Depreciacion(
        val antiguedad: Int,
        val porcentaje: BigDecimal
    ) {
        val factor: BigDecimal get() = BigDecimal.ONE - porcentaje.divide(CIEN)
    }

    // the RNT row (tabla, material, estado) at the construction's age
    private fun depreciacion(
        t: Tablas,
        tabla: String,
        material: String?,
        estado: String?,
        anioConstruccion: Int?,
        anio: Int,
        donde: String
    ): Depreciacion {
        // fires only for obras: valorUnitario already asked every construcción for its year
        val construido = anioConstruccion ?: falta("ANIO_CONSTRUCCION_FALTANTE", "$donde no declara año de construcción")
        val antiguedad = anio - construido
        if (antiguedad < 0) falta("ANTIGUEDAD_NEGATIVA", "$donde declara el año $construido, posterior a $anio")
        val materialRnt = materialRnt(material ?: falta("MATERIAL_FALTANTE", "$donde no declara material"))
        val estadoDeclarado = estado ?: falta("ESTADO_FALTANTE", "$donde no declara estado de conservación")
        val estadoRnt =
            estadoRnt(estadoDeclarado)
                ?: falta("ESTADO_DESCONOCIDO:$estadoDeclarado", "$donde declara el estado «$estadoDeclarado», que el RNT no conoce")
        val serie =
            try {
                t.serieDepreciacion(tabla, materialRnt, estadoRnt)
            } catch (_: IllegalArgumentException) {
                falta(
                    "DEPRECIACION_FALTANTE:$tabla:$materialRnt:$estadoRnt",
                    "El RNT no trae la fila de la tabla $tabla, $materialRnt, $estadoRnt ($donde)"
                )
            }
        // D3: a '*' cell takes the last percentage its row publishes
        val porcentaje = t.depreciacion(tabla, materialRnt, estadoRnt, antiguedad) ?: serie.last().porcentaje
        return Depreciacion(antiguedad, porcentaje)
    }

    // D2: the RNT has three columns; everything that is neither concreto nor ladrillo goes to the light one
    internal fun materialRnt(material: String): String =
        when (material.trim().uppercase()) {
            "CONCRETO" -> "Concreto"
            "LADRILLO" -> "Ladrillo"
            else -> "Liviano/Adobe"
        }

    // D3: the RNT stops at Malo, so MUY MALO depreciates as Malo
    internal fun estadoRnt(estado: String): String? =
        when (estado.trim().uppercase()) {
            "MUY BUENO" -> "Muy Bueno"
            "BUENO" -> "Bueno"
            "REGULAR" -> "Regular"
            "MALO", "MUY MALO" -> "Malo"
            else -> null
        }

    private fun BigDecimal.redondeado(): BigDecimal = setScale(ESCALA, RoundingMode.HALF_UP)

    // a step of a construction's VU: to the céntimo where the region rounds it (Region.redondeaValorUnitario), unchanged
    // elsewhere. round(VU x 1.05) is the padrón's VU + round(VU x 5 %) because the cuadro's cells, and so VU, are
    // céntimos. the obras are not touched: no padrón has shown how a region rounds them
    private fun BigDecimal.alCentimo(t: Tablas): BigDecimal = if (t.region.redondeaValorUnitario) redondeado() else this
}
