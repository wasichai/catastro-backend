package catastro.valuacion

import catastro.tablas.ClaveParametro
import catastro.tablas.Region
import catastro.tablas.Tablas
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import tools.jackson.databind.json.JsonMapper
import java.io.File
import java.math.BigDecimal

// the engine against the shipped tables. every figure is worked by hand in the comment above its assertion, with the
// cells read from src/main/resources/tablas (VU = anexo I.4 selva, dep = RNT anexo I, obras = anexo III.4 selva)
class ValorizacionTest {
    private val tablas = Tablas.de(Region.SELVA)

    private fun bd(valor: String) = BigDecimal(valor)

    private fun insumos(
        areaTerreno: BigDecimal? = bd("200"),
        arancelM2: BigDecimal? = bd("45.50"),
        uso: String? = "010101",
        esEdificio: Boolean = false,
        construcciones: List<Construccion> = emptyList(),
        obras: List<Obra> = emptyList(),
        anio: Int = 2026
    ) = Insumos(anio, areaTerreno, arancelM2, uso, esEdificio, construcciones, obras)

    private fun piso(
        piso: String = "1",
        area: BigDecimal? = bd("100"),
        anio: Int? = 2016,
        material: String? = "CONCRETO",
        estado: String? = "BUENO",
        muros: Char? = 'C',
        techos: Char? = 'D',
        puertas: Char? = 'E',
        techoIncluido: Boolean? = null,
        clasificacion: String? = null,
        seccion: Int? = null
    ) = Construccion(piso, area, anio, material, estado, muros, techos, puertas, techoIncluido, clasificacion, seccion)

    private fun valorizada(
        i: Insumos,
        t: Tablas = tablas
    ): Valuacion.Valorizada {
        val v = Valorizacion.valorizar(i, t)
        assertTrue(v is Valuacion.Valorizada) { "se esperaba un valor y salió $v" }
        return v as Valuacion.Valorizada
    }

    private fun sinValor(i: Insumos): Valuacion.SinValorizar {
        val v = Valorizacion.valorizar(i, tablas)
        assertTrue(v is Valuacion.SinValorizar) { "se esperaba un motivo y salió $v" }
        return v as Valuacion.SinValorizar
    }

    // --- terreno

    @Test
    fun `terreno sin construir - área por arancel`() {
        // 200 m2 x 45.50 = 9100.00; nothing built, nothing declared; actualización 2026 = 0
        val v = valorizada(insumos())
        assertEquals(bd("9100.00"), v.terreno)
        assertEquals(bd("0.00"), v.construccion)
        assertEquals(bd("0.00"), v.obras)
        assertEquals(bd("9100.00"), v.autoavaluo)
    }

    @Test
    fun `terreno - se redondea a dos decimales half up`() {
        // 120.35 x 12.37 = 1488.7295 -> 1488.73
        assertEquals(bd("1488.73"), valorizada(insumos(areaTerreno = bd("120.35"), arancelM2 = bd("12.37"))).autoavaluo)
    }

    @Test
    fun `terreno sin construir no necesita uso`() {
        assertEquals(bd("9100.00"), valorizada(insumos(uso = null)).autoavaluo)
    }

    @Test
    fun `sin arancel, o arancel cero, no hay valor de terreno`() {
        assertEquals("ARANCEL_FALTANTE", sinValor(insumos(arancelM2 = null)).llave)
        assertEquals("ARANCEL_FALTANTE", sinValor(insumos(arancelM2 = bd("0.00"))).llave)
    }

    @Test
    fun `sin área de terreno no hay valor de terreno`() {
        val v = sinValor(insumos(areaTerreno = null, arancelM2 = null))
        // the java order: the ficha's own area before the arancel of its vía
        assertEquals("AREA_TERRENO_FALTANTE", v.llave)
        assertTrue(v.motivo.isNotBlank())
    }

    // --- parámetros del año

    @Test
    fun `un año sin parámetros no se valoriza`() {
        assertEquals("PARAMETRO_FALTANTE:PORCENTAJE_ACTUALIZACION:2025", sinValor(insumos(anio = 2025)).llave)
    }

    @Test
    fun `el porcentaje de actualización incrementa el autoavalúo`() {
        val conDiez =
            Tablas(
                tablas.region,
                tablas.valoresUnitarios,
                tablas.depreciaciones,
                tablas.obras,
                tablas.usos,
                tablas.parametros.map {
                    if (it.clave == ClaveParametro.PORCENTAJE_ACTUALIZACION) it.copy(valor = bd("10")) else it
                }
            )
        // 9100.00 x (1 + 10/100) = 10010.00; terreno itself is not touched
        val v = valorizada(insumos(), conDiez)
        assertEquals(bd("9100.00"), v.terreno)
        assertEquals(bd("10010.00"), v.autoavaluo)
    }

