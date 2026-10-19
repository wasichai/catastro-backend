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
    val obras: List<Obra>
)

// one piso. material and estado in catastro's enum spelling (CONCRETO, MUY BUENO …); the letters are the three
// partidas the selva cuadro prices (the other four categorías do not enter the VU). techoIncluido marks the muros D
// that are drywall including the techo (anexo I.4, llamada 5); null is "not declared", the ladrillo case
data class Construccion(
    val piso: String,
    val areaConstruida: BigDecimal?,
    val anioConstruccion: Int?,
    val material: String?,
    val estado: String?,
    val muros: Char?,
    val techos: Char?,
    val puertas: Char?,
    val techoIncluido: Boolean? = null
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
        val autoavaluo: BigDecimal
    ) : Valuacion

    // motivo is for a person; llave groups predios by what is missing (e.g. "VU_SIN_VALOR:TECHOS:I")
    data class SinValorizar(
        val motivo: String,
        val llave: String
    ) : Valuacion
}

// the autoavalúo of one predio: pure, no clock, no db. the first thing that keeps the predio from a value wins, in the
// order of kamayuk's ValorizacionDelPredio: the ficha's land, the arancel, the year's parameters, every construction's
// cuadro cells, then the uso's depreciation tabla (RT-004), then the obras
object Valorizacion {
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
        // right after every construction's cells (java order) and before anything a piso or an obra declares. a bare lot
        // needs no tabla: the empty one is never read
        val tabla =
            if (i.construcciones.isEmpty() && i.obras.isEmpty()) {
                ""
            } else {
                i.uso?.let { t.tablaPorUso(it) } ?: falta(
                    "TABLA_DE_DEPRECIACION:${i.uso.orEmpty()}",
                    "No hay tabla de depreciación del RNT para el uso «${i.uso ?: "sin uso"}» (D1): sin ella lo construido no se deprecia"
                )
            }

        val construccion =
            i.construcciones
                .zip(unitarios)
                .sumOf { (c, vu) ->
                    val donde = "la construcción del piso ${c.piso}"
                    val areaConstruida = c.areaConstruida ?: falta("AREA_CONSTRUIDA_FALTANTE", "$donde no declara área construida")
                    if (areaConstruida.signum() < 0) falta("AREA_CONSTRUIDA_INVALIDA", "$donde declara un área construida negativa ($areaConstruida)")
                    val conIncremento = incremento?.takeIf { aplicaIncremento(c.piso, it.desde) }?.let { vu.multiply(it.factor) } ?: vu
                    val dep = depreciacion(t, tabla, c.material, c.estado, c.anioConstruccion, i.anio, donde)
                    conIncremento.multiply(dep).multiply(areaConstruida).redondeado()
                }

        val obras =
            i.obras.sumOf { o ->
                val codigo = o.codigoVu.orEmpty()
                val donde = "la obra complementaria $codigo"
                val partida =
                    t.obra(codigo) ?: falta("OBRA_DESCONOCIDA:$codigo", "El cuadro de obras complementarias de la selva no tiene la partida «$codigo»")
                val cantidad = o.cantidad ?: falta("OBRA_CANTIDAD_FALTANTE", "$donde no declara cantidad")
                if (cantidad.signum() < 0) falta("OBRA_CANTIDAD_INVALIDA", "$donde declara una cantidad negativa ($cantidad)")
                // the partida itself names a material (a "muro de concreto"); the ficha's, when given, wins
                val dep = depreciacion(t, tabla, o.material ?: partida.material, o.estado, o.anioConstruccion, i.anio, donde)
                partida.valorUnitario
                    .multiply(cantidad)
                    .multiply(factor)
                    .multiply(dep)
                    .redondeado()
            }

        val suma = terreno + construccion + obras
        // a zero increment leaves the figure as it is (kamayuk: x + x·0 is x, without touching the scale)
        val autoavaluo =
            if (actualizacion.signum() == 0) suma else suma.add(suma.multiply(actualizacion).divide(CIEN)).redondeado()
        return Valuacion.Valorizada(terreno, construccion.redondeado(), obras.redondeado(), autoavaluo)
    }

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
        val donde = "la construcción del piso ${c.piso}"
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
                falta("CATEGORIA_INVALIDA:$partida:$categoria", "$donde declara la categoría $categoria en $partida, fuera de A a J")
            }
            t.valorUnitario(partida, categoria) ?: falta(
                "VU_SIN_VALOR:$partida:$categoria",
                "El cuadro de la selva no publica valor para $partida categoría $categoria ($donde): la celda es «.....», que no es cero"
            )
        }
    }

    // 1 - dep%/100 for the RNT row (tabla, material, estado) at the construction's age
    private fun depreciacion(
        t: Tablas,
        tabla: String,
        material: String?,
        estado: String?,
        anioConstruccion: Int?,
        anio: Int,
        donde: String
    ): BigDecimal {
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
        return BigDecimal.ONE - porcentaje.divide(CIEN)
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
}
