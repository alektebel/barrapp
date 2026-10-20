/*
 * Copyright (C) 2023 The Android Open Source Project
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
import java.util.Properties

val singlePutLimitProperty = project.findProperty("barrapp.singlePutMaxBytes")?.toString()
val debugSinglePutMaxBytes = singlePutLimitProperty?.toLongOrNull()
    ?: if (singlePutLimitProperty == null) 8L * 1024 * 1024
    else error("barrapp.singlePutMaxBytes must be a non-negative integer")
require(debugSinglePutMaxBytes >= 0) { "barrapp.singlePutMaxBytes must be non-negative" }

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

val keystorePropertiesFile = rootProject.file("keystore.properties")
val keystoreProperties = Properties()
if (keystorePropertiesFile.exists()) {
    keystoreProperties.load(keystorePropertiesFile.inputStream())
}

android {
    namespace = "com.barrapp"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.fitness.barrapp"
        minSdk = 24
        targetSdk = 36
        versionCode = 100
        versionName = "1.4.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        vectorDrawables {
            useSupportLibrary = true
        }
        buildConfigField(
            "String",
            "API_BASE_URL",
            "\"${project.findProperty("barrapp.apiUrlDebug") ?: "http://192.168.1.120:8080"}\"",
        )
        buildConfigField("long", "SINGLE_PUT_MAX_BYTES", "${8L * 1024 * 1024}L")
    }

    signingConfigs {
        if (keystorePropertiesFile.exists()) {
            create("release") {
                storeFile = rootProject.file(keystoreProperties.getProperty("storeFile"))
                storePassword = keystoreProperties.getProperty("storePassword")
                keyAlias = keystoreProperties.getProperty("keyAlias")
                keyPassword = keystoreProperties.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        debug {
            // A second install beside the real one, for end-to-end runs from a
            // fresh state (onboarding included) without wiping the phone's
            // own sessions: -Pbarrapp.appIdSuffix=.e2e
            (project.findProperty("barrapp.appIdSuffix") as String?)?.let {
                applicationIdSuffix = it
            }
            buildConfigField(
                "String",
                "API_BASE_URL",
                "\"${project.findProperty("barrapp.apiUrlDebug") ?: "http://192.168.1.120:8080"}\"",
            )
            buildConfigField("long", "SINGLE_PUT_MAX_BYTES", "${debugSinglePutMaxBytes}L")
        }
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
            buildConfigField(
                "String",
                "API_BASE_URL",
                "\"${project.findProperty("barrapp.apiUrlRelease") ?: "https://REPLACE_AFTER_SAM_DEPLOY.execute-api.eu-west-1.amazonaws.com"}\"",
            )
            if (keystorePropertiesFile.exists()) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
    testOptions {
        unitTests {
            isIncludeAndroidResources = true
        }
    }
}

dependencies {

    implementation(platform("androidx.compose:compose-bom:2024.12.01"))
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.compose.material3:material3")
    // Icons used by the shell and calendar. Pulled in transitively by
    // material3, but declared so a material3 upgrade cannot drop them.
    implementation("androidx.compose.material:material-icons-core")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-graphics")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    // Media3 Transformer: recorta el clip a la serie (720p H.264 ~4 Mbit/s)
    // antes de subirlo.
    implementation("androidx.media3:media3-transformer:1.4.1")
    implementation("androidx.media3:media3-effect:1.4.1")
    implementation("androidx.media3:media3-common:1.4.1")
    // ExoPlayer para la repetición: búsqueda precisa al fotograma y una
    // posición que se puede leer en cada frame, para que el contador suba
    // con la rep que se ve. Misma versión que el Transformer.
    implementation("androidx.media3:media3-exoplayer:1.4.1")
    implementation("androidx.media3:media3-ui:1.4.1")
    implementation("com.squareup.okhttp3:okhttp-dnsoverhttps:4.12.0")
    // Weekly review notification. Scheduled by the system, so it survives the
    // app being killed - which is the whole point of a weekly nudge.
    implementation("androidx.work:work-runtime-ktx:2.10.0")

    debugImplementation("androidx.compose.ui:ui-test-manifest")
    debugImplementation("androidx.compose.ui:ui-tooling")

    // Robolectric Compose screenshot tests: render the real composables to
    // PNG on the JVM, no emulator, so an agent (or a vision model) can look at
    // the actual UI. See app/src/test/java/com/barrapp/UiScreenshotTest.kt.
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.7.3")
    testImplementation("junit:junit:4.13.2")
    testImplementation("androidx.test:core:1.6.1")
    testImplementation("androidx.test.ext:junit:1.2.1")
    testImplementation("org.robolectric:robolectric:4.14.1")
    testImplementation("androidx.compose.ui:ui-test-junit4")
    testImplementation("androidx.compose.ui:ui-test-manifest")
}