    // --- construcción

    @Test
    fun `casa de un piso de concreto`() {
        // uso 010101 -> tabla 01. VU = muros C 489.75 + techos D 231.25 + puertas E 108.28 = 829.28
        // antigüedad 2026 - 2016 = 10 -> tramo hasta 10; tabla 01 Concreto Bueno = 5 %
        // piso = 829.28 x (1 - 0.05) x 100 = 787.816 x 100 = 78781.60
        // autoavalúo = 9100.00 + 78781.60 = 87881.60
        val v = valorizada(insumos(construcciones = listOf(piso())))
        assertEquals(bd("78781.60"), v.construccion)
        assertEquals(bd("87881.60"), v.autoavaluo)
    }

    @Test
    fun `ladrillo tiene su propia columna`() {
        // same piso in LADRILLO: tabla 01 Ladrillo Bueno hasta 10 = 11 %
        // 829.28 x 0.89 x 100 = 73805.92
        assertEquals(bd("73805.92"), valorizada(insumos(construcciones = listOf(piso(material = "LADRILLO")))).construccion)
    }

    @Test
    fun `edificio - el quinto piso sube 5 por ciento antes de depreciar`() {
        // uso 020401 (oficina) -> tabla 03. VU = B 679.21 + A 509.83 + A 421.72 = 1610.76
        // antigüedad 2026 - 2021 = 5 -> tramo hasta 5; tabla 03 Concreto Muy Bueno = 0 %
        // piso 4: 1610.76 x 50 = 80538.00
        // piso 5: 1610.76 x 1.05 = 1691.298; x 50 = 84564.90
        // construcción = 165102.90; terreno 100 x 80 = 8000.00; autoavalúo = 173102.90
        val dos =
            listOf("4", "5").map {
                piso(piso = it, area = bd("50"), anio = 2021, estado = "MUY BUENO", muros = 'B', techos = 'A', puertas = 'A')
            }
        val v =
            valorizada(
                insumos(areaTerreno = bd("100"), arancelM2 = bd("80"), uso = "020401", esEdificio = true, construcciones = dos)
            )
        assertEquals(bd("165102.90"), v.construccion)
        assertEquals(bd("173102.90"), v.autoavaluo)
        // not an edificio: both pisos at 80538.00 = 161076.00
        assertEquals(
            bd("161076.00"),
            valorizada(insumos(uso = "020401", esEdificio = false, construcciones = dos)).construccion
        )
    }

    @Test
    fun `muros A no considera techos`() {
        // anexo I.4, muros A: «PARA ESTE CASO NO SE CONSIDERA LOS VALORES DE LA COLUMNA N° 2» (techos)
        // VU = muros A 995.50 + puertas E 108.28 = 1103.78; x 0.95 x 100 = 104859.10
        val esperado = bd("104859.10")
        assertEquals(esperado, valorizada(insumos(construcciones = listOf(piso(muros = 'A', techos = 'A')))).construccion)
        // techos sin declarar, o en una celda de puntos, no importa: no se pide
        assertEquals(esperado, valorizada(insumos(construcciones = listOf(piso(muros = 'A', techos = null)))).construccion)
        assertEquals(esperado, valorizada(insumos(construcciones = listOf(piso(muros = 'A', techos = 'I')))).construccion)
    }

    @Test
    fun `muros D de drywall que incluye techo no considera techos`() {
        // anexo I.4, muros D «DRYWALL O SIMILAR INCLUYE TECHO (5)»; llamada (5): no se considera la columna N° 2 (techos)
        // VU = muros D 378.67 + puertas E 108.28 = 486.95; x 0.95 (concreto bueno hasta 10) x 100 = 462.6025 x 100 = 46260.25
        val esperado = bd("46260.25")
        val incluido = piso(muros = 'D', techos = 'D', techoIncluido = true)
        assertEquals(esperado, valorizada(insumos(construcciones = listOf(incluido))).construccion)
        // techos sin declarar, o en una celda de puntos, no importa: no se pide
        assertEquals(esperado, valorizada(insumos(construcciones = listOf(piso(muros = 'D', techos = null, techoIncluido = true)))).construccion)
        assertEquals(esperado, valorizada(insumos(construcciones = listOf(piso(muros = 'D', techos = 'I', techoIncluido = true)))).construccion)
    }

