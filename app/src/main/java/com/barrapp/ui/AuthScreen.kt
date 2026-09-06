package com.barrapp.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp

/** Where the account screen is in its own little flow. */
enum class AuthStep { SignIn, SignUp, Confirm, Forgot, Reset }

/**
 * Email and password, so a phone is not the only copy of someone's training.
 *
 * Staying anonymous is a first-class choice here, not a dismissal: the device
 * id already identifies a history, and an account is what makes that history
 * survive a lost phone. So "Not now" is a button, not fine print.
 */
@Composable
fun AuthScreen(
    step: AuthStep,
    busy: Boolean,
    error: String?,
    notice: String?,
    onStep: (AuthStep) -> Unit,
    onSignIn: (String, String) -> Unit,
    onSignUp: (String, String) -> Unit,
    onConfirm: (String, String) -> Unit,
    onResend: (String) -> Unit,
    onForgot: (String) -> Unit,
    onReset: (String, String, String) -> Unit,
    onSkip: (() -> Unit)?,
) {
    var email by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var code by remember { mutableStateOf("") }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Text(
            when (step) {
                AuthStep.SignIn -> "Sign in"
                AuthStep.SignUp -> "Create an account"
                AuthStep.Confirm -> "Check your email"
                AuthStep.Forgot -> "Reset your password"
                AuthStep.Reset -> "Choose a new password"
            },
            style = MaterialTheme.typography.displaySmall,
        )
        Spacer(Modifier.height(8.dp))
        Text(
            when (step) {
                AuthStep.SignIn ->
                    "Your sessions follow the account, so a new phone starts where you left off."
                AuthStep.SignUp ->
                    "Eight characters or more, with a letter and a number."
                AuthStep.Confirm ->
                    "We sent a code to $email. Enter it to finish."
                AuthStep.Forgot ->
                    "We will email you a code to set a new password."
                AuthStep.Reset ->
                    "Enter the code from your email and the new password."
            },
            style = MaterialTheme.typography.bodyMedium,
        )
        Spacer(Modifier.height(24.dp))

        if (step != AuthStep.Confirm && step != AuthStep.Reset) {
            OutlinedTextField(
                value = email,
                onValueChange = { email = it.trim() },
                label = { Text("Email") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(
                    keyboardType = KeyboardType.Email, imeAction = ImeAction.Next),
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(12.dp))
        }

        if (step == AuthStep.SignIn || step == AuthStep.SignUp) {
            OutlinedTextField(
                value = password,
                onValueChange = { password = it },
                label = { Text("Password") },
                singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(
                    keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
                modifier = Modifier.fillMaxWidth(),
            )
        }

        if (step == AuthStep.Confirm || step == AuthStep.Reset) {
            OutlinedTextField(
                value = code,
                onValueChange = { code = it.trim() },
                label = { Text("Code") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(
                    keyboardType = KeyboardType.Number, imeAction = ImeAction.Next),
                modifier = Modifier.fillMaxWidth(),
            )
        }

        if (step == AuthStep.Reset) {
            Spacer(Modifier.height(12.dp))
            OutlinedTextField(
                value = password,
                onValueChange = { password = it },
                label = { Text("New password") },
                singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(
                    keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
                modifier = Modifier.fillMaxWidth(),
            )
        }

        if (error != null) {
            Spacer(Modifier.height(12.dp))
            Text(error, style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.error)
        }
        if (notice != null) {
            Spacer(Modifier.height(12.dp))
            Text(notice, style = MaterialTheme.typography.bodyMedium)
        }

        Spacer(Modifier.height(20.dp))
        Button(
            onClick = {
                when (step) {
                    AuthStep.SignIn -> onSignIn(email, password)
                    AuthStep.SignUp -> onSignUp(email, password)
                    AuthStep.Confirm -> onConfirm(email, code)
                    AuthStep.Forgot -> onForgot(email)
                    AuthStep.Reset -> onReset(email, code, password)
                }
            },
            enabled = !busy && when (step) {
                AuthStep.SignIn, AuthStep.SignUp ->
                    email.contains("@") && password.length >= 8
                AuthStep.Confirm -> code.isNotBlank()
                AuthStep.Forgot -> email.contains("@")
                AuthStep.Reset -> code.isNotBlank() && password.length >= 8
            },
            modifier = Modifier.fillMaxWidth(),
        ) {
            if (busy) CircularProgressIndicator(Modifier.height(18.dp))
            else Text(
                when (step) {
                    AuthStep.SignIn -> "Sign in"
                    AuthStep.SignUp -> "Create account"
                    AuthStep.Confirm -> "Confirm"
                    AuthStep.Forgot -> "Email me a code"
                    AuthStep.Reset -> "Set password"
                }
            )
        }

        Spacer(Modifier.height(8.dp))
        when (step) {
            AuthStep.SignIn -> {
                TextButton(onClick = { onStep(AuthStep.SignUp) }) {
                    Text("No account yet? Create one")
                }
                TextButton(onClick = { onStep(AuthStep.Forgot) }) {
                    Text("Forgot your password?")
                }
            }
            AuthStep.SignUp -> TextButton(onClick = { onStep(AuthStep.SignIn) }) {
                Text("Already have an account? Sign in")
            }
            AuthStep.Confirm -> TextButton(onClick = { onResend(email) }) {
                Text("Send the code again")
            }
            AuthStep.Forgot -> TextButton(onClick = { onStep(AuthStep.Reset) }) {
                Text("I already have a code")
            }
            AuthStep.Reset -> TextButton(onClick = { onStep(AuthStep.SignIn) }) {
                Text("Back to sign in")
            }
        }

        if (onSkip != null) {
            TextButton(onClick = onSkip, modifier = Modifier.fillMaxWidth()) {
                Text("Not now — keep training on this phone")
            }
        }
    }
}
