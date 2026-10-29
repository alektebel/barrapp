# Play Store checklist

1. Host `docs/privacy.md` at an HTTPS URL. Paste it into Play Console → App content → Privacy policy.
2. Data safety: Photos and videos, collected, sent off-device, not sold, not used for ads. Device or other IDs: a random app-generated id.
3. Category: Health & Fitness. Content rating questionnaire. Do not claim medical or coaching benefits.
4. Screenshots (phone), 1024×500 feature graphic, short description.
5. Upload `app/build/outputs/bundle/release/app-release.aab` (not the debug APK). Package name is `com.fitness.barrapp` (`applicationId` in `app/build.gradle.kts`) and cannot change later.
6. Create the release keystore **once**, back it up off this machine, and never commit it:

```bash
source scripts/env.sh
mkdir -p keystore
cp keystore.properties.example keystore.properties
# put your own passwords in keystore.properties, then:
keytool -genkeypair -v \
  -keystore keystore/barrapp-release.jks \
  -keyalg RSA -keysize 2048 -validity 10000 \
  -alias barrapp \
  -dname "CN=barrapp, OU=barrapp, O=alektebel, C=ES"
./gradlew bundleRelease
```

Losing `keystore/barrapp-release.jks` means you cannot update the Play listing.

## Subida automática

`.github/workflows/play-release.yml` compila el `.aab` firmado y lo sube a Play:
al empujar una etiqueta `vX.Y.Z` (pista **internal**) o a mano desde Actions
eligiendo la pista. Pasos, una sola vez:

1. **Cuenta de servicio.** Google Cloud → IAM → Cuentas de servicio → crear una →
   Claves → JSON. Activa la «Google Play Android Developer API» en ese proyecto.
2. **Permisos en Play.** Play Console → Usuarios y permisos → invitar el correo de la
   cuenta de servicio con el rol de **gestor de versiones** sobre barrapp.
3. **Secretos del repositorio** (Settings → Secrets → Actions): `PLAY_SERVICE_ACCOUNT_JSON`
   (el JSON entero), `PLAY_KEYSTORE_BASE64` (`base64 -w0 keystore/barrapp-release.jks`),
   `PLAY_KEYSTORE_PASSWORD`, `PLAY_KEY_ALIAS`, `PLAY_KEY_PASSWORD`.
4. **Cada release:** sube `versionCode` (y `versionName`) en `app/build.gradle.kts`, commit,
   `git tag v1.5.0 && git push --tags`. Play rechaza un `versionCode` ya usado.

El keystore sigue siendo el de subida: si usas Play App Signing, perderlo se arregla
desde Play Console; si no, no hay vuelta atrás (ver arriba). Promocionar de internal a
producción se hace en Play Console o relanzando el workflow con `track=production`.