    @Test
    fun `muros D sin el indicador suma techos - es el caso del ladrillo`() {
        // VU = muros D 378.67 + techos D 231.25 + puertas E 108.28 = 718.20; x 0.95 x 100 = 682.29 x 100 = 68229.00
        val esperado = bd("68229.00")
        assertEquals(esperado, valorizada(insumos(construcciones = listOf(piso(muros = 'D')))).construccion)
        // un indicador en falso o vacío es lo mismo que no declararlo
        assertEquals(esperado, valorizada(insumos(construcciones = listOf(piso(muros = 'D', techoIncluido = false)))).construccion)
        // y sin techos declarados el predio no se valoriza: la categoría sin declarar no es «sin techo»
        assertEquals(
            "CATEGORIA_FALTANTE:TECHOS",
            sinValor(insumos(construcciones = listOf(piso(muros = 'D', techos = null)))).llave
        )
    }

    @Test
    fun `muros A con el indicador es redundante pero válido`() {
        // muros A ya excluye techos: VU = 995.50 + 108.28 = 1103.78; x 0.95 x 100 = 104859.10, igual que sin indicador
        val v = valorizada(insumos(construcciones = listOf(piso(muros = 'A', techos = 'A', techoIncluido = true))))
        assertEquals(bd("104859.10"), v.construccion)
    }

    @Test
    fun `el indicador de techo incluido con muros que no son A ni D es un error de captura`() {
        // el cuadro solo incluye techo en muros A (estructuras laminares) y D (drywall): con C no hay que adivinar
        val v = sinValor(insumos(construcciones = listOf(piso(muros = 'C', techoIncluido = true))))
        assertEquals("TECHO_INCLUIDO_INVALIDO:C", v.llave)
        assertTrue(v.motivo.contains("piso 1"))
        // en falso, con C, es el caso corriente: VU 829.28 (829.28 x 0.95 x 100 = 78781.60)
        assertEquals(bd("78781.60"), valorizada(insumos(construcciones = listOf(piso(techoIncluido = false)))).construccion)
    }

    @Test
    fun `un sótano o un piso sin número no sube`() {
        // casa de un piso but on "S1" in an edificio: no increment, 78781.60 as above
        val v = valorizada(insumos(esEdificio = true, construcciones = listOf(piso(piso = "S1"))))
        assertEquals(bd("78781.60"), v.construccion)
    }

    @Test
    fun `una celda de puntos no es cero - el predio no se valoriza`() {
        // anexo I.4: techos I is "....."
        val v = sinValor(insumos(construcciones = listOf(piso(techos = 'I'))))
        assertEquals("VU_SIN_VALOR:TECHOS:I", v.llave)
        assertTrue(v.motivo.contains("piso 1"))
        assertTrue(v.motivo.contains("cuadro de la selva"), v.motivo)
    }

    @Test
    fun `el cero explícito del cuadro sí vale`() {
        // techos H = 0.00, puertas I = 0.00; muros C 489.75 -> VU 489.75 x 0.95 x 100 = 46526.25
        assertEquals(bd("46526.25"), valorizada(insumos(construcciones = listOf(piso(techos = 'H', puertas = 'I')))).construccion)
    }

    @Test
    fun `una categoría sin declarar no es sin techo`() {
        assertEquals("CATEGORIA_FALTANTE:TECHOS", sinValor(insumos(construcciones = listOf(piso(techos = null)))).llave)
        val invalida = sinValor(insumos(construcciones = listOf(piso(muros = 'K'))))
        assertEquals("CATEGORIA_INVALIDA:MUROS_COLUMNAS:K", invalida.llave)
        assertTrue(invalida.motivo.contains("A a J"), invalida.motivo)
    }

    @Test
    fun `una construcción sin año, área, material o estado no se valoriza`() {
        assertEquals("ANIO_CONSTRUCCION_FALTANTE", sinValor(insumos(construcciones = listOf(piso(anio = null)))).llave)
        assertEquals("ANTIGUEDAD_NEGATIVA", sinValor(insumos(construcciones = listOf(piso(anio = 2027)))).llave)
        assertEquals("AREA_CONSTRUIDA_FALTANTE", sinValor(insumos(construcciones = listOf(piso(area = null)))).llave)
        assertEquals("MATERIAL_FALTANTE", sinValor(insumos(construcciones = listOf(piso(material = null)))).llave)
        assertEquals("ESTADO_FALTANTE", sinValor(insumos(construcciones = listOf(piso(estado = null)))).llave)
        assertEquals("ESTADO_DESCONOCIDO:PESIMO", sinValor(insumos(construcciones = listOf(piso(estado = "PESIMO")))).llave)
    }

