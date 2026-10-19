package catastro.tablas

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import java.math.BigDecimal
import java.security.MessageDigest

// the shipped tables against their sources. every expected figure is read from the cited document line, never typed
// from memory: N = /Users/jorge/IdeaProjects/normativa/docs/10-negocio/valores-normativos
class TablasTest {
    private val tablas = Tablas.desdeClasspath()

    private fun bd(valor: String) = BigDecimal(valor)

    private fun recurso(ruta: String) =
        Tablas::class.java.classLoader
            .getResource(ruta)!!
            .readText()

    // the file minus its leading '#' lines, i.e. the rows as the source has them
    private fun sha256SinComentarios(ruta: String): String {
        val filas = recurso(ruta).lines().dropWhile { it.startsWith("#") }.joinToString("\n")
        return MessageDigest.getInstance("SHA-256").digest(filas.toByteArray()).joinToString("") { "%02x".format(it) }
    }

    @Test
    fun `valores unitarios - 30 celdas, 3 partidas por 10 categorías A a J`() {
        assertEquals(30, tablas.valoresUnitarios.size)
        assertEquals(('A'..'J').map { it.toString() }, tablas.categorias)
    }

    @Test
    fun `valores unitarios - celdas del anexo I_4`() {
        // N/valores-unitarios-2026.md:266, fila A: 995.50 | 509.83 | 421.72
        assertEquals(bd("995.50"), tablas.valorUnitario(Partida.MUROS_COLUMNAS, "A"))
        assertEquals(bd("509.83"), tablas.valorUnitario(Partida.TECHOS, "A"))
        assertEquals(bd("421.72"), tablas.valorUnitario(Partida.PUERTAS_VENTANAS, "A"))
        // N/valores-unitarios-2026.md:269, fila D: 378.67 | 231.25 | 166.76
        assertEquals(bd("231.25"), tablas.valorUnitario(Partida.TECHOS, "D"))
        // N/valores-unitarios-2026.md:275, fila J: 16.43 | ..... | .....
        assertEquals(bd("16.43"), tablas.valorUnitario(Partida.MUROS_COLUMNAS, "J"))
    }

    @Test
    fun `valores unitarios - el cuadro entero de la selva`() {
        // N/valores-unitarios-2026.md:266-275, anexo I.4 fila por fila: muros y columnas | techos | puertas y ventanas.
        // "-" is a "....." cell
        val cuadro =
            """
            A 995.50 509.83 421.72
            B 679.21 360.15 334.51
            C 489.75 265.25 248.79
            D 378.67 231.25 166.76
            E 300.68 168.37 108.28
            F 237.10 77.41 88.32
            G 205.37 60.91 52.11
            H 102.68 0.00 26.06
            I 41.08 - 0.00
            J 16.43 - -
            """.trimIndent()
        val cargado =
            tablas.categorias.joinToString("\n") { categoria ->
                (listOf(categoria) + Partida.entries.map { tablas.valorUnitario(it, categoria)?.toPlainString() ?: "-" }).joinToString(" ")
            }
        assertEquals(cuadro, cargado)
    }

    @Test
    fun `valores unitarios - los puntos no tienen valor, el 0_00 es cero`() {
        // N/valores-unitarios-2026.md:273-275: H techos 0.00, I techos ....., I puertas 0.00, J techos y puertas .....
        assertEquals(0, tablas.valorUnitario(Partida.TECHOS, "H")!!.compareTo(BigDecimal.ZERO))
        assertEquals(0, tablas.valorUnitario(Partida.PUERTAS_VENTANAS, "I")!!.compareTo(BigDecimal.ZERO))
        assertNull(tablas.valorUnitario(Partida.TECHOS, "I"))
        assertNull(tablas.valorUnitario(Partida.TECHOS, "J"))
        assertNull(tablas.valorUnitario(Partida.PUERTAS_VENTANAS, "J"))
        // exactly those three cells are dots (N/valores-unitarios-2026.md:182, I.4: I-techos, J-techos, J-puertas)
        assertEquals(3, tablas.valoresUnitarios.count { it.valorM2 == null })
    }

    @Test
    fun `valores unitarios - categoría fuera del cuadro es un error`() {
        assertThrows<IllegalArgumentException> { tablas.valorUnitario(Partida.TECHOS, "K") }
    }

    @Test
    fun `depreciación - copia exacta de depreciacion_csv, 492 filas`() {
        assertEquals(492, tablas.depreciaciones.size)
        // sha256 that N/fuentes/depreciacion-rnt-2016/README.md publishes for its depreciacion.csv
        assertEquals("5e919b370b10473570187c33edefd15a6dd372653db5d77b25fc51e31deb6be6", sha256SinComentarios(Tablas.DEPRECIACION))
    }

