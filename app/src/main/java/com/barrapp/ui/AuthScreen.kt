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
                AuthStep.SignIn -> "Inicia sesión"
                AuthStep.SignUp -> "Crea una cuenta"
                AuthStep.Confirm -> "Revisa tu correo"
                AuthStep.Forgot -> "Restablece tu contraseña"
                AuthStep.Reset -> "Elige una contraseña nueva"
            },
            style = MaterialTheme.typography.displaySmall,
        )
        Spacer(Modifier.height(8.dp))
        Text(
            when (step) {
                AuthStep.SignIn ->
                    "Tus sesiones van con la cuenta, así que un teléfono nuevo continúa donde lo dejaste."
                AuthStep.SignUp ->
                    "Ocho caracteres o más, con una letra y un número."
                AuthStep.Confirm ->
                    "Hemos enviado un código a $email. Introdúcelo para terminar."
                AuthStep.Forgot ->
                    "Te enviaremos un código por correo para fijar una contraseña nueva."
                AuthStep.Reset ->
                    "Introduce el código de tu correo y la contraseña nueva."
            },
            style = MaterialTheme.typography.bodyMedium,
        )
        Spacer(Modifier.height(24.dp))

        if (step != AuthStep.Confirm && step != AuthStep.Reset) {
            OutlinedTextField(
                value = email,
                onValueChange = { email = it.trim() },
                label = { Text("Correo electrónico") },
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
                label = { Text("Contraseña") },
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
                label = { Text("Código") },
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
                label = { Text("Contraseña nueva") },
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
                    AuthStep.SignIn -> "Iniciar sesión"
                    AuthStep.SignUp -> "Crear cuenta"
                    AuthStep.Confirm -> "Confirmar"
                    AuthStep.Forgot -> "Enviarme un código"
                    AuthStep.Reset -> "Fijar contraseña"
                }
            )
        }

        Spacer(Modifier.height(8.dp))
        when (step) {
            AuthStep.SignIn -> {
                TextButton(onClick = { onStep(AuthStep.SignUp) }) {
                    Text("¿Aún no tienes cuenta? Crea una")
                }
                TextButton(onClick = { onStep(AuthStep.Forgot) }) {
                    Text("¿Has olvidado la contraseña?")
                }
            }
            AuthStep.SignUp -> TextButton(onClick = { onStep(AuthStep.SignIn) }) {
                Text("¿Ya tienes cuenta? Inicia sesión")
            }
            AuthStep.Confirm -> TextButton(onClick = { onResend(email) }) {
                Text("Reenviar el código")
            }
            AuthStep.Forgot -> TextButton(onClick = { onStep(AuthStep.Reset) }) {
                Text("Ya tengo un código")
            }
            AuthStep.Reset -> TextButton(onClick = { onStep(AuthStep.SignIn) }) {
                Text("Volver a iniciar sesión")
            }
        }

        if (onSkip != null) {
            TextButton(onClick = onSkip, modifier = Modifier.fillMaxWidth()) {
                Text("Ahora no: seguir entrenando en este teléfono")
            }
        }
    }
}
