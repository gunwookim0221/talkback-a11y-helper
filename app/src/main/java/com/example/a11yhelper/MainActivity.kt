package com.example.a11yhelper

import android.os.Bundle
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

class MainActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val messageView = TextView(this).apply {
            text = getString(R.string.main_message)
            textSize = 18f
            setPadding(48, 96, 48, 96)
        }
        setContentView(messageView)
    }
}
