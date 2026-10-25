package catastro.brechas

import org.springframework.http.ContentDisposition
import org.springframework.http.HttpHeaders
import org.springframework.http.HttpStatus
import org.springframework.http.MediaType
import org.springframework.http.ProblemDetail
import org.springframework.http.ResponseEntity
import org.springframework.web.bind.annotation.ExceptionHandler
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RequestParam
import org.springframework.web.bind.annotation.RestController
import wasichai.core.common.FieldViolation
import wasichai.core.common.ValidationException
import wasichai.gis.FeatureCollection
import java.math.BigDecimal
import java.nio.charset.StandardCharsets

// catastro-ui's brechas dashboard: the cortes of srtm's brecha that importar_corte_brecha.py loaded, their fichas with
// the decision of the corte's year, their lotes as GeoJSON in EPSG:4326, and the decisions' inbox. it needs a token
// (401 without one) and READ on brecha_ficha (403 otherwise); POST /decisiones also UPDATE on decision_brecha.
// without `corte` the most recent one by fecha is read, and with no corte at all /panel, /fichas, /lotes and
// /fichas.csv are a 404 {message}. a parameter it does not know, or cannot read, is a 400 that names it
// (errors[].field), as ViasController
@RestController
@RequestMapping("/api/catastro/brechas")
class BrechasController(
    private val brechas: BrechasService
) {
    @GetMapping("/cortes")
    suspend fun cortes(
        @RequestParam params: Map<String, String>
    ): List<CorteResumen> {
        conocidos(params, emptySet())
        return brechas.cortes()
    }

    @GetMapping("/panel")
    suspend fun panel(
        @RequestParam params: Map<String, String>
    ): Panel {
        conocidos(params, setOf("corte"))
        return brechas.panel(corte(params))
    }

    @GetMapping("/fichas")
    suspend fun fichas(
        @RequestParam params: Map<String, String>
    ): Pagina {
        conocidos(params, FILTROS + "orden" + "page" + "size")
        val page = params["page"]?.let { entero("page", it, 0..Int.MAX_VALUE) } ?: 0
        val size = params["size"]?.let { entero("size", it, 1..TAMANO_MAXIMO) } ?: TAMANO
        return brechas.fichas(corte(params), filtro(params), orden(params), page, size)
    }

    @GetMapping("/lotes")
    suspend fun lotes(
        @RequestParam params: Map<String, String>
    ): FeatureCollection {
        // orden is accepted so the table's query can go as is; a map has no order
        conocidos(params, FILTROS + "orden")
        orden(params)
        return brechas.lotes(corte(params), filtro(params))
    }

    @GetMapping("/fichas.csv")
    suspend fun csv(
        @RequestParam params: Map<String, String>
    ): ResponseEntity<ByteArray> {
        conocidos(params, FILTROS + "orden")
        val (clave, cuerpo) = brechas.csv(corte(params), filtro(params), orden(params))
        val disposicion = ContentDisposition.attachment().filename("brechas-$clave.csv").build()
        return ResponseEntity
            .ok()
            .contentType(MediaType("text", "csv", StandardCharsets.UTF_8))
            .header(HttpHeaders.CONTENT_DISPOSITION, disposicion.toString())
            .body(cuerpo)
    }

    @PostMapping("/decisiones")
    suspend fun decisiones(
        @RequestBody cuerpo: Map<String, Any?>
    ): ResultadoDecisiones = brechas.decidir(pedido(cuerpo))

    @ExceptionHandler(BrechaNoEncontrada::class)
    fun noEncontrada(e: BrechaNoEncontrada): ResponseEntity<ProblemDetail> {
        val problema = ProblemDetail.forStatusAndDetail(HttpStatus.NOT_FOUND, e.message ?: BrechasService.SIN_CORTES)
        problema.title = HttpStatus.NOT_FOUND.reasonPhrase
        problema.setProperty("message", e.message)
        return ResponseEntity.status(HttpStatus.NOT_FOUND).contentType(MediaType.APPLICATION_PROBLEM_JSON).body(problema)
    }

    // the body of POST /decisiones, field by field: what is wrong is a 400 that names it
    private fun pedido(cuerpo: Map<String, Any?>): PedidoDecision {
        cuerpo.keys.firstOrNull { it !in CAMPOS_DECISION }?.let { throw invalido(it, "no existe en este cuerpo") }
        val codigos =
            (cuerpo["codigos"] as? List<*>)
                ?.map { (it as? String)?.trim()?.takeIf(String::isNotEmpty) ?: throw invalido("codigos", "debe ser una lista de códigos no vacíos") }
                ?.distinct()
                ?: throw invalido("codigos", "debe ser una lista de códigos municipales")
        if (codigos.isEmpty() || codigos.size > MAXIMO_DECISIONES) throw invalido("codigos", "debe traer entre 1 y $MAXIMO_DECISIONES códigos")
        val anio =
            (cuerpo["anio"] as? Number)?.takeIf { it.toDouble() % 1 == 0.0 }?.toInt()?.takeIf { it in ANIOS }
                ?: throw invalido("anio", "debe ser un entero entre ${ANIOS.first} y ${ANIOS.last}")
        val estado =
            (cuerpo["estado"] as? String)?.takeIf { it in ESTADOS }
                ?: throw invalido("estado", "debe ser uno de ${ESTADOS.joinToString(", ")}")
        val nota = if ("nota" in cuerpo) PedidoDecision.Nota(texto(cuerpo, "nota")) else null
        val motivo = texto(cuerpo, "motivo_descarte")
        if (estado == DESCARTADO && motivo == null) throw invalido("motivo_descarte", "es obligatorio para DESCARTADO")
        return PedidoDecision(codigos, anio, estado, nota, motivo)
    }

    private fun texto(
        cuerpo: Map<String, Any?>,
        campo: String
    ): String? {
        val valor = cuerpo[campo] ?: return null
        return (valor as? String ?: throw invalido(campo, "debe ser texto")).trim().ifEmpty { null }
    }

    private fun conocidos(
        params: Map<String, String>,
        validos: Set<String>
    ) {
        params.keys.firstOrNull { it !in validos }?.let { throw invalido(it, "no existe en este endpoint") }
    }

    private fun corte(params: Map<String, String>): String? = params["corte"]?.let { it.trim().ifEmpty { throw invalido("corte", "no puede ir vacío") } }

    private fun filtro(params: Map<String, String>): Filtro =
        Filtro(
            categorias = lista(params, "categoria", CATEGORIAS),
            confianzas = lista(params, "confianza", CONFIANZAS),
            sector = params["sector"]?.let { it.trim().ifEmpty { throw invalido("sector", "no puede ir vacío") } },
            estados = lista(params, "estado", ESTADOS),
            supera5Uit =
                params["supera_5_uit"]?.let {
                    when (it.trim().lowercase()) {
                        "true" -> true
                        "false" -> false
                        else -> throw invalido("supera_5_uit", "debe ser true o false")
                    }
                },
            minDelta =
                params["min_delta"]?.let {
                    it.trim().toBigDecimalOrNull()?.takeIf { d -> d >= BigDecimal.ZERO }
                        ?: throw invalido("min_delta", "debe ser un número mayor o igual a 0")
                }
        )

    // a comma-separated list of the model's options; an option it does not have is a 400
    private fun lista(
        params: Map<String, String>,
        nombre: String,
        opciones: List<String>
    ): Set<String>? {
        val valor = params[nombre] ?: return null
        val elegidas = valor.split(",").map { it.trim() }.filter { it.isNotEmpty() }
        if (elegidas.isEmpty() || elegidas.any { it !in opciones }) {
            throw invalido(nombre, "debe ser uno o más de ${opciones.joinToString(", ")}, separados por comas")
        }
        return elegidas.toSet()
    }

    private fun orden(params: Map<String, String>): Orden =
        params["orden"]?.let {
            Orden.de(it.trim()) ?: throw invalido("orden", "debe ser ${Orden.entries.joinToString(", ") { o -> o.parametro }}")
        } ?: Orden.DELTA_DESC

    private fun entero(
        nombre: String,
        valor: String,
        rango: IntRange
    ): Int =
        valor.trim().toIntOrNull()?.takeIf { it in rango }
            ?: throw invalido(nombre, "debe ser un entero entre ${rango.first} y ${rango.last}")

    private fun invalido(
        nombre: String,
        razon: String
    ) = ValidationException("El parámetro '$nombre' $razon", listOf(FieldViolation(nombre, razon)))

    private companion object {
        val FILTROS = setOf("corte", "categoria", "confianza", "sector", "estado", "supera_5_uit", "min_delta")
        val CAMPOS_DECISION = setOf("codigos", "anio", "estado", "nota", "motivo_descarte")
        const val TAMANO = 50
        const val TAMANO_MAXIMO = 500
        const val MAXIMO_DECISIONES = 500
        val ANIOS = 1900..2100
    }
}
