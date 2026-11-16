package __PACKAGE_NAME__.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable

private val LightColors = lightColorScheme(
    background = NeutralSurface,
    onBackground = NeutralOnSurface,
    surface = NeutralSurface,
    onSurface = NeutralOnSurface,
    outline = NeutralOutline,
)

@Composable
fun DesignPactTheme(
    content: @Composable () -> Unit,
) {
    MaterialTheme(
        // Dark mode is enabled only when an approved design contract requires it.
        colorScheme = LightColors,
        typography = DesignPactTypography,
        content = content,
    )
}
