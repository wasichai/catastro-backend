import org.springframework.boot.gradle.tasks.bundling.BootJar

// security floors for the build's own classpath: the spring boot plugin brings commons-lang3 3.16.0 (through
// commons-compress) and jackson 3.1.5, both vulnerable. build time only; the app's come from wasichai-bom
buildscript {
    repositories {
        mavenCentral()
    }
    dependencies {
        constraints {
            classpath("org.apache.commons:commons-lang3:${libs.versions.commons.lang3.get()}")
            classpath("tools.jackson.core:jackson-core:${libs.versions.jackson3.get()}")
            classpath("tools.jackson.core:jackson-databind:${libs.versions.jackson3.get()}")
        }
    }
}

plugins {
    kotlin("jvm") version "2.4.21"
    kotlin("plugin.spring") version "2.4.20"
    id("org.springframework.boot") version "4.1.1"
    id("org.jlleitschuh.gradle.ktlint") version "14.2.0"
}

group = "catastro"
description = "catastro-backend: valorización catastral (autoavalúo) de Perené on wasichai"

val wasichaiVersion = "1.3.0"

dependencies {
    implementation(platform("wasichai:wasichai-bom:$wasichaiVersion"))
    implementation("wasichai:wasichai-spring-boot-starter")
    // lotes and predios with their polygons. needs PostGIS (compose.yml)
    implementation("wasichai:wasichai-spring-boot-starter-gis")

    // WasichaiIntegrationTest; brings spring-boot-starter-test, webflux-test and testcontainers
    testImplementation("wasichai:wasichai-test")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher")
}

kotlin {
    jvmToolchain(25)
    compilerOptions {
        freeCompilerArgs.add("-Xjsr305=strict")
    }
}

// ktlint reads .editorconfig; same tool version as wasichai
ktlint {
    version.set("1.7.1")
}

// ktlint's tool classpath pins logback 1.3.15 (vulnerable). lift it; ktlint only logs through it
configurations.matching { it.name.startsWith("ktlint") }.configureEach {
    resolutionStrategy.eachDependency {
        if (requested.group == "ch.qos.logback") {
            useVersion(libs.versions.logback.get())
            because("logback below 1.5.34 is vulnerable")
        }
    }
}

// unit tests always run; container-backed ones go through integrationTest
tasks.named<Test>("test") {
    useJUnitPlatform {
        excludeTags("integration")
    }
    // the smoke test is integration-tagged: an empty unit run is expected
    failOnNoDiscoveredTests.set(false)
}

// WASICHAI_TEST_DB_* (if set) point the suite at an external db instead of testcontainers
tasks.register<Test>("integrationTest") {
    group = "verification"
    description = "Runs tests tagged 'integration' against a PostgreSQL container."
    testClassesDirs = sourceSets["test"].output.classesDirs
    classpath = sourceSets["test"].runtimeClasspath
    useJUnitPlatform {
        includeTags("integration")
    }
    // gis needs PostGIS: testcontainers starts this image instead of plain postgres:18. an external test db
    // (WASICHAI_TEST_DB_*) must have the postgis extension available
    systemProperty("wasichai.test.db.image", "postgis/postgis:18-3.6")
    // the app logs to stdout; stderr carries only what a test reports
    testLogging {
        events("standard_error")
    }
    shouldRunAfter(tasks.named("test"))
}

// one runnable jar with a fixed name
tasks.named<BootJar>("bootJar") {
    archiveFileName.set("app.jar")
}

// an app, not a library: no plain jar next to the boot jar
tasks.named<Jar>("jar") {
    enabled = false
}
