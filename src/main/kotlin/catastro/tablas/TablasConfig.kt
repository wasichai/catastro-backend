package catastro.tablas

import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration

// the tables of every region an organization may choose
class TablasPorRegion(
    private val porRegion: Map<Region, Tablas>
) {
    fun de(region: Region): Tablas = porRegion.getValue(region)
}

// the normative tables of every region, read once from the classpath at startup: a malformed file fails the boot, not
// a valuation
@Configuration(proxyBeanMethods = false)
class TablasConfig {
    @Bean
    fun tablasPorRegion(): TablasPorRegion = TablasPorRegion(Region.entries.associateWith(Tablas::de))
}
