package catastro.tablas

import java.io.Reader

// the tablas' csv: leading '#' lines cite the source, then a header and rfc 4180 rows (quoted fields may hold commas;
// no field spans lines). a trailing '\r' is dropped so a file saved with crlf reads the same: readLine already splits
// on crlf, the strip keeps that from being an accident of the reader. a hand parser keeps the loader free of a csv
// dependency for five small files
internal object Csv {
    fun leer(
        reader: Reader,
        nombre: String
    ): List<Map<String, String>> {
        val lineas =
            reader.useLines { seq ->
                seq
                    .map { it.removeSuffix("\r") }
                    .dropWhile { it.startsWith("#") }
                    .filter { it.isNotEmpty() }
                    .toList()
            }
        require(lineas.isNotEmpty()) { "$nombre: sin cabecera" }
        val cabecera = campos(lineas.first(), nombre, 1)
        return lineas.drop(1).mapIndexed { i, linea ->
            val valores = campos(linea, nombre, i + 2)
            require(valores.size == cabecera.size) {
                "$nombre, fila ${i + 2}: ${valores.size} campos, la cabecera tiene ${cabecera.size}"
            }
            cabecera.zip(valores).toMap()
        }
    }

    private fun campos(
        linea: String,
        nombre: String,
        fila: Int
    ): List<String> {
        val campos = mutableListOf<String>()
        val actual = StringBuilder()
        var entreComillas = false
        var i = 0
        while (i < linea.length) {
            val c = linea[i]
            when {
                entreComillas && c == '"' && i + 1 < linea.length && linea[i + 1] == '"' -> {
                    actual.append('"')
                    i++
                }
                c == '"' -> entreComillas = !entreComillas
                c == ',' && !entreComillas -> {
                    campos += actual.toString()
                    actual.clear()
                }
                else -> actual.append(c)
            }
            i++
        }
        require(!entreComillas) { "$nombre, fila $fila: comillas sin cerrar" }
        campos += actual.toString()
        return campos
    }
}
