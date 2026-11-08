# The bridge is Python that calls into this app's Java, and the Python
# side looks these classes up by name at runtime.
-keep class com.autosongs.bridge.** { *; }
-keep class com.chaquo.python.** { *; }
-keep class com.chaquo.python.android.AndroidPlatform { *; }
-dontwarn com.chaquo.python.**