    // --- clasificación de cada construcción (the RNT tabla that construction depreciates with)

    @Test
    fun `la clasificación de la construcción manda sobre la tabla del uso`() {
        // uso 010101 would give tabla 01 (5 %); EDIFICIO-OFICINAS is tabla 03, Concreto Bueno hasta 10 = 8 %
        // 829.28 x 0.92 = 762.9376; x 100 = 76293.76
        val v = valorizada(insumos(construcciones = listOf(piso(clasificacion = "EDIFICIO-OFICINAS"))))
        assertEquals(bd("76293.76"), v.construccion)
        assertEquals(bd("85393.76"), v.autoavaluo)
    }

    @Test
    fun `cada construcción con su tabla - la que no trae clasificación usa la del uso`() {
        // piso 1 CLINICAS... = tabla 04, Concreto Bueno hasta 10 = 10 %: 829.28 x 0.90 x 100 = 74635.20
        // piso 2 without one: the uso's tabla 01, 5 %: 78781.60. construcción = 153416.80
        val dos = listOf(piso(clasificacion = "CLINICAS HOSPITALES CINES INDUSTRIAS COLEGIOS TALLERES"), piso(piso = "2"))
        assertEquals(bd("153416.80"), valorizada(insumos(construcciones = dos)).construccion)
    }

    @Test
    fun `con todas las construcciones clasificadas no hace falta la tabla del uso`() {
        // tabla 02 (TIENDAS...), Concreto Bueno hasta 10 = 7 %: 829.28 x 0.93 x 100 = 77123.04
        val tienda = piso(clasificacion = "TIENDAS DEPOSITOS CENTROS DE RECREACION CLUBES E INSTITUCIONES")
        assertEquals(bd("77123.04"), valorizada(insumos(uso = "990000", construcciones = listOf(tienda))).construccion)
        assertEquals(bd("77123.04"), valorizada(insumos(uso = null, construcciones = listOf(tienda))).construccion)
    }

    @Test
    fun `las obras siguen con la tabla del uso aunque las construcciones traigan la suya`() {
        val muro = Obra("MUROS PERIMETRICOS O CERCOS|1", bd("30"), 2016, "CONCRETO", "BUENO")
        val oficina = piso(clasificacion = "EDIFICIO-OFICINAS")
        // uso 010101 -> tabla 01 for the muro: 8870.61 (as in the obra test); the piso 76293.76 with tabla 03
        val v = valorizada(insumos(construcciones = listOf(oficina), obras = listOf(muro)))
        assertEquals(bd("76293.76"), v.construccion)
        assertEquals(bd("8870.61"), v.obras)
        assertEquals("TABLA_DE_DEPRECIACION:990000", sinValor(insumos(uso = "990000", construcciones = listOf(oficina), obras = listOf(muro))).llave)
    }

    @Test
    fun `una clasificación que el motor no conoce no se valoriza`() {
        // an option added to the model's enum before the engine knows its tabla: never the uso's in silence
        val v = sinValor(insumos(construcciones = listOf(piso(clasificacion = "MUSEOS"))))
        assertEquals("CLASIFICACION_DESCONOCIDA:MUSEOS", v.llave)
        assertTrue(v.motivo.contains("MUSEOS"), v.motivo)
    }

    @Test
    fun `cada clasificación del modelo tiene su tabla del RNT, en el orden de las tablas`() {
        val modelo = JsonMapper.builder().build().readTree(File("model/model.json"))
        val enum = modelo["enums"]["clasificacion"]
        val opciones = (0 until enum.size()).map { enum[it].asString() }
        assertEquals(opciones, Valorizacion.TABLA_POR_CLASIFICACION.keys.toList())
        assertEquals(listOf("01", "02", "03", "04"), Valorizacion.TABLA_POR_CLASIFICACION.values.toList())
        val rnt = tablas.depreciaciones.map { it.tabla }.toSet()
        assertTrue(rnt.containsAll(Valorizacion.TABLA_POR_CLASIFICACION.values), "$rnt")
    }

    // --- secciones de un piso

