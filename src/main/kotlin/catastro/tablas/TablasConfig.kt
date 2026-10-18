package catastro.tablas

import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration

// the normative tables, read once from the classpath at startup: a malformed file fails the boot, not a valuation
@Configuration(proxyBeanMethods = false)
class TablasConfig {
    @Bean
    fun tablas(): Tablas = Tablas.desdeClasspath()
}
