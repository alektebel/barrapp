#!/usr/bin/env bash
# Compile and RUN the app's pure logic on a plain JVM.
#
# Why this exists: the Compose and androidx toolchain cannot be fetched in
# every environment (maven.google.com redirects to dl.google.com, which some
# network policies block), and where it cannot, no Kotlin in this project gets
# executed at all. The coach's answers and the weekly review's arithmetic are
# deliberately free of Android so that they can be, here and under Gradle.
#
#   tools/run_logic_tests.sh [path/to/kotlin-compiler-embeddable.jar]
#
# With no argument it looks for kotlinc on PATH.
set -euo pipefail
cd "$(dirname "$0")/.."
SRC=(
  app/src/main/java/com/barrapp/data/Models.kt
  app/src/main/java/com/barrapp/data/Profile.kt
  app/src/main/java/com/barrapp/notify/ReviewText.kt
  app/src/main/java/com/barrapp/Coach.kt
  app/src/main/java/com/barrapp/Progression.kt
  app/src/test/java/com/barrapp/LogicTest.kt
)
OUT=$(mktemp -d)
if command -v kotlinc >/dev/null 2>&1; then
  kotlinc "${SRC[@]}" -include-runtime -d "$OUT/logic.jar" >/dev/null
  java -cp "$OUT/logic.jar" com.barrapp.LogicTest
else
  JAR=${1:?"pass the path to kotlin-compiler-embeddable.jar, or install kotlinc"}
  LIB=$(dirname "$JAR")
  # kotlin-compiler-embeddable needs coroutines and trove4j on its own
  # classpath, not just the compiled code's.
  java -cp "$JAR:$LIB/kotlin-stdlib.jar:$LIB/annotations.jar:$LIB/trove4j.jar:$LIB/coroutines.jar" \
    org.jetbrains.kotlin.cli.jvm.K2JVMCompiler -no-stdlib -no-reflect -nowarn \
    -classpath "$LIB/kotlin-stdlib.jar" -d "$OUT/classes" "${SRC[@]}" 2>&1 | grep -v "Picked up" || true
  java -cp "$OUT/classes:$LIB/kotlin-stdlib.jar" com.barrapp.LogicTest 2>&1 | grep -v "Picked up"
fi