    @Test
    fun `dos secciones del quinto piso de un edificio suben las dos 5 por ciento`() {
        // the oficina of the edificio test: piso 5 = 1610.76 x 1.05 = 1691.298; x 50 = 84564.90, twice = 169129.80
        val secciones =
            (1..2).map {
                piso(piso = "5", area = bd("50"), anio = 2021, estado = "MUY BUENO", muros = 'B', techos = 'A', puertas = 'A', seccion = it)
            }
        val v = valorizada(insumos(areaTerreno = bd("100"), arancelM2 = bd("80"), uso = "020401", esEdificio = true, construcciones = secciones))
        assertEquals(bd("169129.80"), v.construccion)
    }

    @Test
    fun `el motivo nombra la sección cuando no es la primera`() {
        val segunda = sinValor(insumos(construcciones = listOf(piso(piso = "5", area = null, seccion = 2))))
        assertEquals("AREA_CONSTRUIDA_FALTANTE", segunda.llave)
        assertTrue(segunda.motivo.contains("piso 5, sección 2"), segunda.motivo)
        val primera = sinValor(insumos(construcciones = listOf(piso(piso = "5", area = null, seccion = 1))))
        assertTrue(!primera.motivo.contains("sección"), primera.motivo)
    }

    @Test
    fun `un uso sin tabla de depreciación no se valoriza`() {
        assertEquals("TABLA_DE_DEPRECIACION:990000", sinValor(insumos(uso = "990000", construcciones = listOf(piso()))).llave)
        assertEquals("TABLA_DE_DEPRECIACION:", sinValor(insumos(uso = null, construcciones = listOf(piso()))).llave)
    }

    @Test
    fun `la casilla del cuadro se revisa antes que la tabla del uso`() {
        // the java order: every construction's cells first, then RT-004 (the uso's tabla)
        assertEquals("VU_SIN_VALOR:TECHOS:J", sinValor(insumos(uso = "990000", construcciones = listOf(piso(techos = 'J')))).llave)
    }

    @Test
    fun `la tabla del uso se revisa antes que lo que declara cada piso u obra`() {
        // the documented order: cells, then the tabla, then área / material / estado / the obra's own data
        assertEquals("TABLA_DE_DEPRECIACION:990000", sinValor(insumos(uso = "990000", construcciones = listOf(piso(area = null)))).llave)
        assertEquals("TABLA_DE_DEPRECIACION:990000", sinValor(insumos(uso = "990000", construcciones = listOf(piso(estado = "PESIMO")))).llave)
        val desconocida = Obra("CERCOS METALICOS|3", null, null, null, null)
        assertEquals("TABLA_DE_DEPRECIACION:990000", sinValor(insumos(uso = "990000", obras = listOf(desconocida))).llave)
    }

    @Test
    fun `un área construida o una cantidad negativa no se valoriza`() {
        assertEquals("AREA_CONSTRUIDA_INVALIDA", sinValor(insumos(construcciones = listOf(piso(area = bd("-1"))))).llave)
        val muro = Obra("MUROS PERIMETRICOS O CERCOS|1", bd("-30"), 2016, "CONCRETO", "BUENO")
        assertEquals("OBRA_CANTIDAD_INVALIDA", sinValor(insumos(obras = listOf(muro))).llave)
        // zero is a value: nothing built there
        assertEquals(bd("9100.00"), valorizada(insumos(obras = listOf(muro.copy(cantidad = BigDecimal.ZERO)))).autoavaluo)
    }

    @Test
    fun `celda asterisco - toma el último porcentaje publicado de su fila`() {
        // ADOBE -> Liviano/Adobe (D2), MUY MALO -> Malo (D3). tabla 01 Liviano/Adobe Malo: 65 70 75 80 85 90 * * * * *
        // antigüedad 2026 - 1980 = 46 -> '*' -> last published = 90 %
        // VU = H 102.68 + H 0.00 + H 26.06 = 128.74; x (1 - 0.90) = 12.874; x 40 = 514.96
        // autoavalúo = 300 x 5 = 1500.00 + 514.96 = 2014.96
        val adobe = piso(area = bd("40"), anio = 1980, material = "ADOBE", estado = "MUY MALO", muros = 'H', techos = 'H', puertas = 'H')
        val v = valorizada(insumos(areaTerreno = bd("300"), arancelM2 = bd("5"), construcciones = listOf(adobe)))
        assertEquals(bd("514.96"), v.construccion)
        assertEquals(bd("2014.96"), v.autoavaluo)
    }

    // --- levantamiento

