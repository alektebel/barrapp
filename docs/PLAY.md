# Play Store checklist

1. Host `docs/privacy.md` at an HTTPS URL. Paste it into Play Console → App content → Privacy policy.
2. Data safety: Photos and videos, collected, sent off-device, not sold, not used for ads. Device or other IDs: a random app-generated id.
3. Category: Health & Fitness. Content rating questionnaire. Do not claim medical or coaching benefits.
4. Screenshots (phone), 1024×500 feature graphic, short description.
5. Upload `app/build/outputs/bundle/release/app-release.aab` (not the debug APK). Package name is `com.alektebel.barrapp` and cannot change later.
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
