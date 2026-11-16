package __PACKAGE_NAME__

import org.junit.Assert.assertEquals
import org.junit.Test

class AppIdentityTest {
    @Test
    fun generatedIdentityIsPresent() {
        assertEquals("__DISPLAY_NAME__", AppIdentity.DISPLAY_NAME)
    }
}
