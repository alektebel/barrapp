"""Check that every Compose/Android symbol a file uses is imported.

The Kotlin parser cannot catch a missing import here: without the Android
classpath every androidx symbol is unresolved anyway, so a forgotten import
looks exactly like a present one. This walks the other way - it finds the
symbols the file actually uses and asserts an import line exists for each.

Deliberately curated rather than exhaustive: a wrong entry would produce false
alarms, and the point is a list that can be trusted without checking.
"""
import re, sys, pathlib

SYMBOLS = {
    # modifiers / foundation
    "background(": "androidx.compose.foundation.background",
    "border(": "androidx.compose.foundation.border",
    "clickable(": "androidx.compose.foundation.clickable",
    "Canvas(": "androidx.compose.foundation.Canvas",
    "verticalScroll(": "androidx.compose.foundation.verticalScroll",
    "rememberScrollState(": "androidx.compose.foundation.rememberScrollState",
    "horizontalScroll(": "androidx.compose.foundation.horizontalScroll",
    # layout
    "Arrangement.": "androidx.compose.foundation.layout.Arrangement",
    "Spacer(": "androidx.compose.foundation.layout.Spacer",
    "PaddingValues(": "androidx.compose.foundation.layout.PaddingValues",
    ".fillMaxSize(": "androidx.compose.foundation.layout.fillMaxSize",
    ".fillMaxWidth(": "androidx.compose.foundation.layout.fillMaxWidth",
    ".fillMaxHeight(": "androidx.compose.foundation.layout.fillMaxHeight",
    ".padding(": "androidx.compose.foundation.layout.padding",
    ".widthIn(": "androidx.compose.foundation.layout.widthIn",
    ".heightIn(": "androidx.compose.foundation.layout.heightIn",
    ".aspectRatio(": "androidx.compose.foundation.layout.aspectRatio",
    ".imePadding(": "androidx.compose.foundation.layout.imePadding",
    ".safeDrawingPadding(": "androidx.compose.foundation.layout.safeDrawingPadding",
    ".navigationBarsPadding(": "androidx.compose.foundation.layout.navigationBarsPadding",
    ".statusBarsPadding(": "androidx.compose.foundation.layout.statusBarsPadding",
    "BoxWithConstraints(": "androidx.compose.foundation.layout.BoxWithConstraints",
    # lazy
    "LazyColumn(": "androidx.compose.foundation.lazy.LazyColumn",
    "LazyRow(": "androidx.compose.foundation.lazy.LazyRow",
    "itemsIndexed(": "androidx.compose.foundation.lazy.itemsIndexed",
    "rememberLazyListState(": "androidx.compose.foundation.lazy.rememberLazyListState",
    "LazyVerticalGrid(": "androidx.compose.foundation.lazy.grid.LazyVerticalGrid",
    "GridCells.": "androidx.compose.foundation.lazy.grid.GridCells",
    # shape / graphics
    "RoundedCornerShape(": "androidx.compose.foundation.shape.RoundedCornerShape",
    "CircleShape": "androidx.compose.foundation.shape.CircleShape",
    ".clip(": "androidx.compose.ui.draw.clip",
    ".alpha(": "androidx.compose.ui.draw.alpha",
    "Offset(": "androidx.compose.ui.geometry.Offset",
    "Path(": "androidx.compose.ui.graphics.Path",
    "StrokeCap.": "androidx.compose.ui.graphics.StrokeCap",
    "Stroke(": "androidx.compose.ui.graphics.drawscope.Stroke",
    "Color(": "androidx.compose.ui.graphics.Color",
    "FontFamily.": "androidx.compose.ui.text.font.FontFamily",
    "FontWeight.": "androidx.compose.ui.text.font.FontWeight",
    "TextAlign.": "androidx.compose.ui.text.style.TextAlign",
    "TextOverflow.": "androidx.compose.ui.text.style.TextOverflow",
    "Alignment.": "androidx.compose.ui.Alignment",
    ".dp": "androidx.compose.ui.unit.dp",
    ".sp": "androidx.compose.ui.unit.sp",
    "LocalContext.": "androidx.compose.ui.platform.LocalContext",
    "LocalView.": "androidx.compose.ui.platform.LocalView",
    "LocalFocusManager.": "androidx.compose.ui.platform.LocalFocusManager",
    "LocalHapticFeedback.": "androidx.compose.ui.platform.LocalHapticFeedback",
    "HapticFeedbackType.": "androidx.compose.ui.hapticfeedback.HapticFeedbackType",
    ".graphicsLayer": "androidx.compose.ui.graphics.graphicsLayer",
    ".zIndex(": "androidx.compose.ui.zIndex",
    "PathEffect.": "androidx.compose.ui.graphics.PathEffect",
    "MutableInteractionSource(": "androidx.compose.foundation.interaction.MutableInteractionSource",
    ".collectIsPressedAsState(": "androidx.compose.foundation.interaction.collectIsPressedAsState",
    # runtime
    "remember{": "androidx.compose.runtime.remember",
    "remember(": "androidx.compose.runtime.remember",
    "mutableStateOf(": "androidx.compose.runtime.mutableStateOf",
    "mutableIntStateOf(": "androidx.compose.runtime.mutableIntStateOf",
    "mutableStateListOf(": "androidx.compose.runtime.mutableStateListOf",
    "LaunchedEffect(": "androidx.compose.runtime.LaunchedEffect",
    "DisposableEffect(": "androidx.compose.runtime.DisposableEffect",
    "SideEffect{": "androidx.compose.runtime.SideEffect",
    "derivedStateOf(": "androidx.compose.runtime.derivedStateOf",
    "rememberCoroutineScope(": "androidx.compose.runtime.rememberCoroutineScope",
    "CompositionLocalProvider(": "androidx.compose.runtime.CompositionLocalProvider",
    "staticCompositionLocalOf(": "androidx.compose.runtime.staticCompositionLocalOf",
    # material3
    "MaterialTheme.": "androidx.compose.material3.MaterialTheme",
    "Text(": "androidx.compose.material3.Text",
    "Button(": "androidx.compose.material3.Button",
    "TextButton(": "androidx.compose.material3.TextButton",
    "OutlinedButton(": "androidx.compose.material3.OutlinedButton",
    "FilledTonalButton(": "androidx.compose.material3.FilledTonalButton",
    "IconButton(": "androidx.compose.material3.IconButton",
    "Icon(": "androidx.compose.material3.Icon",
    "Surface(": "androidx.compose.material3.Surface",
    "Scaffold(": "androidx.compose.material3.Scaffold",
    "HorizontalDivider(": "androidx.compose.material3.HorizontalDivider",
    "VerticalDivider(": "androidx.compose.material3.VerticalDivider",
    "OutlinedTextField(": "androidx.compose.material3.OutlinedTextField",
    "LinearProgressIndicator(": "androidx.compose.material3.LinearProgressIndicator",
    "CircularProgressIndicator(": "androidx.compose.material3.CircularProgressIndicator",
    "FilterChip(": "androidx.compose.material3.FilterChip",
    "AssistChip(": "androidx.compose.material3.AssistChip",
    "NavigationBar(": "androidx.compose.material3.NavigationBar",
    "NavigationBarItem(": "androidx.compose.material3.NavigationBarItem",
    "NavigationRail(": "androidx.compose.material3.NavigationRail",
    "NavigationRailItem(": "androidx.compose.material3.NavigationRailItem",
    "FloatingActionButton(": "androidx.compose.material3.FloatingActionButton",
    "ExtendedFloatingActionButton(": "androidx.compose.material3.ExtendedFloatingActionButton",
    "TopAppBar(": "androidx.compose.material3.TopAppBar",
    "AlertDialog(": "androidx.compose.material3.AlertDialog",
    "Icons.": "androidx.compose.material.icons.Icons",
    # animation
    "AnimatedVisibility(": "androidx.compose.animation.AnimatedVisibility",
    "AnimatedContent(": "androidx.compose.animation.AnimatedContent",
    "animateFloatAsState(": "androidx.compose.animation.core.animateFloatAsState",
    "rememberInfiniteTransition(": "androidx.compose.animation.core.rememberInfiniteTransition",
    "infiniteRepeatable(": "androidx.compose.animation.core.infiniteRepeatable",
    "tween(": "androidx.compose.animation.core.tween",
    "fadeIn(": "androidx.compose.animation.fadeIn",
    "fadeOut(": "androidx.compose.animation.fadeOut",
    "slideInVertically(": "androidx.compose.animation.slideInVertically",
    "slideOutVertically(": "androidx.compose.animation.slideOutVertically",
    "slideInHorizontally(": "androidx.compose.animation.slideInHorizontally",
    "slideOutHorizontally(": "androidx.compose.animation.slideOutHorizontally",
    # lifecycle
    "collectAsStateWithLifecycle(": "androidx.lifecycle.compose.collectAsStateWithLifecycle",
    "viewModel(": "androidx.lifecycle.viewmodel.compose.viewModel",
}

