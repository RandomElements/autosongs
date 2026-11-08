/*
 * A very small JNI layer over LAME, the MP3 encoder.
 *
 * Android has no MP3 encoder of its own: MediaCodec can decode MP3, but it
 * cannot produce one, so there is no way to re-encode to MP3 with the
 * platform alone. LAME is a small LGPL library that does exactly that, and
 * this file is the whole of the glue between it and the app.
 *
 * The result is one shared library, about 400 KB per device type, against
 * the 30 MB that bundling all of ffmpeg would cost.
 *
 * LAME is licensed under the LGPL 2.0. See LAME-LICENSE.txt and the note
 * in the app's licences screen.
 */
#include <jni.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "lame.h"

extern "C" {

/* Turns the samples into MP3 bytes. The handle is a lame_t. */
JNIEXPORT jlong JNICALL
Java_com_autosongs_ytdl_audio_LameEncoder_nativeOpen(JNIEnv *env, jobject obj,
                                                    jint sample_rate, jint channels,
                                                    jint bitrate, jstring title,
                                                    jstring artist, jstring album,
                                                    jbyteArray artwork)
{
    lame_t lame = lame_init();
    if (lame == NULL) {
        return 0;
    }

    lame_set_in_samplerate(lame, sample_rate);
    lame_set_num_channels(lame, channels);
    lame_set_brate(lame, bitrate);
    /* Quality 2 is the usual "good enough, fast" setting. */
    lame_set_quality(lame, 2);
    lame_set_mode(lame, channels == 1 ? MONO : JOINT_STEREO);
    lame_set_VBR(lame, vbr_off);

    /* The tag is written by hand, so LAME must not add one of its own.
     * This has to come after lame_init_params, which turns it back on. */
    lame_set_write_id3tag_automatic(lame, 0);

    /* Without this, LAME writes only a v1 tag and the v2 tag comes back
     * empty. */
    id3tag_add_v2(lame);

    /* The tags have to be in place before the parameters are worked out,
     * because that is when LAME builds the tag. */
    if (title != NULL) {
        const char *value = env->GetStringUTFChars(title, NULL);
        if (value != NULL) {
            id3tag_set_title(lame, value);
            env->ReleaseStringUTFChars(title, value);
        }
    }
    if (artist != NULL) {
        const char *value = env->GetStringUTFChars(artist, NULL);
        if (value != NULL) {
            id3tag_set_artist(lame, value);
            env->ReleaseStringUTFChars(artist, value);
        }
    }
    if (album != NULL) {
        const char *value = env->GetStringUTFChars(album, NULL);
        if (value != NULL) {
            id3tag_set_album(lame, value);
            env->ReleaseStringUTFChars(album, value);
        }
    }
    if (artwork != NULL) {
        jsize length = env->GetArrayLength(artwork);
        if (length > 0) {
            jbyte *bytes = env->GetByteArrayElements(artwork, NULL);
            if (bytes != NULL) {
                id3tag_set_albumart(lame, (const char *)bytes, (size_t)length);
                env->ReleaseByteArrayElements(artwork, bytes, JNI_ABORT);
            }
        }
    }

    if (lame_init_params(lame) < 0) {
        lame_close(lame);
        return 0;
    }
    /* lame_init_params turns the automatic tag back on. */
    lame_set_write_id3tag_automatic(lame, 0);

    return (jlong)(intptr_t)lame;
}

/* Encodes one buffer of 16 bit samples and returns the MP3 bytes. */
JNIEXPORT jbyteArray JNICALL
Java_com_autosongs_ytdl_audio_LameEncoder_nativeEncode(JNIEnv *env, jobject obj,
                                                      jlong handle, jshortArray pcm,
                                                      jint samples)
{
    lame_t lame = (lame_t)(intptr_t)handle;
    if (lame == NULL || samples <= 0) {
        return env->NewByteArray(0);
    }

    /* LAME counts frames - samples per channel - and not the values in
     * the buffer. The caller hands over the values, so the frames are
     * worked out here, in the one place that knows what LAME wants.
     *
     * Getting this wrong is not a small mistake: for a stereo track it
     * makes LAME believe the track is twice as long as it is, and the
     * second half of every buffer is read from past the end of the
     * array. The track comes out twice as long and full of noise. */
    int channels = lame_get_num_channels(lame);
    if (channels < 1) {
        channels = 1;
    }
    int frames = samples / channels;
    if (frames <= 0) {
        return env->NewByteArray(0);
    }

    jshort *data = env->GetShortArrayElements(pcm, NULL);
    if (data == NULL) {
        return NULL;
    }

    /* LAME asks for 1.25 bytes per frame plus a good margin. */
    int size = (int)(1.25 * (double)frames) + 7200 + 65536;
    unsigned char *out = (unsigned char *)malloc((size_t)size);
    if (out == NULL) {
        env->ReleaseShortArrayElements(pcm, data, JNI_ABORT);
        return NULL;
    }

    int written = lame_encode_buffer_interleaved(lame, data, frames, out, size);
    env->ReleaseShortArrayElements(pcm, data, JNI_ABORT);

    if (written < 0) {
        free(out);
        return env->NewByteArray(0);
    }
    jbyteArray result = env->NewByteArray(written);
    if (result != NULL && written > 0) {
        env->SetByteArrayRegion(result, 0, written, (const jbyte *)out);
    }
    free(out);
    return result;
}

/* Finishes the file and returns the last bytes. */
JNIEXPORT jbyteArray JNICALL
Java_com_autosongs_ytdl_audio_LameEncoder_nativeFlush(JNIEnv *env, jobject obj,
                                                     jlong handle)
{
    lame_t lame = (lame_t)(intptr_t)handle;
    if (lame == NULL) {
        return env->NewByteArray(0);
    }
    unsigned char out[65536];
    /* flush, not flush_nogap: a gap would put a hole in the middle of the
     * track. */
    int written = lame_encode_flush(lame, out, (int)sizeof(out));
    if (written < 0) {
        return env->NewByteArray(0);
    }
    jbyteArray result = env->NewByteArray(written);
    if (result != NULL && written > 0) {
        env->SetByteArrayRegion(result, 0, written, (const jbyte *)out);
    }
    return result;
}

/* The ID3v2 tag that goes at the front of the file. */
JNIEXPORT jbyteArray JNICALL
Java_com_autosongs_ytdl_audio_LameEncoder_nativeId3Tag(JNIEnv *env, jobject obj,
                                                       jlong handle)
{
    lame_t lame = (lame_t)(intptr_t)handle;
    if (lame == NULL) {
        return env->NewByteArray(0);
    }
    size_t needed = lame_get_id3v2_tag(lame, NULL, 0);
    if (needed == 0) {
        return env->NewByteArray(0);
    }
    unsigned char *buffer = (unsigned char *)malloc(needed);
    if (buffer == NULL) {
        return env->NewByteArray(0);
    }
    size_t got = lame_get_id3v2_tag(lame, buffer, needed);
    jbyteArray result = env->NewByteArray((jsize)got);
    if (result != NULL && got > 0) {
        env->SetByteArrayRegion(result, 0, (jsize)got, (const jbyte *)buffer);
    }
    free(buffer);
    return result;
}

JNIEXPORT void JNICALL
Java_com_autosongs_ytdl_audio_LameEncoder_nativeClose(JNIEnv *env, jobject obj,
                                                      jlong handle)
{
    lame_t lame = (lame_t)(intptr_t)handle;
    if (lame != NULL) {
        lame_close(lame);
    }
}

} /* extern "C" */