    @Test
    fun `una ficha sin levantar no se valoriza ni se estima`() {
        val v = sinValor(insumos(areaTerreno = null, arancelM2 = null).copy(levantamiento = "SIN_LEVANTAR"))
        assertEquals("SIN_LEVANTAMIENTO", v.llave)
        assertEquals("SIN_LEVANTAMIENTO", v.motivo)
    }

    @Test
    fun `una ficha parcial o completa se valoriza como siempre`() {
        assertEquals(bd("9100.00"), valorizada(insumos().copy(levantamiento = "PARCIAL")).autoavaluo)
        assertEquals(bd("9100.00"), valorizada(insumos().copy(levantamiento = "COMPLETO")).autoavaluo)
    }

    // --- tipo de predio (rústico, #27: sin tablas rústicas, sin valor)

    @Test
    fun `un predio rústico no se valoriza con el arancel urbano`() {
        val v = sinValor(insumos().copy(tipoPredio = "RUSTICO"))
        assertEquals("PREDIO_RUSTICO", v.llave)
        assertEquals("PREDIO_RUSTICO", v.motivo)
    }

    @Test
    fun `un predio urbano, o sin tipo, se valoriza como siempre`() {
        assertEquals(bd("9100.00"), valorizada(insumos().copy(tipoPredio = "URBANO")).autoavaluo)
    }

    @Test
    fun `sin levantar gana sobre rústico`() {
        assertEquals("SIN_LEVANTAMIENTO", sinValor(insumos().copy(levantamiento = "SIN_LEVANTAR", tipoPredio = "RUSTICO")).llave)
    }

    // --- obras complementarias

    @Test
    fun `obra complementaria - VU por cantidad por factor de oficialización depreciado`() {
        // MUROS PERIMETRICOS O CERCOS|1 = 457.72 por m2; 30 m2; Fo 2026 = 0.68
        // antigüedad 10, tabla 01 (uso del predio) Concreto Bueno = 5 %
        // 457.72 x 30 = 13731.60; x 0.68 = 9337.488; x 0.95 = 8870.6136 -> 8870.61
        // autoavalúo = 9100.00 + 8870.61 = 17970.61
        val muro = Obra("MUROS PERIMETRICOS O CERCOS|1", bd("30"), 2016, "CONCRETO", "BUENO")
        val v = valorizada(insumos(obras = listOf(muro)))
        assertEquals(bd("8870.61"), v.obras)
        assertEquals(bd("17970.61"), v.autoavaluo)
    }

    @Test
    fun `obra sin material toma el de su partida`() {
        // the partida says CONCRETO: same figure as above
        val muro = Obra("MUROS PERIMETRICOS O CERCOS|1", bd("30"), 2016, null, "BUENO")
        assertEquals(bd("8870.61"), valorizada(insumos(obras = listOf(muro))).obras)
    }

    @Test
    fun `obra que el cuadro no tiene, o incompleta, no se valoriza`() {
        val obra = Obra("CERCOS METALICOS|3", bd("1"), 2016, "METAL", "BUENO")
        val desconocida = sinValor(insumos(obras = listOf(obra)))
        assertEquals("OBRA_DESCONOCIDA:CERCOS METALICOS|3", desconocida.llave)
        assertTrue(desconocida.motivo.contains("de la selva"), desconocida.motivo)
        val ok = obra.copy(codigoVu = "MUROS PERIMETRICOS O CERCOS|1")
        assertEquals("OBRA_CANTIDAD_FALTANTE", sinValor(insumos(obras = listOf(ok.copy(cantidad = null)))).llave)
        assertEquals("ANIO_CONSTRUCCION_FALTANTE", sinValor(insumos(obras = listOf(ok.copy(anioConstruccion = null)))).llave)
        assertEquals("ESTADO_FALTANTE", sinValor(insumos(obras = listOf(ok.copy(estado = null)))).llave)
        assertEquals("TABLA_DE_DEPRECIACION:990000", sinValor(insumos(uso = "990000", obras = listOf(ok))).llave)
    }

    @Test
    fun `todo junto`() {
        // casa de un piso 78781.60 + muro 8870.61 + terreno 9100.00 = 96752.21
        val muro = Obra("MUROS PERIMETRICOS O CERCOS|1", bd("30"), 2016, "CONCRETO", "BUENO")
        val v = valorizada(insumos(construcciones = listOf(piso()), obras = listOf(muro)))
        assertEquals(bd("9100.00"), v.terreno)
        assertEquals(bd("78781.60"), v.construccion)
        assertEquals(bd("8870.61"), v.obras)
        assertEquals(bd("96752.21"), v.autoavaluo)
    }
}
