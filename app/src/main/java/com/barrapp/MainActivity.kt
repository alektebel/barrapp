package com.barrapp

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import com.barrapp.ui.BarrappApp
import com.barrapp.ui.theme.BarrappTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Tiza is a light design: dark bar icons on the paper ground, whatever
        // the system theme says.
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.light(0xFFF1EEE6.toInt(), 0xFFF1EEE6.toInt()),
            navigationBarStyle = SystemBarStyle.light(0xFFF1EEE6.toInt(), 0xFFF1EEE6.toInt()),
        )
        setContent {
            BarrappTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    BarrappApp()
                }
            }
        }
    }
}
