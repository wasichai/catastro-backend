package catastro

import org.springframework.boot.runApplication
import wasichai.core.autoconfigure.WasichaiApplication

// the whole server: the wasichai starters on the classpath do the rest.
// never move it under package `wasichai`: the component scan would register the library's controllers twice (ADR-024)
@WasichaiApplication
class CatastroApplication

fun main(args: Array<String>) {
    runApplication<CatastroApplication>(*args)
}