# `by` delegation needs these; flagged separately because the symbol is a keyword.
DELEGATES = [("getValue", " by remember"), ("getValue", " by vm."), ("getValue", " by transition")]

bad = 0
for path in sys.argv[1:]:
    src = pathlib.Path(path).read_text()
    body = "\n".join(l for l in src.splitlines() if not l.startswith("import "))
    imports = set(re.findall(r"^import (.+)$", src, re.M))
    # Fully-qualified uses need no import.
    for imp in list(imports):
        body = body.replace(imp, "\u0000")
    for token, imp in SYMBOLS.items():
        name = token.rstrip("(.").lstrip(".")
        if token.startswith("."):
            # extension or unit: .dp .sp .padding( ...
            pattern = rf"\.{re.escape(name)}\b"
        elif token.endswith("("):
            pattern = rf"(?<![\w]){re.escape(name)}\s*\("
        else:
            pattern = rf"(?<![\w]){re.escape(name)}\b"
        if re.search(pattern, body) and imp not in imports:
            # a symbol declared in this same file needs no import
            local = imp.rsplit(".", 1)[1]
            if re.search(rf"^(private )?(fun|val|var|object|class|data class|enum class)\s+{local}\b",
                         body, re.M):
                continue
            if re.search(rf"fun {local}\s*\(", body):
                continue
            print(f"{path}: uses {token!r} but does not import {imp}")
            bad += 1
    if re.search(r"\bby (remember|vm\.|transition|infiniteTransition)", body) and \
       "androidx.compose.runtime.getValue" not in imports:
        print(f"{path}: uses `by` delegation but does not import androidx.compose.runtime.getValue")
        bad += 1
    if re.search(r"\bvar \w+ by ", body) and "androidx.compose.runtime.setValue" not in imports:
        print(f"{path}: uses `var ... by` but does not import androidx.compose.runtime.setValue")
        bad += 1
print(f"\n{bad} missing import(s)" if bad else "\nno missing imports")
sys.exit(1 if bad else 0)
