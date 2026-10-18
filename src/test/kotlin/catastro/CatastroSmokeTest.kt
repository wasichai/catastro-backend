package catastro

import org.junit.jupiter.api.Test
import org.springframework.http.HttpHeaders
import wasichai.test.WasichaiIntegrationTest

// the app itself (CatastroApplication) on PostGIS: it boots, the admin logs in, and the gis module answers
class CatastroSmokeTest : WasichaiIntegrationTest() {
    @Test
    fun `health is up`() {
        client
            .get()
            .uri("/actuator/health")
            .exchange()
            .expectStatus()
            .isOk
            .expectBody()
            .jsonPath("$.status")
            .isEqualTo("UP")
    }

    @Test
    fun `the seeded admin logs in and reaches the gis layers`() {
        client
            .get()
            .uri("/api/gis/layers")
            .header(HttpHeaders.AUTHORIZATION, bearer())
            .exchange()
            .expectStatus()
            .isOk
    }
}