    @Test
    fun `depreciación - tramos en sus bordes`() {
        // N/depreciacion.md:43, tabla 01 Concreto Muy Bueno: 0 0 3 6 9 12 15 18 21 24 27
        val porcentaje = { anios: Int -> tablas.depreciacion("01", "Concreto", "Muy Bueno", anios) }
        assertEquals(bd("0"), porcentaje(0))
        assertEquals(bd("0"), porcentaje(5))
        assertEquals(bd("0"), porcentaje(10))
        assertEquals(bd("3"), porcentaje(11))
        assertEquals(bd("3"), porcentaje(15))
        assertEquals(bd("24"), porcentaje(50))
        assertEquals(bd("27"), porcentaje(51))
        assertEquals(bd("27"), porcentaje(120))
        // N/depreciacion.md:104, tabla 04 Liviano/Adobe Regular, hasta 25: 52
        assertEquals(bd("52"), tablas.depreciacion("04", "Liviano/Adobe", "Regular", 21))
        assertEquals(bd("52"), tablas.depreciacion("04", "Liviano/Adobe", "Regular", 25))
    }

    @Test
    fun `depreciación - una celda asterisco no tiene valor`() {
        // N/depreciacion.md:97, tabla 04 Concreto Malo: … 77 | 80 | * | *
        assertEquals(bd("80"), tablas.depreciacion("04", "Concreto", "Malo", 45))
        assertNull(tablas.depreciacion("04", "Concreto", "Malo", 46))
        assertNull(tablas.depreciacion("04", "Concreto", "Malo", 51))
        // N/depreciacion.md:54, tabla 01 Liviano/Adobe Malo: 65 70 75 80 85 90 * * * * *
        assertEquals(bd("90"), tablas.depreciacion("01", "Liviano/Adobe", "Malo", 30))
        assertNull(tablas.depreciacion("01", "Liviano/Adobe", "Malo", 31))
        assertEquals(bd("90"), tablas.serieDepreciacion("01", "Liviano/Adobe", "Malo").last().porcentaje)
    }

    @Test
    fun `depreciación - vocabulario ajeno al RNT y edad negativa son errores`() {
        assertThrows<IllegalArgumentException> { tablas.depreciacion("01", "CONCRETO", "Muy Bueno", 5) }
        assertThrows<IllegalArgumentException> { tablas.depreciacion("01", "Concreto", "Muy Malo", 5) }
        assertThrows<IllegalArgumentException> { tablas.depreciacion("05", "Concreto", "Bueno", 5) }
        assertThrows<IllegalArgumentException> { tablas.depreciacion("01", "Concreto", "Bueno", -1) }
    }

    @Test
    fun `obras - copia exacta de obras_complementarias_csv de srtm, 96 partidas`() {
        assertEquals(96, tablas.obras.size)
        // sha256 of srtm-backend/model/data/obras_complementarias.csv when this table was copied
        assertEquals("787f5868dd8d57a2a7e6f0e15048e61d681c102842847fc6c029ee2cdbaf2731", sha256SinComentarios(Tablas.OBRAS))
    }

    @Test
    fun `obras - partidas por tipo de obra y número`() {
        // srtm-backend/model/data/obras_complementarias.csv:2
        val muro = tablas.obra("MUROS PERIMETRICOS O CERCOS|1")!!
        assertEquals(bd("457.72"), muro.valorUnitario)
        assertEquals("M2", muro.unidadMedida)
        assertEquals("CONCRETO", muro.material)
        // srtm-backend/model/data/obras_complementarias.csv:19, no material
        val tanque = tablas.obra("TANQUES ELEVADOS|18")!!
        assertEquals(bd("1452.77"), tanque.valorUnitario)
        assertEquals("M3", tanque.unidadMedida)
        assertNull(tanque.material)
        // srtm-backend/model/data/obras_complementarias.csv:89, a quoted description with commas and doubled quotes
        val cerco = tablas.obra("CERCOS METALICOS|88")!!
        assertEquals("CERCO METÁLICO; TUBO CIRCULAR 2\" DIAM., ANG. 1\", MALLA 2\" X 2\", ALAM. #8", cerco.descripcion)
        assertEquals(bd("244.43"), cerco.valorUnitario)
        assertNull(tablas.obra("CERCOS METALICOS|3"))
    }

