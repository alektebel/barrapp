export JAVA_HOME="${JAVA_HOME:-$(ls -d "$HOME"/.jdks/jdk-17* 2>/dev/null | sort | tail -1)}"
export ANDROID_HOME="$HOME/Android/Sdk"
export ANDROID_SDK_ROOT=$ANDROID_HOME
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
