package com.ning.chinese;

import org.junit.Test;

public final class PlaybackCoreJUnitTest {
    @Test public void ringAndDurableSpool() throws Exception {
        PlaybackCoreTest.main(new String[0]);
        PlaybackDrainTest.main(new String[0]);
    }
}