    @Test
    fun `usos - gana el prefijo más largo`() {
        assertEquals("01", tablas.tablaPorUso("010101"))
        assertEquals("02", tablas.tablaPorUso("020301"))
        assertEquals("03", tablas.tablaPorUso("020401"))
        assertEquals("04", tablas.tablaPorUso("020507"))
        assertEquals("02", tablas.tablaPorUso("020501"))
        assertEquals("04", tablas.tablaPorUso("030201"))
        assertEquals("02", tablas.tablaPorUso("040107"))
        assertEquals("04", tablas.tablaPorUso("040208"))
        assertEquals("04", tablas.tablaPorUso("050101"))
        assertEquals("04", tablas.tablaPorUso("050202"))
        assertEquals("03", tablas.tablaPorUso("100203"))
        assertEquals("02", tablas.tablaPorUso("100204"))
        // D1 (2026-10-20): institucional va a la 02 («instituciones»), salvo oficinas públicas (03) e instrucción (04)
        assertEquals("02", tablas.tablaPorUso("060201"))
        assertEquals("03", tablas.tablaPorUso("060101"))
        assertEquals("04", tablas.tablaPorUso("060203"))
        assertEquals("04", tablas.tablaPorUso("040205"))
        assertEquals("02", tablas.tablaPorUso("050209"))
        // códigos de solo clase que el padrón importa
        assertEquals("01", tablas.tablaPorUso("090000"))
        assertEquals("01", tablas.tablaPorUso("100000"))
        assertEquals("01", tablas.tablaPorUso("100400"))
        assertNull(tablas.tablaPorUso("990000"))
        assertNull(tablas.tablaPorUso(""))
    }

    @Test
    fun `parámetros 2026`() {
        // N/obras-complementarias-y-oficializacion-2026.md:152, «FACTOR DE OFICIALIZACIÓN Fo = 0,68»
        assertEquals(bd("0.68"), tablas.parametro(ClaveParametro.FACTOR_OFICIALIZACION, 2026))
        // N/predial-porcentaje-de-actualizacion.md:259, «no hay actualización que aplicar: 0»
        assertEquals(bd("0"), tablas.parametro(ClaveParametro.PORCENTAJE_ACTUALIZACION, 2026))
        // N/valores-unitarios-2026.md:111, «AUMENTAR EL VALOR POR M2 EN 5 % A PARTIR DEL 5° PISO»
        assertEquals(bd("5"), tablas.parametro(ClaveParametro.INCREMENTO_PISO_DESDE, 2026))
        assertEquals(bd("5"), tablas.parametro(ClaveParametro.INCREMENTO_PISO_PORCENTAJE, 2026))
        assertNull(tablas.parametro(ClaveParametro.FACTOR_OFICIALIZACION, 2025))
    }

    @Test
    fun `cargar - un archivo con fin de línea crlf se lee igual`() {
        val vu = "# fuente\r\npartida,categoria,valor_m2,fuente\r\nMUROS_COLUMNAS,A,1,x\r\nTECHOS,A,2,x\r\nPUERTAS_VENTANAS,A,,x\r\n"
        // porcentaje and descripcion are last columns: with the '\r' kept their header names would not match
        val depreciacion = "tabla,material,estado_conservacion,antiguedad_hasta,porcentaje\r\n01,Concreto,Bueno,5,3\r\n"
        val tablas =
            Tablas.cargar(
                vu.reader(),
                depreciacion.reader(),
                "tipo_obra,numero,descripcion,unidad_medida,material,valor_unitario\r\n".reader(),
                "prefijo,tabla,descripcion\r\n01,01,x\r\n".reader(),
                "clave,anio,valor,fuente\r\n".reader()
            )
        assertEquals(bd("3"), tablas.depreciacion("01", "Concreto", "Bueno", 4))
        assertEquals("x", tablas.usos.single().descripcion)
        assertNull(tablas.valorUnitario(Partida.PUERTAS_VENTANAS, "A"))
    }

    @Test
    fun `cargar - una tabla mal formada falla al cargar`() {
        val vacia = "tabla,material,estado_conservacion,antiguedad_hasta,porcentaje\n"
        val obras = "tipo_obra,numero,descripcion,unidad_medida,material,valor_unitario\n"
        val usos = "prefijo,tabla,descripcion\n"
        val parametros = "clave,anio,valor,fuente\n"
        // one cell short of the 3 partidas x categorías grid
        val vu = "partida,categoria,valor_m2,fuente\nMUROS_COLUMNAS,A,1,x\nTECHOS,A,1,x\n"
        assertThrows<IllegalArgumentException> {
            Tablas.cargar(vu.reader(), vacia.reader(), obras.reader(), usos.reader(), parametros.reader())
        }
        // a uso pointing at a tabla the RNT does not have
        val vuCompleto = "partida,categoria,valor_m2,fuente\nMUROS_COLUMNAS,A,1,x\nTECHOS,A,1,x\nPUERTAS_VENTANAS,A,,x\n"
        assertThrows<IllegalArgumentException> {
            Tablas.cargar(vuCompleto.reader(), vacia.reader(), obras.reader(), "${usos}01,01,x\n".reader(), parametros.reader())
        }
        val tablas = Tablas.cargar(vuCompleto.reader(), vacia.reader(), obras.reader(), usos.reader(), parametros.reader())
        assertNull(tablas.valorUnitario(Partida.PUERTAS_VENTANAS, "A"))
    }
}
