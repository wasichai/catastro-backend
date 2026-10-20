package catastro.valuacion

import catastro.CampoInvalido
import tools.jackson.core.JacksonException
import tools.jackson.databind.DeserializationFeature
import tools.jackson.databind.JsonNode
import tools.jackson.databind.json.JsonMapper
import java.math.BigDecimal

// the body of POST /api/catastro/valuacion: the engine's Insumos in json, plus the codigoMunicipal of a stored ficha
// whose arancel is taken when arancelM2 is absent. read by hand, so every malformed field is a 422 that names its
// path (CampoInvalido) and not spring's 400. a field left out or null stays null: the engine's motivo, never a zero
class PedidoValuacion private constructor(
    val insumos: Insumos,
    val codigoMunicipal: String?
) {
    companion object {
        // as many as one predio can sensibly declare; a guard against a runaway body, not a business rule
        const val MAXIMO = 1000

        private val ANIOS = 1900..2100
        private val LETRAS = 'A'..'J'
        private val CAMPOS =
            setOf("anio", "areaTerreno", "arancelM2", "uso", "esEdificio", "construcciones", "obras", "codigoMunicipal")
        private val CAMPOS_CONSTRUCCION =
            setOf(
                "piso",
                "areaConstruida",
                "anioConstruccion",
                "material",
                "estado",
                "muros",
                "techos",
                "puertas",
                "techoIncluido",
                "clasificacion",
                "seccion"
            )
        private val CAMPOS_OBRA = setOf("codigoVu", "cantidad", "anioConstruccion", "material", "estado")

        // decimals as BigDecimal: 45.50 stays 45.50, never a double
        private val JSON: JsonMapper = JsonMapper.builder().enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS).build()

        fun leer(cuerpo: String?): PedidoValuacion {
            val raiz =
                try {
                    cuerpo?.takeIf { it.isNotBlank() }?.let { JSON.readTree(it) }
                } catch (_: JacksonException) {
                    null
                }
            if (raiz == null || !raiz.isObject) throw CampoInvalido("cuerpo", "debe ser un objeto JSON con los insumos de la valuación")
            val r = Lector(raiz, "", CAMPOS)
            val anio = r.entero("anio") ?: throw CampoInvalido("anio", "es obligatorio")
            if (anio !in ANIOS) throw CampoInvalido("anio", "debe ser un entero entre ${ANIOS.first} y ${ANIOS.last}")
            val insumos =
                Insumos(
                    anio = anio,
                    areaTerreno = r.decimal("areaTerreno"),
                    arancelM2 = r.decimal("arancelM2"),
                    uso = r.texto("uso"),
                    esEdificio = r.logico("esEdificio") ?: false,
                    construcciones = r.lista("construcciones", CAMPOS_CONSTRUCCION).map(::construccion),
                    obras = r.lista("obras", CAMPOS_OBRA).map(::obra)
                )
            return PedidoValuacion(insumos, r.texto("codigoMunicipal"))
        }

        private fun construccion(c: Lector): Construccion {
            val piso = c.texto("piso")?.takeIf { it.isNotBlank() } ?: throw CampoInvalido(c.ruta("piso"), "es obligatorio (\"1\", \"S1\", \"AZ\" …)")
            val seccion = c.entero("seccion")
            if (seccion != null && seccion < 1) throw CampoInvalido(c.ruta("seccion"), "debe ser un entero desde 1")
            return Construccion(
                piso = piso,
                areaConstruida = c.decimal("areaConstruida"),
                anioConstruccion = c.entero("anioConstruccion"),
                material = c.texto("material"),
                estado = c.texto("estado"),
                muros = c.letra("muros"),
                techos = c.letra("techos"),
                puertas = c.letra("puertas"),
                techoIncluido = c.logico("techoIncluido"),
                clasificacion = c.texto("clasificacion"),
                seccion = seccion
            )
        }

        private fun obra(o: Lector): Obra =
            Obra(o.texto("codigoVu"), o.decimal("cantidad"), o.entero("anioConstruccion"), o.texto("material"), o.texto("estado"))
    }

    // one json object at `prefijo`, with the fields it may carry: each getter is null for an absent or null field
    private class Lector(
        private val nodo: JsonNode,
        private val prefijo: String,
        conocidos: Set<String>
    ) {
        init {
            nodo.propertyNames().firstOrNull { it !in conocidos }?.let { throw CampoInvalido(ruta(it), "no existe en este cuerpo") }
        }

        fun ruta(campo: String) = prefijo + campo

        private fun valor(campo: String): JsonNode? = nodo.get(campo)?.takeUnless { it.isNull }

        private fun mal(
            campo: String,
            razon: String
        ): Nothing = throw CampoInvalido(ruta(campo), razon)

        fun texto(campo: String): String? = valor(campo)?.let { if (it.isString) it.asString() else mal(campo, "debe ser un texto") }

        fun decimal(campo: String): BigDecimal? = valor(campo)?.let { if (it.isNumber) it.decimalValue() else mal(campo, "debe ser un número") }

        fun entero(campo: String): Int? =
            valor(campo)?.let { if (it.isIntegralNumber && it.canConvertToInt()) it.intValue() else mal(campo, "debe ser un número entero") }

        fun logico(campo: String): Boolean? = valor(campo)?.let { if (it.isBoolean) it.booleanValue() else mal(campo, "debe ser true o false") }

        // a cuadro's categoría: one capital letter, A to J (the region's cuadro may stop earlier: that is the engine's motivo)
        fun letra(campo: String): Char? =
            texto(campo)?.let {
                it.singleOrNull()?.takeIf { l -> l in LETRAS } ?: mal(campo, "debe ser una sola letra mayúscula de la A a la J")
            }

        fun lista(
            campo: String,
            conocidos: Set<String>
        ): List<Lector> {
            val arreglo = valor(campo) ?: return emptyList()
            if (!arreglo.isArray) mal(campo, "debe ser una lista")
            if (arreglo.size() > MAXIMO) mal(campo, "admite a lo sumo $MAXIMO elementos")
            return arreglo.values().mapIndexed { n, elemento ->
                val ruta = "${ruta(campo)}[$n]"
                if (!elemento.isObject) throw CampoInvalido(ruta, "debe ser un objeto")
                Lector(elemento, "$ruta.", conocidos)
            }
        }
    }
}
