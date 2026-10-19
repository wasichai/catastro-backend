package catastro.tablas

import org.slf4j.LoggerFactory
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration

// the tables of every region an organization may choose
class TablasPorRegion(
    private val porRegion: Map<Region, Tablas>
) {
    fun de(region: Region): Tablas = porRegion.getValue(region)
}

// the normative tables of every region, read once from the classpath at startup: a malformed file fails the boot, not
// a valuation. one log line per region says what it carries, so a region without its obras cuadro is visible
@Configuration(proxyBeanMethods = false)
class TablasConfig {
    @Bean
    fun tablasPorRegion(): TablasPorRegion {
        val porRegion = Region.entries.associateWith(Tablas::de)
        porRegion.values.forEach { t ->
            log.info(
                "tablas {}: {} celdas de valores unitarios ({} sin valor), {}",
                t.region,
                t.valoresUnitarios.size,
                t.valoresUnitarios.count { it.valorM2 == null },
                t.obras?.let { "${it.size} partidas de obras (${t.region.obras})" } ?: "sin cuadro de obras (${t.region.obras} no está)"
            )
        }
        return TablasPorRegion(porRegion)
    }

    private companion object {
        val log = LoggerFactory.getLogger(TablasConfig::class.java)
    }
}
