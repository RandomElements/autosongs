# The MP3 encoder is reached from Java code by name - the name is baked
# into the native library, so renaming it would break it.
-keep class com.autosongs.ytdl.audio.LameEncoder { *; }

# The services are named in the manifest and started by the system.
-keep class com.autosongs.ytdl.media.MediaSessionListenerService { *; }
-keep class com.autosongs.ytdl.download.WatcherService { *; }

# Chaquopy looks these up by name at runtime.
-keep class com.chaquo.python.** { *; }
-keep class com.autosongs.ytdl.bridge.** { *; }
