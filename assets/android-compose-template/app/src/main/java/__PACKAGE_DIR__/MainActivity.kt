package __PACKAGE_NAME__

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import __PACKAGE_NAME__.ui.theme.DesignPactTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            DesignPactTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    // The first approved L2 screen is composed only after its design contract exists.
                }
            }
        }
    }
}
