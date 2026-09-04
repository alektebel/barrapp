package com.barrapp.ui

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.barrapp.data.ActivityLevel
import com.barrapp.data.Profile
import com.barrapp.ui.parts.Eyebrow

/**
 * Three questions, one per screen.
 *
 * One question at a time rather than a form, because a form of three fields
 * reads as paperwork and this is the first thing anyone sees. Each step can be
 * gone back to, nothing is mandatory-looking, and the copy says what the answer
 * is for - people give better answers when they know why you asked.
 */
@Composable
fun Onboarding(
    initial: Profile,
    onDone: (Profile) -> Unit,
    modifier: Modifier = Modifier,
    onObjectives: (() -> Unit)? = null,
) {
    var step by remember { mutableIntStateOf(0) }
    var name by remember { mutableStateOf(initial.name) }
    var age by remember { mutableStateOf(if (initial.age > 0) initial.age.toString() else "") }
    var activity by remember { mutableStateOf(initial.activity) }

    val ageValue = age.toIntOrNull() ?: 0
    val canAdvance = when (step) {
        0 -> name.isNotBlank()
        1 -> ageValue in 10..100
        else -> activity != ActivityLevel.Unset
    }

    Box(modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
        Column(
            Modifier
                .align(Alignment.Center)
                .widthIn(max = 460.dp)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 28.dp, vertical = 32.dp)
        ) {
            Eyebrow("Step ${step + 1} of 3")
            Spacer(Modifier.height(20.dp))

            AnimatedContent(
                targetState = step,
                transitionSpec = {
                    val forward = targetState > initialState
                    val width = if (forward) 1 else -1
                    (slideInHorizontally(tween(280)) { w -> width * w / 3 } + fadeIn(tween(280)))
                        .togetherWith(
                            slideOutHorizontally(tween(280)) { w -> -width * w / 3 } + fadeOut(tween(180))
                        )
                },
                label = "onboarding",
            ) { current ->
                when (current) {
                    0 -> Column {
                        Text("What should we call you?", style = MaterialTheme.typography.displaySmall)
                        Spacer(Modifier.height(10.dp))
                        Text(
                            "Used to address you in the app. It never leaves this phone.",
                            style = MaterialTheme.typography.bodyLarge,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Spacer(Modifier.height(24.dp))
                        OutlinedTextField(
                            value = name,
                            onValueChange = { name = it.take(40) },
                            label = { Text("Name") },
                            singleLine = true,
                            shape = RoundedCornerShape(12.dp),
                            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }

                    1 -> Column {
                        Text("How old are you?", style = MaterialTheme.typography.displaySmall)
                        Spacer(Modifier.height(10.dp))
                        Text(
                            "It changes nothing about the measurement — every number here is " +
                                "compared against your own previous reps, never against a " +
                                "population average. It only shapes how the app talks to you.",
                            style = MaterialTheme.typography.bodyLarge,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Spacer(Modifier.height(24.dp))
                        OutlinedTextField(
                            value = age,
                            onValueChange = { entered -> age = entered.filter { it.isDigit() }.take(3) },
                            label = { Text("Age") },
                            singleLine = true,
                            shape = RoundedCornerShape(12.dp),
                            keyboardOptions = KeyboardOptions(
                                keyboardType = KeyboardType.Number,
                                imeAction = ImeAction.Done,
                            ),
                            supportingText = {
                                if (age.isNotBlank() && ageValue !in 10..100) {
                                    Text("Somewhere between 10 and 100.")
                                }
                            },
                            isError = age.isNotBlank() && ageValue !in 10..100,
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }

                    else -> Column {
                        Text("How often do you train?", style = MaterialTheme.typography.displaySmall)
                        Spacer(Modifier.height(10.dp))
                        Text(
                            "Sets how many reps a session should aim for. Three is the floor " +
                                "for any comparison at all.",
                            style = MaterialTheme.typography.bodyLarge,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Spacer(Modifier.height(20.dp))
                        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                            ActivityLevel.entries.filter { it != ActivityLevel.Unset }.forEach { level ->
                                ActivityOption(
                                    level = level,
                                    selected = activity == level,
                                    onSelect = { activity = level },
                                )
                            }
                        }
                    }
                }
            }

            Spacer(Modifier.height(32.dp))
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                if (step > 0) {
                    TextButton(onClick = { step -= 1 }) { Text("Back") }
                } else {
                    Spacer(Modifier.size(1.dp))
                }
                Button(
                    onClick = {
                        if (step < 2) {
                            step += 1
                        } else {
                            onDone(Profile(name.trim(), ageValue, activity))
                        }
                    },
                    enabled = canAdvance,
                    shape = RoundedCornerShape(12.dp),
                ) {
                    Text(if (step < 2) "Continue" else "Start training")
                }
            }

            if (onObjectives != null) {
                Spacer(Modifier.height(14.dp))
                TextButton(onClick = onObjectives, modifier = Modifier.fillMaxWidth()) {
                    Text("Or set up your goals in a chat instead")
                }
            }
        }
    }
}

@Composable
private fun ActivityOption(
    level: ActivityLevel,
    selected: Boolean,
    onSelect: () -> Unit,
) {
    val border = if (selected) MaterialTheme.colorScheme.primary
    else MaterialTheme.colorScheme.outline
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(
                if (selected) MaterialTheme.colorScheme.primary.copy(alpha = 0.08f)
                else MaterialTheme.colorScheme.surface
            )
            .border(
                width = if (selected) 2.dp else 1.dp,
                color = border,
                shape = RoundedCornerShape(14.dp),
            )
            .clickable(onClick = onSelect)
            .padding(horizontal = 16.dp, vertical = 14.dp)
    ) {
        Text(level.label, style = MaterialTheme.typography.titleMedium)
        Text(
            level.detail,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
