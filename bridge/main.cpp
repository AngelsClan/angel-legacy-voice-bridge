// Angel Legacy Voice Bridge: SAPI 5 speech through an offline virtual COM port.
// No networking, shell commands, external XML, or speech-content logging.
#define WINVER 0x0501
#define _WIN32_WINNT 0x0501
#define _SAPI_VER 0x51
#include <windows.h>
#include <shellapi.h>
#include <initguid.h>
#include <sapi.h>
#include <mmsystem.h>
#include <mmddk.h>

namespace {
const unsigned int MAX_LINE = 8192;
const unsigned int MAX_TEXT = 512;
const unsigned int MAX_VOICES = 128;
const DWORD HEARTBEAT_TIMEOUT = 6000;

// Audio routing. The helper always starts a connection playing through the XP
// sound card, so an add-on that never sends ROUTE behaves exactly as before.
const unsigned int ROUTE_XP = 0;
const unsigned int ROUTE_NVDA = 1;
const unsigned int ROUTE_BOTH = 2;
// Local playback for the Both route. Sixteen buffers of 8 KiB is about 2.9
// seconds at 22.05 kHz: enough to ride out scheduling, small enough to bound.
const unsigned int PLAYBACK_BUFFERS = 16;
const unsigned int PLAYBACK_BUFFER_BYTES = 8192;
// One second and a half of 22.05 kHz 16-bit mono. Bounded on purpose: when the
// link cannot keep up, SAPI is made to wait rather than the helper growing.
const unsigned int AUDIO_RING = 65536;
const unsigned int AUDIO_FRAME_BYTES = 2048;
const unsigned int AUDIO_FRAMES_PER_TURN = 8;
const unsigned int AUDIO_LINE = 4096;
// Never let a stalled reader hold the SAPI rendering thread for good.
const DWORD AUDIO_WRITE_TIMEOUT = 5000;
// Leave the virtual UART room for control messages behind queued audio.
const DWORD AUDIO_TX_QUEUE_LIMIT = 8192;
const unsigned int AUDIO_FALLBACK_RATE = 22050;

HANDLE serialPort = INVALID_HANDLE_VALUE;
ISpVoice* voice = NULL;
ISpObjectToken* voices[MAX_VOICES] = {};
WCHAR* voiceIds[MAX_VOICES] = {};
WCHAR* voiceNames[MAX_VOICES] = {};
bool catalogChanged = false;
unsigned int voiceCount = 0;
int selectedVoice = -1;
char session[33] = {};
unsigned int generation = 0;
unsigned int requestId = 0;
bool speaking = false;
bool paused = false;
bool serialFault = false;
unsigned int protocolVersion = 1;
bool assembling = false;
bool batchSpeech = false;
bool endInputSeen = false;
ULONG activeStream = 0;
unsigned int batchVoice = 0;
unsigned int batchQuality = 0;
int selectedQuality = -1;
const unsigned int MAX_XML = 131072;
WCHAR utteranceXml[MAX_XML];
unsigned int xmlUsed = 0;
bool styleOpen = false;
unsigned int styleRate = 10, styleVolume = 100, stylePitch = 10, styleSpell = 0;
volatile LONG stopping = 0;
DWORD lastContact = 0;
char incoming[MAX_LINE];
char outgoing[MAX_LINE];
WCHAR speechText[MAX_TEXT];
WCHAR speechXml[MAX_TEXT * 16 + 100];

// Audio capture state. Only the ring and the sink counters are touched by the
// SAPI rendering thread; everything else belongs to the single main loop.
unsigned int audioRoute = ROUTE_XP;
int appliedRoute = -1;
unsigned int requestedQuality = 0;
bool routedCapture = false;
bool pendingDone = false;
bool audioFormatSent = false;
unsigned int audioSequence = 0;
unsigned int nativeRate[MAX_VOICES] = {};
unsigned int nativeChannels[MAX_VOICES] = {};
// The format named at bind time. SAPI is not allowed to change it, so this is
// the truth about the captured PCM and nothing has to ask the stream for it.
unsigned int captureRate = 0;
unsigned int captureBits = 0;
unsigned int captureChannels = 0;
// A recovery check must never be heard. Some engines, notably the AT&T voices,
// still produce roughly a fifth of full level at SAPI volume zero, so silence
// cannot be arranged by turning the voice down: the audio has to be kept away
// from the sound card entirely and measured instead.
bool batchProbe = false;
bool probeUtterance = false;
bool suppressFrames = false;
unsigned int probeBytes = 0;
bool probeNonSilent = false;
ISpStream* captureStream = NULL;
CRITICAL_SECTION audioLock;
char audioRing[AUDIO_RING];
char audioLine[AUDIO_LINE];
unsigned int ringStart = 0;
unsigned int ringUsed = 0;
ULONGLONG sinkWritten = 0;
ULONGLONG sinkPosition = 0;
unsigned int seekAnomalies = 0;
unsigned int writeTimeouts = 0;
volatile LONG sinkWriteAborts = 0;
volatile LONG captureAbort = 1;
volatile LONG captureAbortReason = 0;

// Local playback of the captured PCM, used only by the Both route. This opens
// one ordinary wave output stream; it never touches the mixer, never mutes and
// never changes any level, so the machine's other sounds continue unaffected.
struct PlaybackBuffer {
    WAVEHDR header;
    char data[PLAYBACK_BUFFER_BYTES];
    bool queued;
};
HWAVEOUT playbackDevice = NULL;
PlaybackBuffer playbackBuffers[PLAYBACK_BUFFERS];
unsigned int playbackRate = 0;
unsigned int playbackChannels = 0;
unsigned int playbackUnderruns = 0;

void logMessage(const char* message) {
    DWORD written;
    WriteFile(GetStdHandle(STD_OUTPUT_HANDLE), message, lstrlenA(message), &written, NULL);
    WriteFile(GetStdHandle(STD_OUTPUT_HANDLE), "\r\n", 2, &written, NULL);
}

bool sendLine(const char* line) {
    if (serialFault) return false;
    DWORD length = lstrlenA(line), written = 0;
    // The host discards anything longer than its own line bound, so a helper
    // line that grew past it would desynchronise the stream instead of failing.
    if (length >= MAX_LINE) {
        logMessage("Refused to send an over-long line.");
        return false;
    }
    if (!WriteFile(serialPort, line, length, &written, NULL) || written != length ||
        !WriteFile(serialPort, "\n", 1, &written, NULL) || written != 1) {
        serialFault = true;
        return false;
    }
    return true;
}

bool parseNumber(const char* text, unsigned int maximum, unsigned int& result) {
    if (!*text) return false;
    result = 0;
    for (; *text; ++text) {
        if (*text < '0' || *text > '9') return false;
        unsigned int digit = *text - '0';
        if (result > maximum / 10 || (result == maximum / 10 && digit > maximum % 10)) return false;
        result = result * 10 + digit;
    }
    return true;
}

int hexDigit(char value) {
    if (value >= '0' && value <= '9') return value - '0';
    if (value >= 'a' && value <= 'f') return value - 'a' + 10;
    return -1;
}

bool validSession(const char* value) {
    if (lstrlenA(value) != 32) return false;
    for (unsigned int i = 0; i < 32; ++i) if (hexDigit(value[i]) < 0) return false;
    return true;
}

bool decodeText(const char* input) {
    unsigned int size = lstrlenA(input);
    if (!size || size % 4 || size / 4 >= MAX_TEXT) return false;
    for (unsigned int i = 0; i < size / 4; ++i) {
        int a = hexDigit(input[i * 4]), b = hexDigit(input[i * 4 + 1]);
        int c = hexDigit(input[i * 4 + 2]), d = hexDigit(input[i * 4 + 3]);
        if (a < 0 || b < 0 || c < 0 || d < 0) return false;
        WCHAR value = static_cast<WCHAR>((a * 16 + b) | ((c * 16 + d) << 8));
        if (value < 32 && value != 9 && value != 10 && value != 13) return false;
        if (value == 0xFFFE || value == 0xFFFF) return false;
        speechText[i] = value;
    }
    speechText[size / 4] = 0;
    for (unsigned int i = 0; i < size / 4; ++i) {
        WCHAR value = speechText[i];
        if (value >= 0xD800 && value <= 0xDBFF) {
            WCHAR low = speechText[++i];
            if (low < 0xDC00 || low > 0xDFFF) return false;
        } else if (value >= 0xDC00 && value <= 0xDFFF) return false;
    }
    return true;
}

void encodeName(const WCHAR* name, char* destination, unsigned int capacity) {
    const char* digits = "0123456789abcdef";
    unsigned int offset = 0;
    while (*name && offset + 4 < capacity) {
        if (*name >= 0xD800 && *name <= 0xDBFF && offset + 8 >= capacity) break;
        unsigned int value = *name++;
        destination[offset++] = digits[(value >> 4) & 15];
        destination[offset++] = digits[value & 15];
        destination[offset++] = digits[(value >> 12) & 15];
        destination[offset++] = digits[(value >> 8) & 15];
    }
    destination[offset] = 0;
}

// Base64 keeps audio frames inside the existing tab-separated ASCII framing at
// four characters per three bytes, where the protocol's hex would cost six.
unsigned int encodeBase64(const char* data, unsigned int length, char* destination) {
    static const char digits[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    unsigned int offset = 0;
    for (unsigned int i = 0; i < length; i += 3) {
        unsigned int remaining = length - i;
        unsigned int group = static_cast<unsigned char>(data[i]) << 16;
        if (remaining > 1) group |= static_cast<unsigned char>(data[i + 1]) << 8;
        if (remaining > 2) group |= static_cast<unsigned char>(data[i + 2]);
        destination[offset++] = digits[(group >> 18) & 63];
        destination[offset++] = digits[(group >> 12) & 63];
        destination[offset++] = remaining > 1 ? digits[(group >> 6) & 63] : '=';
        destination[offset++] = remaining > 2 ? digits[group & 63] : '=';
    }
    destination[offset] = 0;
    return offset;
}

// ---------------------------------------------------------------------------
// Captured speech audio
//
// When the add-on asks for the NVDA route, SAPI writes into this sink instead
// of the XP sound card. The sink is the base stream of a SAPI SpStream object,
// which lets SAPI tell us the engine's own output format instead of forcing a
// rate and resampling. Other XP sounds are never touched.
//
// The sink is filled on SAPI's rendering thread and drained on the main loop,
// so only these functions take the lock, and nothing here writes to the serial
// port. The build has no C runtime startup, so the object is a plain struct
// with an explicit vtable rather than a class whose constructor would never run.
// ---------------------------------------------------------------------------

bool sameGuid(const GUID& left, const GUID& right) {
    const DWORD* a = reinterpret_cast<const DWORD*>(&left);
    const DWORD* b = reinterpret_cast<const DWORD*>(&right);
    return a[0] == b[0] && a[1] == b[1] && a[2] == b[2] && a[3] == b[3];
}

const GUID GUID_UNKNOWN = {0x00000000, 0x0000, 0x0000, {0xC0, 0, 0, 0, 0, 0, 0, 0x46}};
const GUID GUID_SEQUENTIAL_STREAM = {0x0c733a30, 0x2a1c, 0x11ce, {0xad, 0xe5, 0x00, 0xaa, 0x00, 0x44, 0x77, 0x3d}};
const GUID GUID_STREAM = {0x0000000c, 0x0000, 0x0000, {0xC0, 0, 0, 0, 0, 0, 0, 0x46}};

struct AudioSink;
struct AudioSinkVtbl {
    HRESULT (STDMETHODCALLTYPE* QueryInterface)(AudioSink*, REFIID, void**);
    ULONG (STDMETHODCALLTYPE* AddRef)(AudioSink*);
    ULONG (STDMETHODCALLTYPE* Release)(AudioSink*);
    HRESULT (STDMETHODCALLTYPE* Read)(AudioSink*, void*, ULONG, ULONG*);
    HRESULT (STDMETHODCALLTYPE* Write)(AudioSink*, const void*, ULONG, ULONG*);
    HRESULT (STDMETHODCALLTYPE* Seek)(AudioSink*, LARGE_INTEGER, DWORD, ULARGE_INTEGER*);
    HRESULT (STDMETHODCALLTYPE* SetSize)(AudioSink*, ULARGE_INTEGER);
    HRESULT (STDMETHODCALLTYPE* CopyTo)(AudioSink*, IStream*, ULARGE_INTEGER, ULARGE_INTEGER*, ULARGE_INTEGER*);
    HRESULT (STDMETHODCALLTYPE* Commit)(AudioSink*, DWORD);
    HRESULT (STDMETHODCALLTYPE* Revert)(AudioSink*);
    HRESULT (STDMETHODCALLTYPE* LockRegion)(AudioSink*, ULARGE_INTEGER, ULARGE_INTEGER, DWORD);
    HRESULT (STDMETHODCALLTYPE* UnlockRegion)(AudioSink*, ULARGE_INTEGER, ULARGE_INTEGER, DWORD);
    HRESULT (STDMETHODCALLTYPE* Stat)(AudioSink*, STATSTG*, DWORD);
    HRESULT (STDMETHODCALLTYPE* Clone)(AudioSink*, IStream**);
};
struct AudioSink { const AudioSinkVtbl* table; };

void captureRewind() {
    EnterCriticalSection(&audioLock);
    ringStart = 0;
    ringUsed = 0;
    sinkWritten = 0;
    sinkPosition = 0;
    seekAnomalies = 0;
    writeTimeouts = 0;
    InterlockedExchange(&sinkWriteAborts, 0);
    LeaveCriticalSection(&audioLock);
    audioSequence = 0;
    audioFormatSent = false;
    InterlockedExchange(&captureAbortReason, 0);
    InterlockedExchange(&captureAbort, 0);
}

// Release a blocked rendering thread before anything waits on SAPI itself.
void captureAbortNow(LONG reason) {
    InterlockedExchange(&captureAbortReason, reason);
    InterlockedExchange(&captureAbort, 1);
    EnterCriticalSection(&audioLock);
    ringStart = 0;
    ringUsed = 0;
    LeaveCriticalSection(&audioLock);
    routedCapture = false;
    pendingDone = false;
    // A cancelled check must not leave its measurement to be reported against
    // whatever speaks next.
    probeUtterance = false;
    suppressFrames = false;
}

bool captureEmpty() {
    EnterCriticalSection(&audioLock);
    bool empty = ringUsed == 0;
    LeaveCriticalSection(&audioLock);
    return empty;
}

// Take whole 4-byte blocks so a frame never splits a stereo sample pair; the
// final short remainder is only released once the engine has actually finished.
unsigned int captureTake(char* destination, unsigned int capacity, bool flushTail) {
    EnterCriticalSection(&audioLock);
    unsigned int available = ringUsed < capacity ? ringUsed : capacity;
    if (!flushTail) available -= available % 4;
    unsigned int firstSpan = AUDIO_RING - ringStart;
    if (firstSpan > available) firstSpan = available;
    memcpy(destination, audioRing + ringStart, firstSpan);
    if (available > firstSpan) memcpy(destination + firstSpan, audioRing, available - firstSpan);
    ringStart = (ringStart + available) % AUDIO_RING;
    ringUsed -= available;
    LeaveCriticalSection(&audioLock);
    return available;
}

HRESULT STDMETHODCALLTYPE sinkQueryInterface(AudioSink* self, REFIID id, void** result) {
    if (!result) return E_POINTER;
    if (sameGuid(id, GUID_UNKNOWN) || sameGuid(id, GUID_SEQUENTIAL_STREAM) || sameGuid(id, GUID_STREAM)) {
        *result = self;
        return S_OK;
    }
    *result = NULL;
    return E_NOINTERFACE;
}

// One process-lifetime singleton: reference counting would add no safety here.
ULONG STDMETHODCALLTYPE sinkAddRef(AudioSink*) { return 1; }
ULONG STDMETHODCALLTYPE sinkRelease(AudioSink*) { return 1; }

HRESULT STDMETHODCALLTYPE sinkRead(AudioSink*, void*, ULONG, ULONG* read) {
    if (read) *read = 0;
    return S_FALSE;
}

HRESULT STDMETHODCALLTYPE sinkWrite(AudioSink*, const void* data, ULONG count, ULONG* written) {
    if (written) *written = 0;
    if (!data && count) return E_POINTER;
    const char* bytes = static_cast<const char*>(data);
    ULONG done = 0;
    DWORD waitingSince = GetTickCount();
    while (done < count) {
        if (captureAbort) {
            InterlockedIncrement(&sinkWriteAborts);
            return E_ABORT;
        }
        EnterCriticalSection(&audioLock);
        unsigned int room = AUDIO_RING - ringUsed;
        unsigned int chunk = count - done < room ? count - done : room;
        unsigned int end = (ringStart + ringUsed) % AUDIO_RING;
        unsigned int firstSpan = AUDIO_RING - end;
        if (firstSpan > chunk) firstSpan = chunk;
        memcpy(audioRing + end, bytes + done, firstSpan);
        if (chunk > firstSpan) memcpy(audioRing, bytes + done + firstSpan, chunk - firstSpan);
        ringUsed += chunk;
        sinkWritten += chunk;
        sinkPosition += chunk;
        LeaveCriticalSection(&audioLock);
        done += chunk;
        if (done == count) break;
        // The ring is full: the link is slower than the engine. Waiting here
        // paces SAPI instead of dropping speech, but never without a bound.
        if (static_cast<DWORD>(GetTickCount() - waitingSince) > AUDIO_WRITE_TIMEOUT) {
            ++writeTimeouts;
            return E_ABORT;
        }
        if (chunk) waitingSince = GetTickCount();
        Sleep(1);
    }
    if (written) *written = done;
    return S_OK;
}

HRESULT STDMETHODCALLTYPE sinkSeek(AudioSink*, LARGE_INTEGER move, DWORD origin, ULARGE_INTEGER* result) {
    if (origin > STREAM_SEEK_END) return STG_E_INVALIDFUNCTION;
    EnterCriticalSection(&audioLock);
    LONGLONG base = origin == STREAM_SEEK_SET ? 0
                  : origin == STREAM_SEEK_CUR ? static_cast<LONGLONG>(sinkPosition)
                                              : static_cast<LONGLONG>(sinkWritten);
    LONGLONG target = base + move.QuadPart;
    bool valid = target >= 0;
    if (valid) {
        // Audio already handed to the host cannot be rewritten. Count any real
        // repositioning so a wrapper that patches a header is visible, not silent.
        if (static_cast<ULONGLONG>(target) != sinkPosition) ++seekAnomalies;
        sinkPosition = static_cast<ULONGLONG>(target);
    }
    if (result) result->QuadPart = sinkPosition;
    LeaveCriticalSection(&audioLock);
    return valid ? S_OK : STG_E_INVALIDFUNCTION;
}

HRESULT STDMETHODCALLTYPE sinkSetSize(AudioSink*, ULARGE_INTEGER) { return S_OK; }
HRESULT STDMETHODCALLTYPE sinkCopyTo(AudioSink*, IStream*, ULARGE_INTEGER, ULARGE_INTEGER*, ULARGE_INTEGER*) {
    return E_NOTIMPL;
}
HRESULT STDMETHODCALLTYPE sinkCommit(AudioSink*, DWORD) { return S_OK; }
HRESULT STDMETHODCALLTYPE sinkRevert(AudioSink*) { return S_OK; }
HRESULT STDMETHODCALLTYPE sinkLockRegion(AudioSink*, ULARGE_INTEGER, ULARGE_INTEGER, DWORD) {
    return STG_E_INVALIDFUNCTION;
}
HRESULT STDMETHODCALLTYPE sinkUnlockRegion(AudioSink*, ULARGE_INTEGER, ULARGE_INTEGER, DWORD) {
    return STG_E_INVALIDFUNCTION;
}

HRESULT STDMETHODCALLTYPE sinkStat(AudioSink*, STATSTG* status, DWORD) {
    if (!status) return E_POINTER;
    STATSTG empty = {};
    *status = empty;
    status->type = STGTY_STREAM;
    status->grfMode = STGM_WRITE;
    EnterCriticalSection(&audioLock);
    status->cbSize.QuadPart = sinkWritten;
    LeaveCriticalSection(&audioLock);
    return S_OK;
}

HRESULT STDMETHODCALLTYPE sinkClone(AudioSink*, IStream**) { return E_NOTIMPL; }

const AudioSinkVtbl audioSinkTable = {
    sinkQueryInterface, sinkAddRef, sinkRelease, sinkRead, sinkWrite, sinkSeek,
    sinkSetSize, sinkCopyTo, sinkCommit, sinkRevert, sinkLockRegion,
    sinkUnlockRegion, sinkStat, sinkClone
};
AudioSink audioSink = {&audioSinkTable};

IStream* sinkStream() { return reinterpret_cast<IStream*>(&audioSink); }

// ---------------------------------------------------------------------------
// Local playback for the Both route
//
// The captured PCM is played here as well as sent to the host. Buffers are
// recycled only once the device reports them finished, and the frame pump
// stops taking audio while none is free, so playback paces the whole path
// instead of anything being dropped. Nothing else on the machine is muted,
// ducked or re-levelled: this is one ordinary wave output stream.
// ---------------------------------------------------------------------------

void releaseFinishedBuffers() {
    if (!playbackDevice) return;
    for (unsigned int i = 0; i < PLAYBACK_BUFFERS; ++i) {
        PlaybackBuffer& buffer = playbackBuffers[i];
        if (buffer.queued && (buffer.header.dwFlags & WHDR_DONE)) {
            waveOutUnprepareHeader(playbackDevice, &buffer.header, sizeof(WAVEHDR));
            buffer.queued = false;
        }
    }
}

void closePlayback() {
    if (!playbackDevice) return;
    // Reset first: unpreparing a header the device still owns fails.
    waveOutReset(playbackDevice);
    for (unsigned int i = 0; i < PLAYBACK_BUFFERS; ++i) {
        PlaybackBuffer& buffer = playbackBuffers[i];
        if (buffer.queued) {
            waveOutUnprepareHeader(playbackDevice, &buffer.header, sizeof(WAVEHDR));
            buffer.queued = false;
        }
    }
    waveOutClose(playbackDevice);
    playbackDevice = NULL;
    playbackRate = 0;
    playbackChannels = 0;
}

// Discard whatever has not been heard yet. Used for cancellation only.
void resetPlayback() {
    if (!playbackDevice) return;
    waveOutReset(playbackDevice);
    releaseFinishedBuffers();
}

bool openPlayback(unsigned int rate, unsigned int channels) {
    if (playbackDevice && playbackRate == rate && playbackChannels == channels) return true;
    closePlayback();
    WAVEFORMATEX format = {};
    format.wFormatTag = WAVE_FORMAT_PCM;
    format.nChannels = static_cast<WORD>(channels);
    format.nSamplesPerSec = rate;
    format.wBitsPerSample = 16;
    format.nBlockAlign = static_cast<WORD>(channels * 2);
    format.nAvgBytesPerSec = rate * channels * 2;
    // WAVE_MAPPER is the machine's own default output, the same one the user's
    // other programs use. No device is taken exclusively.
    if (waveOutOpen(&playbackDevice, WAVE_MAPPER, &format, 0, 0, CALLBACK_NULL) != MMSYSERR_NOERROR) {
        playbackDevice = NULL;
        return false;
    }
    for (unsigned int i = 0; i < PLAYBACK_BUFFERS; ++i) playbackBuffers[i].queued = false;
    playbackRate = rate;
    playbackChannels = channels;
    return true;
}

// A buffer is available only when the device has finished with it.
PlaybackBuffer* freePlaybackBuffer() {
    releaseFinishedBuffers();
    for (unsigned int i = 0; i < PLAYBACK_BUFFERS; ++i)
        if (!playbackBuffers[i].queued) return &playbackBuffers[i];
    return NULL;
}

bool playbackHasRoom() { return freePlaybackBuffer() != NULL; }

bool playCapturedAudio(const char* data, unsigned int length) {
    if (!playbackDevice || length > PLAYBACK_BUFFER_BYTES) return false;
    PlaybackBuffer* buffer = freePlaybackBuffer();
    if (!buffer) return false;
    memcpy(buffer->data, data, length);
    WAVEHDR header = {};
    header.lpData = buffer->data;
    header.dwBufferLength = length;
    buffer->header = header;
    if (waveOutPrepareHeader(playbackDevice, &buffer->header, sizeof(WAVEHDR)) != MMSYSERR_NOERROR)
        return false;
    if (waveOutWrite(playbackDevice, &buffer->header, sizeof(WAVEHDR)) != MMSYSERR_NOERROR) {
        waveOutUnprepareHeader(playbackDevice, &buffer->header, sizeof(WAVEHDR));
        ++playbackUnderruns;
        return false;
    }
    buffer->queued = true;
    return true;
}

void stopSpeech(LONG reason = 1) {
    // Free the rendering thread first: it may be waiting for ring space, and
    // purging SAPI waits for that same thread to unwind.
    captureAbortNow(reason);
    // Cancellation must silence what the Both route has already queued.
    resetPlayback();
    if (voice) {
        voice->Speak(NULL, SPF_PURGEBEFORESPEAK, NULL);
        if (paused) voice->Resume();
    }
    paused = false;
    speaking = false;
    assembling = false;
    batchSpeech = false;
    endInputSeen = false;
    xmlUsed = 0;
    styleOpen = false;
}

void sendError(const char* code) {
    wsprintfA(outgoing, "ERROR\t%s\t%u\t%u\t%s", session, generation, requestId, code);
    sendLine(outgoing);
    logMessage(code);
}

// Fixed numeric diagnostics only: never retain utterances, token paths or names.
// Keep a small helper-side record even when an older add-on ignores SAPIERROR.
void reportSapiFailure(unsigned int stage, HRESULT result, unsigned int slot, unsigned int quality,
                       const SPVOICESTATUS* status = NULL, LONG abortBefore = -1,
                       LONG sinkAbortsBefore = -1, LONG abortReasonBefore = -1) {
    SYSTEMTIME now;
    GetLocalTime(&now);
    char record[256];
    wsprintfA(record, "%04u-%02u-%02u %02u:%02u:%02u stage=%u HRESULT=%08lX voice_slot=%u quality=%u route=%u write_timeouts=%u seeks=%u stream=%lu capture_abort=%ld abort_reason=%ld sink_aborts=%ld current_stream=%lu last_queued=%lu\r\n",
              now.wYear, now.wMonth, now.wDay, now.wHour, now.wMinute, now.wSecond,
              stage, static_cast<DWORD>(result), slot, quality, audioRoute,
              writeTimeouts, seekAnomalies, activeStream, abortBefore, abortReasonBefore, sinkAbortsBefore,
              status ? status->ulCurrentStream : 0, status ? status->ulLastStreamQueued : 0);
    WCHAR path[MAX_PATH];
    DWORD length = GetModuleFileNameW(NULL, path, MAX_PATH);
    if (length && length < MAX_PATH) {
        while (length && path[length - 1] != L'\\') --length;
        if (length && length < MAX_PATH - 32) {
            lstrcpyW(path + length, L"bridge-sapi-errors.log");
            HANDLE log = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
                                     NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
            if (log != INVALID_HANDLE_VALUE) {
                DWORD size = GetFileSize(log, NULL);
                if (size != INVALID_FILE_SIZE && size >= 1024 * 1024) SetEndOfFile(log);
                SetFilePointer(log, 0, NULL, FILE_END);
                DWORD written;
                WriteFile(log, record, lstrlenA(record), &written, NULL);
                CloseHandle(log);
            }
        }
    }
    wsprintfA(outgoing, "SAPIERROR\t%s\t%u\t%u\t%u\t%lu\t%u\t%u",
              session, generation, requestId, stage, static_cast<DWORD>(result), slot, quality);
    sendLine(outgoing);
}

bool maximizePlaybackLine(HMIXER mixer, const MIXERLINEW& line) {
    MIXERCONTROLW control = {};
    control.cbStruct = sizeof(control);
    MIXERLINECONTROLSW controls = {};
    controls.cbStruct = sizeof(controls);
    controls.dwLineID = line.dwLineID;
    controls.dwControlType = MIXERCONTROL_CONTROLTYPE_VOLUME;
    controls.cControls = 1;
    controls.cbmxctrl = sizeof(control);
    controls.pamxctrl = &control;
    HMIXEROBJ object = reinterpret_cast<HMIXEROBJ>(mixer);
    if (mixerGetLineControlsW(object, &controls, MIXER_GETLINECONTROLSF_ONEBYTYPE | MIXER_OBJECTF_HMIXER)
            != MMSYSERR_NOERROR || (control.fdwControl & (MIXERCONTROL_CONTROLF_DISABLED | MIXERCONTROL_CONTROLF_MULTIPLE)))
        return false;
    DWORD channels = control.fdwControl & MIXERCONTROL_CONTROLF_UNIFORM ? 1 : line.cChannels;
    if (!channels || channels > 32) return false;
    MIXERCONTROLDETAILS_UNSIGNED levels[32] = {};
    for (DWORD i = 0; i < channels; ++i) levels[i].dwValue = control.Bounds.dwMaximum;
    MIXERCONTROLDETAILS details = {};
    details.cbStruct = sizeof(details);
    details.dwControlID = control.dwControlID;
    details.cChannels = channels;
    details.cbDetails = sizeof(levels[0]);
    details.paDetails = levels;
    if (mixerSetControlDetails(object, &details, MIXER_SETCONTROLDETAILSF_VALUE | MIXER_OBJECTF_HMIXER)
            != MMSYSERR_NOERROR) return false;
    // Read back, rather than claiming a driver accepted settings it ignored.
    if (mixerGetControlDetailsW(object, &details, MIXER_GETCONTROLDETAILSF_VALUE | MIXER_OBJECTF_HMIXER)
            != MMSYSERR_NOERROR) return false;
    for (DWORD i = 0; i < channels; ++i)
        if (levels[i].dwValue != control.Bounds.dwMaximum) return false;
    return true;
}

const char* maximizePlaybackVolume() {
    DWORD device = WAVE_MAPPER, flags = 0;
    if (waveOutMessage(reinterpret_cast<HWAVEOUT>(static_cast<UINT_PTR>(WAVE_MAPPER)),
                       DRVM_MAPPER_PREFERRED_GET, reinterpret_cast<DWORD_PTR>(&device),
                       reinterpret_cast<DWORD_PTR>(&flags)) != MMSYSERR_NOERROR || device == WAVE_MAPPER)
        return "UNSUPPORTED";
    HMIXER mixer = NULL;
    if (mixerOpen(&mixer, device, 0, 0, MIXER_OBJECTF_WAVEOUT) != MMSYSERR_NOERROR)
        return "UNSUPPORTED";
    MIXERLINEW output = {};
    output.cbStruct = sizeof(output);
    output.dwComponentType = MIXERLINE_COMPONENTTYPE_DST_SPEAKERS;
    HMIXEROBJ object = reinterpret_cast<HMIXEROBJ>(mixer);
    bool master = false;
    unsigned int waveLines = 0, adjustedWaveLines = 0;
    if (mixerGetLineInfoW(object, &output, MIXER_GETLINEINFOF_COMPONENTTYPE | MIXER_OBJECTF_HMIXER)
            == MMSYSERR_NOERROR) {
        master = maximizePlaybackLine(mixer, output);
        // Only playback sources routed to this output; never recording gain.
        for (DWORD i = 0; i < output.cConnections && i < 64; ++i) {
            MIXERLINEW source = {};
            source.cbStruct = sizeof(source);
            source.dwDestination = output.dwDestination;
            source.dwSource = i;
            if (mixerGetLineInfoW(object, &source, MIXER_GETLINEINFOF_SOURCE | MIXER_OBJECTF_HMIXER)
                    == MMSYSERR_NOERROR && source.dwComponentType == MIXERLINE_COMPONENTTYPE_SRC_WAVEOUT) {
                ++waveLines;
                if (maximizePlaybackLine(mixer, source)) ++adjustedWaveLines;
            }
        }
    }
    mixerClose(mixer);
    bool allAdjusted = master && waveLines && adjustedWaveLines == waveLines && output.cConnections <= 64;
    return allAdjusted ? "OK" : (master || adjustedWaveLines ? "PARTIAL" : "UNSUPPORTED");
}

bool loadVoices() {
    ISpObjectTokenCategory* category = NULL;
    IEnumSpObjectTokens* items = NULL;
    HRESULT result = CoCreateInstance(CLSID_SpObjectTokenCategory, NULL, CLSCTX_INPROC_SERVER,
                                     IID_ISpObjectTokenCategory, reinterpret_cast<void**>(&category));
    if (FAILED(result)) return false;
    result = category->SetId(SPCAT_VOICES, FALSE);
    if (SUCCEEDED(result)) result = category->EnumTokens(NULL, NULL, &items);
    category->Release();
    if (FAILED(result)) return false;
    // Build a complete temporary snapshot. An installer can leave tokens half
    // written; keep the last good catalog rather than withdrawing working voices.
    ULONG count = 0;
    ISpObjectToken* newTokens[MAX_VOICES] = {};
    WCHAR* newIds[MAX_VOICES] = {};
    WCHAR* newNames[MAX_VOICES] = {};
    bool complete = SUCCEEDED(items->GetCount(&count)) && count <= MAX_VOICES;
    for (ULONG i = 0; complete && i < count; ++i) {
        complete = items->Next(1, &newTokens[i], NULL) == S_OK;
        if (complete) complete = SUCCEEDED(newTokens[i]->GetId(&newIds[i])) &&
                                 SUCCEEDED(newTokens[i]->GetStringValue(NULL, &newNames[i]));
        if (complete) complete = newIds[i] && newNames[i] && lstrlenW(newIds[i]) <= 1400;
    }
    items->Release();
    if (!complete) {
        for (unsigned int i = 0; i < MAX_VOICES; ++i) {
            if (newTokens[i]) newTokens[i]->Release();
            if (newIds[i]) CoTaskMemFree(newIds[i]);
            if (newNames[i]) CoTaskMemFree(newNames[i]);
        }
        return false;
    }
    catalogChanged = false;
    bool seen[MAX_VOICES] = {};
    for (ULONG i = 0; i < count; ++i) {
        WCHAR* id = newIds[i];
        unsigned int slot = 0;
        while (slot < voiceCount && lstrcmpW(voiceIds[slot], id)) ++slot;
        if (slot == MAX_VOICES) {
            CoTaskMemFree(id); CoTaskMemFree(newNames[i]); newTokens[i]->Release(); continue;
        }
        if (slot == voiceCount) { voiceIds[slot] = id; ++voiceCount; }
        else CoTaskMemFree(id);
        if (!voices[slot] || !voiceNames[slot] || lstrcmpW(voiceNames[slot], newNames[i])) {
            catalogChanged = true;
            if (selectedVoice == static_cast<int>(slot)) selectedVoice = -1;
            // A reinstalled or renamed voice may output at a different rate.
            nativeRate[slot] = 0;
            nativeChannels[slot] = 0;
        }
        if (voices[slot]) voices[slot]->Release();
        if (voiceNames[slot]) CoTaskMemFree(voiceNames[slot]);
        voices[slot] = newTokens[i];
        voiceNames[slot] = newNames[i];
        seen[slot] = true;
    }
    for (unsigned int i = 0; i < voiceCount; ++i) {
        if (!seen[i] && voices[i]) {
            catalogChanged = true;
            voices[i]->Release();
            voices[i] = NULL;
            nativeRate[i] = 0;
            nativeChannels[i] = 0;
            if (selectedVoice == static_cast<int>(i)) selectedVoice = -1;
        }
    }
    return true;
}

void announceVoices() {
    sendLine(""); // Terminate a partial previous reply before a fresh handshake.
    wsprintfA(outgoing, "READY\t%u\t%s", protocolVersion, session);
    sendLine(outgoing);
    for (unsigned int i = 0; i < voiceCount; ++i) {
        if (!voices[i]) continue;
        wsprintfA(outgoing, "VOICE\t%u\t", i);
        unsigned int prefixLength = lstrlenA(outgoing);
        encodeName(voiceNames[i], outgoing + prefixLength, 2048);
        lstrcatA(outgoing, "\t");
        prefixLength = lstrlenA(outgoing);
        encodeName(voiceIds[i], outgoing + prefixLength, MAX_LINE - prefixLength);
        sendLine(outgoing);
    }
    sendLine("ENDVOICES");
    if (protocolVersion == 2) {
        wsprintfA(outgoing, "CAPS\t%s\tvoice-refresh", session);
        sendLine(outgoing);
        wsprintfA(outgoing, "CAPS\t%s\txp-volume", session);
        sendLine(outgoing);
        wsprintfA(outgoing, "CAPS\t%s\taudio-pcm", session);
        sendLine(outgoing);
        // Advertised separately so a host that only knows audio-pcm keeps
        // offering the two routes it understands.
        wsprintfA(outgoing, "CAPS\t%s\taudio-both", session);
        sendLine(outgoing);
        wsprintfA(outgoing, "CAPS\t%s\tsilent-probe", session);
        sendLine(outgoing);
    }
}

// Only these generated tags are allowed. User text is always XML-escaped.
void makeSpeechXml(unsigned int pitch, unsigned int volume, bool spell) {
    // Keep the SAPI master volume open. A cold engine can accept Speak at
    // master volume zero and then report E_ABORT asynchronously. The batch
    // protocol already applies per-request volume in XML and does not hit
    // that failure; use the same path for legacy SPEAK.
    wsprintfW(speechXml, L"<volume level=\"%u\"><pitch absmiddle=\"%d\">",
              volume, static_cast<int>(pitch) - 10);
    if (spell) lstrcatW(speechXml, L"<spell>");
    for (const WCHAR* next = speechText; *next; ++next) {
        // Pipe Organ's XP SAPI engine accepts a raw '!' and then fails the
        // stream asynchronously. An isolated CDATA text node preserves the
        // mark and survived 100 direct SAPI requests without slowing speech.
        if (*next == L'!') lstrcatW(speechXml, L"<![CDATA[!]]>");
        else if (*next == L'&') lstrcatW(speechXml, L"&amp;");
        else if (*next == L'<') lstrcatW(speechXml, L"&lt;");
        else if (*next == L'>') lstrcatW(speechXml, L"&gt;");
        else {
            unsigned int end = lstrlenW(speechXml);
            speechXml[end] = *next;
            speechXml[end + 1] = 0;
        }
    }
    if (spell) lstrcatW(speechXml, L"</spell>");
    lstrcatW(speechXml, L"</pitch></volume>");
}

HRESULT selectVoice(unsigned int slot) {
    if (selectedVoice == static_cast<int>(slot)) return S_OK;
    // Catalog objects may still hold a deleted registry key after reinstall.
    // Resolve the stable ID afresh; catalog slots remain unchanged for NVDA.
    ISpObjectToken* current = NULL;
    HRESULT result = CoCreateInstance(CLSID_SpObjectToken, NULL, CLSCTX_INPROC_SERVER,
                                      IID_ISpObjectToken, reinterpret_cast<void**>(&current));
    if (SUCCEEDED(result)) result = current->SetId(NULL, voiceIds[slot], FALSE);
    if (SUCCEEDED(result)) result = voice->SetVoice(current);
    if (current) current->Release();
    if (SUCCEEDED(result)) selectedVoice = slot;
    return result;
}

HRESULT setOutputQuality(unsigned int sampleRate);
HRESULT applyOutput(unsigned int slot, unsigned int sampleRate);

HRESULT speakXml(unsigned int slot, const WCHAR* xml, ULONG* stream) {
    HRESULT result = voice->Speak(xml, SPF_ASYNC | SPF_IS_XML, stream);
    if (result != HRESULT_FROM_WIN32(ERROR_KEY_DELETED)) return result;
    // Reinstalling the currently selected voice can invalidate its token too.
    // Retry only this synchronous rejection, once. Never replay accepted speech
    // or suppress other engine failures that must trigger local-speech fallback.
    reportSapiFailure(5, result, slot, selectedQuality < 0 ? 0 : selectedQuality);
    // SpVoice caches engines by token ID. A fresh token alone is insufficient
    // when the selected engine already owns the deleted registration handle.
    long rate = 0;
    USHORT volume = 100;
    result = voice->GetRate(&rate);
    if (SUCCEEDED(result)) result = voice->GetVolume(&volume);
    if (FAILED(result)) return result;
    ISpVoice* replacement = NULL;
    result = CoCreateInstance(CLSID_SpVoice, NULL, CLSCTX_INPROC_SERVER,
                              IID_ISpVoice, reinterpret_cast<void**>(&replacement));
    if (FAILED(result)) return result;
    ULONGLONG interest = SPFEI(SPEI_END_INPUT_STREAM) | SPFEI(SPEI_TTS_BOOKMARK);
    result = replacement->SetInterest(interest, interest);
    if (SUCCEEDED(result) && paused) result = replacement->Pause();
    if (FAILED(result)) { replacement->Release(); return result; }
    voice->Speak(NULL, SPF_PURGEBEFORESPEAK, NULL);
    voice->Release();
    voice = replacement;
    unsigned int quality = requestedQuality;
    selectedVoice = -1;
    selectedQuality = -1;
    appliedRoute = -1;
    result = selectVoice(slot);
    if (SUCCEEDED(result)) result = applyOutput(slot, quality);
    if (SUCCEEDED(result)) result = voice->SetRate(rate);
    if (SUCCEEDED(result)) result = voice->SetVolume(volume);
    if (SUCCEEDED(result)) result = voice->Speak(xml, SPF_ASYNC | SPF_IS_XML, stream);
    if (SUCCEEDED(result)) {
        wsprintfA(outgoing, "NOTICE\t%s\t%u\t%u\tvoice-token-refreshed", session, generation, requestId);
        sendLine(outgoing);
    }
    return result;
}

void speakCommand(char** fields, unsigned int count) {
    unsigned int newGeneration, newRequest, voiceIndex, rate, volume, pitch, spell;
    if (count != 11 ||
        !parseNumber(fields[2], 2147483647, newGeneration) ||
        !parseNumber(fields[3], 2147483647, newRequest) ||
        !parseNumber(fields[4], MAX_VOICES - 1, voiceIndex) || voiceIndex >= voiceCount || !voices[voiceIndex] ||
        !parseNumber(fields[5], 20, rate) || !parseNumber(fields[6], 100, volume) ||
        !parseNumber(fields[7], 20, pitch) || !parseNumber(fields[8], 1, spell) ||
        lstrcmpA(fields[9], "TEXT") || !decodeText(fields[10])) {
        sendError("invalid-speech-command");
        return;
    }
    if (newGeneration != generation) return;
    if (speaking) { sendError("speech-already-active"); return; }
    requestId = newRequest;
    // Version 1 has no audio route; make sure a stale capture binding from a
    // previous version 2 session cannot swallow this utterance.
    if (appliedRoute != static_cast<int>(ROUTE_XP) && appliedRoute >= 0) {
        closePlayback();
        audioRoute = ROUTE_XP;
        appliedRoute = -1;
        selectedQuality = -1;
        requestedQuality = 0;
        setOutputQuality(0);
    }
    HRESULT result = selectVoice(voiceIndex);
    if (SUCCEEDED(result)) result = voice->SetRate(static_cast<int>(rate) - 10);
    if (SUCCEEDED(result)) result = voice->SetVolume(100);
    makeSpeechXml(pitch, volume, spell != 0);
    endInputSeen = false;
    if (SUCCEEDED(result)) result = speakXml(voiceIndex, speechXml, NULL);
    if (FAILED(result)) { sendError("sapi-speak-failed"); return; }
    speaking = true;
    wsprintfA(outgoing, "ACCEPTED\t%s\t%u\t%u", session, generation, requestId);
    sendLine(outgoing);
}

bool appendXml(const WCHAR* text) {
    unsigned int length = lstrlenW(text);
    if (length >= MAX_XML - xmlUsed) return false;
    lstrcpyW(utteranceXml + xmlUsed, text);
    xmlUsed += length;
    return true;
}

bool closeStyle() {
    if (!styleOpen) return true;
    styleOpen = false;
    if (styleSpell && !appendXml(L"</spell>")) return false;
    return appendXml(L"</pitch></volume></rate>");
}

bool appendSpeechPart(unsigned int rate, unsigned int volume, unsigned int pitch, unsigned int spell) {
    // Transport boundaries must not become prosody boundaries in SAPI XML.
    if (!styleOpen || rate != styleRate || volume != styleVolume || pitch != stylePitch || spell != styleSpell) {
        if (!closeStyle()) return false;
        WCHAR opening[160];
        wsprintfW(opening, L"<rate absspeed=\"%d\"><volume level=\"%u\"><pitch absmiddle=\"%d\">",
                  static_cast<int>(rate) - 10, volume, static_cast<int>(pitch) - 10);
        if (!appendXml(opening) || (spell && !appendXml(L"<spell>"))) return false;
        styleRate = rate; styleVolume = volume; stylePitch = pitch; styleSpell = spell;
        styleOpen = true;
    }
    for (const WCHAR* next = speechText; *next; ++next) {
        if (*next == L'!') { if (!appendXml(L"<![CDATA[!]]>")) return false; }
        else if (*next == L'&') { if (!appendXml(L"&amp;")) return false; }
        else if (*next == L'<') { if (!appendXml(L"&lt;")) return false; }
        else if (*next == L'>') { if (!appendXml(L"&gt;")) return false; }
        else {
            if (xmlUsed + 1 >= MAX_XML) return false;
            utteranceXml[xmlUsed++] = *next;
            utteranceXml[xmlUsed] = 0;
        }
    }
    return true;
}

HRESULT setOutputQuality(unsigned int sampleRate) {
    if (selectedQuality == static_cast<int>(sampleRate)) return S_OK;
    HRESULT result;
    if (!sampleRate) result = voice->SetOutput(NULL, TRUE);
    else {
        ISpAudio* output = NULL;
        result = CoCreateInstance(CLSID_SpMMAudioOut, NULL, CLSCTX_INPROC_SERVER,
                                  IID_ISpAudio, reinterpret_cast<void**>(&output));
        if (FAILED(result)) return result;
        WAVEFORMATEX format = {};
        format.wFormatTag = WAVE_FORMAT_PCM;
        format.nChannels = 1;
        format.nSamplesPerSec = sampleRate;
        format.wBitsPerSample = 16;
        format.nBlockAlign = 2;
        format.nAvgBytesPerSec = sampleRate * 2;
        result = output->SetFormat(SPDFID_WaveFormatEx, &format);
        if (SUCCEEDED(result)) result = voice->SetOutput(output, FALSE);
        output->Release();
    }
    if (SUCCEEDED(result)) selectedQuality = sampleRate;
    return result;
}

// Learn the format SAPI negotiates for the selected voice on the real output,
// so 'voice default' can be captured without resampling. Measured on XP: this
// reports 16 kHz for the AT&T voices and 22.05 kHz for the others, so it does
// follow the engine. It speaks nothing and produces no sound.
void discoverNativeFormat(unsigned int slot) {
    if (slot >= MAX_VOICES || nativeRate[slot]) return;
    if (FAILED(voice->SetOutput(NULL, TRUE))) return;
    // The real output object was just replaced; no cached binding survives it.
    selectedQuality = -1;
    appliedRoute = -1;
    ISpStreamFormat* stream = NULL;
    if (FAILED(voice->GetOutputStream(&stream)) || !stream) return;
    GUID formatId;
    WAVEFORMATEX* format = NULL;
    if (SUCCEEDED(stream->GetFormat(&formatId, &format)) && format) {
        if (format->nSamplesPerSec >= 8000 && format->nSamplesPerSec <= 48000 &&
            format->wBitsPerSample == 16 && (format->nChannels == 1 || format->nChannels == 2)) {
            nativeRate[slot] = format->nSamplesPerSec;
            nativeChannels[slot] = format->nChannels;
        }
        CoTaskMemFree(format);
    }
    stream->Release();
}

// Bind SAPI's output to the capture sink. SAPI will not fill in the engine's
// format for a caller-supplied base stream, so the format has to be named:
// either the rate the user chose, or the one discovered above.
// A SAPI stream keeps its base stream until it is closed: binding a second
// utterance onto the same object returns SPERR_ALREADY_INITIALIZED. Close it
// first, and if that is not enough, start with a fresh one.
HRESULT rebindCaptureStream(const WAVEFORMATEX* format) {
    if (captureStream) {
        captureStream->Close();
        HRESULT result = captureStream->SetBaseStream(sinkStream(), SPDFID_WaveFormatEx, format);
        if (SUCCEEDED(result)) return result;
        captureStream->Release();
        captureStream = NULL;
    }
    HRESULT created = CoCreateInstance(CLSID_SpStream, NULL, CLSCTX_INPROC_SERVER,
                                       IID_ISpStream, reinterpret_cast<void**>(&captureStream));
    if (FAILED(created)) return created;
    return captureStream->SetBaseStream(sinkStream(), SPDFID_WaveFormatEx, format);
}

HRESULT bindCaptureOutput(unsigned int slot, unsigned int sampleRate) {
    unsigned int rate = sampleRate;
    unsigned int channels = 1;
    if (!rate) {
        discoverNativeFormat(slot);
        if (slot < MAX_VOICES && nativeRate[slot]) {
            rate = nativeRate[slot];
            channels = nativeChannels[slot];
        }
    }
    if (!rate) rate = AUDIO_FALLBACK_RATE;
    WAVEFORMATEX format = {};
    format.wFormatTag = WAVE_FORMAT_PCM;
    format.nChannels = static_cast<WORD>(channels);
    format.nSamplesPerSec = rate;
    format.wBitsPerSample = 16;
    format.nBlockAlign = static_cast<WORD>(channels * 2);
    format.nAvgBytesPerSec = rate * channels * 2;
    captureRate = rate;
    captureBits = 16;
    captureChannels = channels;
    captureRewind();
    HRESULT result = rebindCaptureStream(&format);
    if (FAILED(result)) return result;
    return voice->SetOutput(captureStream, FALSE);
}

HRESULT applyOutput(unsigned int slot, unsigned int sampleRate) {
    // The capture route deliberately clears selectedQuality, so remember the
    // requested rate here; the one-time Speak retry must not silently lose it.
    requestedQuality = sampleRate;
    // A probe is always rendered into memory and never played anywhere, no
    // matter which route the user chose.
    unsigned int target = batchProbe ? ROUTE_NVDA : audioRoute;
    if (target == ROUTE_XP) {
        closePlayback();
        if (appliedRoute != static_cast<int>(ROUTE_XP)) selectedQuality = -1;
        HRESULT result = setOutputQuality(sampleRate);
        if (SUCCEEDED(result)) appliedRoute = ROUTE_XP;
        return result;
    }
    HRESULT result = bindCaptureOutput(slot, sampleRate);
    if (FAILED(result)) return result;
    if (target == ROUTE_BOTH && !openPlayback(captureRate, captureChannels)) {
        // Better to say the local device is unavailable than to quietly send
        // the speech to NVDA only while the user asked to hear it here too.
        closePlayback();
        return E_FAIL;
    }
    if (target != ROUTE_BOTH) closePlayback();
    appliedRoute = target;
    // Returning to the speakers must always reconfigure the real device.
    selectedQuality = -1;
    return result;
}

// Announce the format that was named when the stream was bound.
//
// This must NOT ask the capture stream, and neither must anything else on this
// thread while speech is in flight. SAPI's stream object serialises its own
// methods, and the rendering thread sits inside its Write for as long as the
// link needs to catch up. Measured on XP: a GetFormat call from this thread
// blocked for 4,984 ms of a 5,000 ms wait. That froze the very loop that
// drains the buffer, so the wait could never end, and the host gave up first.
// SAPI is bound with format changes disallowed, so the named format is the
// truth and no call is needed.
void emitAudioFormat() {
    if (audioFormatSent) return;
    audioFormatSent = true;
    // Unreachable while capture is only enabled after a successful bind, but
    // announcing a zero format would be worse than refusing to speak.
    if (captureRate < 8000 || captureRate > 48000 || captureBits != 16 ||
        (captureChannels != 1 && captureChannels != 2)) {
        stopSpeech();
        sendError("audio-format-unsupported");
        return;
    }
    wsprintfA(outgoing, "AUDIOFORMAT\t%s\t%u\t%u\t%u\t%u\t%u",
              session, generation, requestId, captureRate, captureBits, captureChannels);
    sendLine(outgoing);
}

// Room in the transmit queue, so audio never blocks the loop that also reads
// cancellation and answers the heartbeat.
bool audioLinkHasRoom() {
    COMSTAT status = {};
    DWORD errors = 0;
    if (!ClearCommError(serialPort, &errors, &status)) return true;
    return status.cbOutQue <= AUDIO_TX_QUEUE_LIMIT;
}

void pumpCapturedAudio() {
    if (!routedCapture) return;
    bool alsoPlayHere = appliedRoute == static_cast<int>(ROUTE_BOTH);
    if (alsoPlayHere && !playbackDevice) {
        // Binding opens the device before speaking, so this cannot normally
        // happen. Say so and stop rather than waiting for room that no device
        // will ever free, which would hang the utterance.
        stopSpeech();
        sendError("local-playback-unavailable");
        return;
    }
    for (unsigned int frames = 0; frames < AUDIO_FRAMES_PER_TURN; ++frames) {
        if (!audioLinkHasRoom()) break;
        // On the Both route the local device sets the pace. Taking audio we
        // cannot also play would either drop it or run the two outputs apart.
        if (alsoPlayHere && !playbackHasRoom()) break;
        char raw[AUDIO_FRAME_BYTES];
        unsigned int taken = captureTake(raw, AUDIO_FRAME_BYTES, pendingDone);
        if (!taken) break;
        if (alsoPlayHere && !playCapturedAudio(raw, taken)) {
            ++playbackUnderruns;
            logMessage("Local playback refused a buffer; that audio was not heard on this machine.");
        }
        if (probeUtterance) {
            probeBytes += taken;
            // Real speech, not a run of digital silence. The threshold ignores
            // the tiny dither some engines emit while producing nothing.
            for (unsigned int i = 0; i + 1 < taken; i += 2) {
                short sample = static_cast<short>(
                    static_cast<unsigned char>(raw[i]) | (static_cast<unsigned char>(raw[i + 1]) << 8));
                if (sample > 64 || sample < -64) { probeNonSilent = true; break; }
            }
        }
        if (suppressFrames) continue;
        emitAudioFormat();
        if (!routedCapture) return;
        int prefix = wsprintfA(audioLine, "AUDIO\t%s\t%u\t%u\t%u\t",
                               session, generation, requestId, audioSequence);
        encodeBase64(raw, taken, audioLine + prefix);
        ++audioSequence;
        if (!sendLine(audioLine)) return;
    }
    if (!pendingDone || !captureEmpty()) return;
    pendingDone = false;
    routedCapture = false;
    if (seekAnomalies || writeTimeouts)
        logMessage("Captured audio needed stream repositioning or timed out waiting for the host.");
    // Measured proof that the engine really rendered, for a check that was
    // deliberately never played. Old hosts ignore an unknown line.
    if (probeUtterance) {
        wsprintfA(outgoing, "PROBEAUDIO\t%s\t%u\t%u\t%u\t%u",
                  session, generation, requestId, probeBytes, probeNonSilent ? 1u : 0u);
        sendLine(outgoing);
        probeUtterance = false;
        suppressFrames = false;
    }
    wsprintfA(outgoing, "DONE\t%s\t%u\t%u", session, generation, requestId);
    sendLine(outgoing);
}

void reportFormat() {
    // Same hazard as emitAudioFormat: GetOutputStream returns the capture
    // stream on the routed path, and touching it here would stall the loop.
    if (routedCapture) {
        wsprintfA(outgoing, "FORMAT\t%s\t%u\t%u\t%u", session, captureRate, captureBits, captureChannels);
        sendLine(outgoing);
        return;
    }
    ISpStreamFormat* stream = NULL;
    if (FAILED(voice->GetOutputStream(&stream))) return;
    GUID formatId;
    WAVEFORMATEX* format = NULL;
    if (SUCCEEDED(stream->GetFormat(&formatId, &format)) && format) {
        wsprintfA(outgoing, "FORMAT\t%s\t%u\t%u\t%u", session,
                  format->nSamplesPerSec, format->wBitsPerSample, format->nChannels);
        sendLine(outgoing);
        CoTaskMemFree(format);
    }
    stream->Release();
}

void batchCommand(char** fields, unsigned int count) {
    unsigned int newGeneration, newRequest;
    if (count < 4 || !parseNumber(fields[2], 2147483647, newGeneration) ||
        !parseNumber(fields[3], 2147483647, newRequest)) { sendError("invalid-batch"); return; }
    if (newGeneration != generation) return;
    if (!lstrcmpA(fields[0], "BEGIN")) {
        // An optional seventh field marks a recovery check. Older hosts send
        // six fields and are simply never treated as probing.
        unsigned int probeFlag = 0;
        if (count == 7 && !parseNumber(fields[6], 1, probeFlag)) { sendError("invalid-begin"); return; }
        if ((count != 6 && count != 7) || speaking || assembling ||
            !parseNumber(fields[4], MAX_VOICES - 1, batchVoice) || batchVoice >= voiceCount || !voices[batchVoice] ||
            !parseNumber(fields[5], 48000, batchQuality) ||
            (batchQuality && batchQuality != 16000 && batchQuality != 22050 && batchQuality != 44100 && batchQuality != 48000)) {
            sendError("invalid-begin"); return;
        }
        // The host only sends BEGIN after DONE, so audio from the previous
        // utterance cannot still be draining here. If it ever were, abandon it
        // rather than let its tail and sequence numbers run into this one.
        if (pendingDone) {
            captureAbortNow(2); // previous routed audio was still pending
            logMessage("A new utterance arrived before the previous audio finished; the remainder was dropped.");
        }
        batchProbe = probeFlag != 0;
        requestId = newRequest;
        xmlUsed = 0;
        styleOpen = false;
        utteranceXml[0] = 0;
        assembling = true;
    } else {
        if (!assembling || newRequest != requestId) { sendError("no-active-batch"); return; }
        if (!lstrcmpA(fields[0], "PART")) {
            unsigned int rate, volume, pitch, spell;
            if (count != 9 || !parseNumber(fields[4], 20, rate) || !parseNumber(fields[5], 100, volume) ||
                !parseNumber(fields[6], 20, pitch) || !parseNumber(fields[7], 1, spell) || !decodeText(fields[8])) {
                sendError("invalid-part"); return;
            }
            if (!appendSpeechPart(rate, volume, pitch, spell)) {
                stopSpeech(); sendError("utterance-too-long"); return;
            }
        } else if (!lstrcmpA(fields[0], "MARK") || !lstrcmpA(fields[0], "BREAK")) {
            unsigned int value;
            bool isMark = !lstrcmpA(fields[0], "MARK");
            if (count != 5 || !parseNumber(fields[4], isMark ? 2147483647 : 10000, value)) {
                sendError("invalid-marker"); return;
            }
            WCHAR tag[80];
            if (isMark) wsprintfW(tag, L"<bookmark mark=\"%u\"/>", value);
            else wsprintfW(tag, L"<silence msec=\"%u\"/>", value);
            if (!appendXml(tag)) { stopSpeech(); sendError("utterance-too-long"); return; }
        } else if (!lstrcmpA(fields[0], "COMMIT") && count == 4) {
            if (!closeStyle()) { stopSpeech(); sendError("utterance-too-long"); return; }
            assembling = false;
            probeUtterance = batchProbe;
            // On the XP route a probe has nowhere to go: the host is not
            // expecting audio frames there, so count the PCM instead of
            // sending it. On the other routes the host already discards it.
            suppressFrames = batchProbe && audioRoute == ROUTE_XP;
            probeBytes = 0;
            probeNonSilent = false;
            HRESULT result = selectVoice(batchVoice);
            unsigned int stage = 1;
            if (SUCCEEDED(result)) { stage = 2; result = applyOutput(batchVoice, batchQuality); }
            if (SUCCEEDED(result)) { stage = 3; result = voice->SetRate(0); }
            if (SUCCEEDED(result)) { stage = 4; result = voice->SetVolume(100); }
            endInputSeen = false;
            if (SUCCEEDED(result) && xmlUsed) {
                stage = 5;
                result = speakXml(batchVoice, utteranceXml, &activeStream);
            }
            if (FAILED(result)) {
                captureAbortNow(3); // synchronous SAPI setup/speak failure
                reportSapiFailure(stage, result, batchVoice, batchQuality);
                sendError("batch-speak-failed"); return;
            }
            speaking = xmlUsed != 0;
            batchSpeech = speaking;
            // Captured audio is forwarded by the main loop; DONE waits for it.
            routedCapture = speaking && appliedRoute != static_cast<int>(ROUTE_XP) && appliedRoute >= 0;
            reportFormat();
            if (!speaking) {
                wsprintfA(outgoing, "DONE\t%s\t%u\t%u", session, generation, requestId);
                sendLine(outgoing);
            }
        } else { sendError("unknown-batch-command"); return; }
    }
    wsprintfA(outgoing, "ACK\t%s\t%u\t%u", session, generation, requestId);
    sendLine(outgoing);
}

void finishSpeech() {
    if (!speaking) return;
    // SAPI can accept Speak asynchronously and fail later in the engine. Do
    // not report that failure as successful (but silent) speech to NVDA.
    SPVOICESTATUS status = {};
    HRESULT result = voice->GetStatus(&status, NULL);
    speaking = false;
    batchSpeech = false;
    endInputSeen = false;
    if (FAILED(result) || FAILED(status.hrLastResult)) {
        LONG abortBefore = InterlockedCompareExchange(&captureAbort, 0, 0);
        LONG abortReasonBefore = InterlockedCompareExchange(&captureAbortReason, 0, 0);
        LONG sinkAbortsBefore = InterlockedCompareExchange(&sinkWriteAborts, 0, 0);
        captureAbortNow(4); // asynchronous SAPI failure
        reportSapiFailure(FAILED(result) ? 6 : 7, FAILED(result) ? result : status.hrLastResult,
                          selectedVoice < 0 ? MAX_VOICES : selectedVoice, batchQuality,
                          &status, abortBefore, sinkAbortsBefore, abortReasonBefore);
        sendError("sapi-engine-failed");
        return;
    }
    // On the NVDA route the engine is finished but the audio is not: DONE must
    // not claim completion before the last frame has left the helper.
    if (routedCapture) { pendingDone = true; return; }
    wsprintfA(outgoing, "DONE\t%s\t%u\t%u", session, generation, requestId);
    sendLine(outgoing);
}

void speechEvents() {
    SPEVENT event;
    ULONG fetched;
    while (voice->GetEvents(1, &event, &fetched) == S_OK && fetched) {
        if (batchSpeech && event.ulStreamNum == activeStream) {
            if (event.eEventId == SPEI_TTS_BOOKMARK) {
                // Rendering into a stream runs far ahead of real time, so a
                // routed bookmark carries the byte offset it belongs to and the
                // host fires it when playback reaches that point. Old add-ons
                // keep the five-field line they already understand.
                if (routedCapture)
                    wsprintfA(outgoing, "INDEX\t%s\t%u\t%u\t%u\t%lu", session, generation, requestId,
                              static_cast<unsigned int>(event.wParam),
                              static_cast<DWORD>(event.ullAudioStreamOffset));
                else
                    wsprintfA(outgoing, "INDEX\t%s\t%u\t%u\t%u", session, generation, requestId, static_cast<unsigned int>(event.wParam));
                sendLine(outgoing);
            } else if (event.eEventId == SPEI_END_INPUT_STREAM) {
#ifndef ALVB_TEST_DROP_END_EVENTS
                endInputSeen = true;
#endif
            }
        }
        if (event.elParamType == SPET_LPARAM_IS_STRING || event.elParamType == SPET_LPARAM_IS_POINTER)
            CoTaskMemFree(reinterpret_cast<void*>(event.lParam));
    }
}

void checkSpeechCompletion() {
    // Drain bookmarks first. END_INPUT_STREAM can arrive before SAPI's output
    // thread has fully released the voice. Telling the host DONE at that event
    // lets a new request enter the old engine's teardown and occasionally
    // returns E_FAIL on the following stream. WaitUntilDone(0) confirms actual
    // completion, even when the engine never emits an END event.
    speechEvents();
    if (!speaking || paused) return;
    HRESULT result = voice->WaitUntilDone(0);
    if (result == S_OK) {
        // Events can arrive between the first drain and the completion poll.
        speechEvents();
        if (!speaking) return;
        if (batchSpeech && !endInputSeen) {
            wsprintfA(outgoing, "NOTICE\t%s\t%u\t%u\tcompletion-polled", session, generation, requestId);
            sendLine(outgoing);
        }
        finishSpeech();
    } else if (FAILED(result)) {
        stopSpeech(11); // completion poll itself failed
        sendError("sapi-completion-failed");
    }
}

void handleLine(char* line) {
    char* fields[12];
    unsigned int count = 1;
    fields[0] = line;
    for (char* position = line; *position; ++position) {
        if (*position != '\t') continue;
        if (count == 12) { sendError("too-many-fields"); return; }
        *position = 0;
        fields[count++] = position + 1;
    }
    if (count == 3 && !lstrcmpA(fields[0], "HELLO") &&
        (!lstrcmpA(fields[1], "1") || !lstrcmpA(fields[1], "2")) && validSession(fields[2])) {
        stopSpeech(12); // new session
        // Every connection starts on the XP sound card, so an add-on that does
        // not know about routing inherits exactly the old behaviour.
        closePlayback();
        audioRoute = ROUTE_XP;
        appliedRoute = -1;
        selectedQuality = -1;
        lstrcpynA(session, fields[2], sizeof(session));
        generation = 0;
        protocolVersion = fields[1][0] - '0';
        lastContact = GetTickCount();
        announceVoices();
        logMessage("Bridge connected. Audio plays through the XP default output.");
        return;
    }
    if (count < 2 || !session[0] || lstrcmpA(fields[1], session)) return;
    lastContact = GetTickCount();
    if (!lstrcmpA(fields[0], "PING") && count == 2) {
        wsprintfA(outgoing, "PONG\t%s", session);
        sendLine(outgoing);
    } else if (!lstrcmpA(fields[0], "MIXER") && count == 2 && protocolVersion == 2) {
        const char* result = maximizePlaybackVolume();
        wsprintfA(outgoing, "MIXER\t%s\t%s", session, result);
        sendLine(outgoing);
        logMessage("XP playback volume adjustment requested (mute state unchanged).");
    } else if (!lstrcmpA(fields[0], "REFRESH") && count == 2 && protocolVersion == 2) {
        if (speaking || assembling) { sendError("refresh-while-busy"); return; }
        if (!loadVoices()) {
            wsprintfA(outgoing, "VOICESRETRY\t%s", session);
            sendLine(outgoing);
            logMessage("Voice scan incomplete; keeping last good catalog.");
            return;
        }
        if (!catalogChanged) {
            wsprintfA(outgoing, "VOICESUNCHANGED\t%s", session);
            sendLine(outgoing);
            return;
        }
        // Same session and generation, no audio purge, and stable voice slots.
        announceVoices();
    } else if (!lstrcmpA(fields[0], "ROUTE") && count == 3 && protocolVersion == 2) {
        // Only between utterances: changing SAPI's output object mid-speech
        // would strand audio the host has already been promised.
        if (speaking || assembling || routedCapture) { sendError("route-while-busy"); return; }
        unsigned int wanted;
        if (!lstrcmpA(fields[2], "xp")) wanted = ROUTE_XP;
        else if (!lstrcmpA(fields[2], "nvda")) wanted = ROUTE_NVDA;
        else if (!lstrcmpA(fields[2], "both")) wanted = ROUTE_BOTH;
        else { sendError("invalid-route"); return; }
        if (wanted != audioRoute) {
            audioRoute = wanted;
            appliedRoute = -1;
            selectedQuality = -1;
            if (wanted != ROUTE_BOTH) closePlayback();
        }
        wsprintfA(outgoing, "ROUTE\t%s\t%s", session, fields[2]);
        sendLine(outgoing);
    } else if (!lstrcmpA(fields[0], "CANCEL") && count == 3) {
        unsigned int value;
        if (!parseNumber(fields[2], 2147483647, value)) { sendError("invalid-generation"); return; }
        stopSpeech(13); // explicit host cancellation
        generation = value;
        wsprintfA(outgoing, "CANCELLED\t%s\t%u", session, generation);
        sendLine(outgoing);
    } else if (!lstrcmpA(fields[0], "PAUSE") && count == 3) {
        // SAPI's pause acts on its audio output. On the NVDA route that output
        // is a memory stream, so pausing here is not known to hold the audio
        // back; the host has to pause its own player as well. Untested.
        if (lstrcmpA(fields[2], "0") && lstrcmpA(fields[2], "1")) {
            sendError("invalid-pause");
            return;
        }
        bool wanted = !lstrcmpA(fields[2], "1");
        if (wanted != paused) {
            HRESULT result = wanted ? voice->Pause() : voice->Resume();
            if (SUCCEEDED(result)) paused = wanted;
            else sendError("sapi-pause-failed");
        }
    } else if (!lstrcmpA(fields[0], "SPEAK")) speakCommand(fields, count);
    else if (protocolVersion == 2 && (!lstrcmpA(fields[0], "BEGIN") || !lstrcmpA(fields[0], "PART") ||
             !lstrcmpA(fields[0], "MARK") || !lstrcmpA(fields[0], "BREAK") || !lstrcmpA(fields[0], "COMMIT"))) batchCommand(fields, count);
    else sendError("unknown-command");
}

BOOL WINAPI onConsoleEvent(DWORD) {
    InterlockedExchange(&stopping, 1);
    return TRUE;
}

bool openSerial(const WCHAR* name) {
    serialPort = CreateFileW(name, GENERIC_READ | GENERIC_WRITE, 0, NULL, OPEN_EXISTING, 0, NULL);
    if (serialPort == INVALID_HANDLE_VALUE) return false;
    if (!SetupComm(serialPort, 16384, 16384)) return false;
    DCB settings = {};
    settings.DCBlength = sizeof(settings);
    if (!GetCommState(serialPort, &settings)) return false;
    settings.BaudRate = CBR_115200;
    settings.ByteSize = 8;
    settings.Parity = NOPARITY;
    settings.StopBits = ONESTOPBIT;
    settings.fBinary = TRUE;
    settings.fOutxCtsFlow = FALSE;
    settings.fOutxDsrFlow = FALSE;
    settings.fOutX = FALSE;
    settings.fInX = FALSE;
    settings.fAbortOnError = FALSE;
    settings.fDtrControl = DTR_CONTROL_DISABLE;
    settings.fRtsControl = RTS_CONTROL_DISABLE;
    if (!SetCommState(serialPort, &settings)) return false;
    COMMTIMEOUTS timeouts = {MAXDWORD, 0, 20, 0, 1000};
    if (!SetCommTimeouts(serialPort, &timeouts)) return false;
    PurgeComm(serialPort, PURGE_RXCLEAR | PURGE_TXCLEAR);
    return true;
}

int runBridge() {
    int argumentCount = 0;
    // COM1 is deliberately the sole default; no probing other devices.
    const WCHAR* port = L"\\\\.\\COM1";
    WCHAR** arguments = CommandLineToArgvW(GetCommandLineW(), &argumentCount);
    if (!arguments) return 1;
    if (argumentCount == 2 && !lstrcmpW(arguments[1], L"--com2")) port = L"\\\\.\\COM2";
    else if (argumentCount == 2 && !lstrcmpW(arguments[1], L"--com3")) port = L"\\\\.\\COM3";
    else if (argumentCount == 2 && !lstrcmpW(arguments[1], L"--com4")) port = L"\\\\.\\COM4";
    else if (argumentCount > 1 && (argumentCount != 2 || lstrcmpW(arguments[1], L"--com1"))) {
        logMessage("Usage: AngelLegacyVoiceBridge.exe [--com1 | --com2 | --com3 | --com4]");
        LocalFree(arguments);
        return 1;
    }
    LocalFree(arguments);
    // No C runtime startup runs, so anything with state is initialised here.
    InitializeCriticalSection(&audioLock);
    HRESULT result = CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);
    if (FAILED(result)) { logMessage("Unable to initialize COM."); return 1; }
    result = CoCreateInstance(CLSID_SpVoice, NULL, CLSCTX_INPROC_SERVER, IID_ISpVoice,
                              reinterpret_cast<void**>(&voice));
    if (FAILED(result) || !loadVoices()) { logMessage("No working SAPI 5 voice found."); return 2; }
    if (!voiceCount) logMessage("No SAPI 5 voices registered yet; waiting for voice installation and idle scan.");
    ULONGLONG interest = SPFEI(SPEI_END_INPUT_STREAM) | SPFEI(SPEI_TTS_BOOKMARK);
    if (FAILED(voice->SetInterest(interest, interest))) { logMessage("Cannot receive SAPI completion events."); return 2; }
    if (!openSerial(port)) { logMessage("Cannot open configured COM port. Check VM serial settings and other bridge instances."); return 3; }
    SetConsoleCtrlHandler(onConsoleEvent, TRUE);
    logMessage("Angel Legacy Voice Bridge 0.1.2-dev3. Waiting for the host. Ctrl+C exits.");
#ifdef ALVB_TEST_DROP_END_EVENTS
    logMessage("FAULT-INJECTION TEST ONLY: end events suppressed. Do not distribute this helper.");
#endif
    unsigned int used = 0;
    bool discardingLine = false;
    unsigned int serialErrors = 0;
    DWORD lastSerialError = 0;
    // Larger than the original 256 bytes so control messages are not read a
    // fragment at a time while captured audio is also crossing the link.
    char buffer[1024];
    while (!stopping) {
        DWORD received = 0;
        if (!ReadFile(serialPort, buffer, sizeof(buffer), &received, NULL)) serialFault = true;
        if (serialFault) {
            DWORD now = GetTickCount();
            if (static_cast<DWORD>(now - lastSerialError) > 10000) serialErrors = 0;
            lastSerialError = now;
            stopSpeech(14); // serial transport fault
            closePlayback();
            session[0] = 0;
            audioRoute = ROUTE_XP;
            appliedRoute = -1;
            selectedQuality = -1;
            used = 0;
            discardingLine = false;
            DWORD errors = 0;
            ClearCommError(serialPort, &errors, NULL);
            PurgeComm(serialPort, PURGE_RXCLEAR | PURGE_TXCLEAR);
            logMessage("Serial I/O failed; session cleared. Retrying.");
            if (++serialErrors >= 5) {
                logMessage("Serial port unavailable; backing off before retrying.");
                Sleep(5000);
                serialErrors = 0;
            }
            serialFault = false;
            Sleep(200);
            continue;
        }
        if (received) serialErrors = 0;
        for (DWORD i = 0; i < received; ++i) {
            char value = buffer[i];
            if (value == '\n') {
                if (!discardingLine) { incoming[used] = 0; handleLine(incoming); }
                else sendError("invalid-line");
                used = 0;
                discardingLine = false;
            } else if (value != '\r') {
                if (value && used + 1 < MAX_LINE && !discardingLine) incoming[used++] = value;
                else discardingLine = true;
            }
        }
        MSG message;
        while (PeekMessageW(&message, NULL, 0, 0, PM_REMOVE)) {
            TranslateMessage(&message);
            DispatchMessageW(&message);
        }
        checkSpeechCompletion();
        pumpCapturedAudio();
        if (session[0] && static_cast<DWORD>(GetTickCount() - lastContact) > HEARTBEAT_TIMEOUT) {
            stopSpeech(15); // heartbeat expiration
            closePlayback();
            session[0] = 0;
            audioRoute = ROUTE_XP;
            appliedRoute = -1;
            selectedQuality = -1;
            logMessage("Host disconnected; old speech discarded. Waiting for reconnection.");
        }
    }
    stopSpeech();
    closePlayback();
    CloseHandle(serialPort);
    if (captureStream) captureStream->Release();
    for (unsigned int i = 0; i < voiceCount; ++i) {
        if (voices[i]) voices[i]->Release();
        CoTaskMemFree(voiceIds[i]);
        CoTaskMemFree(voiceNames[i]);
    }
    voice->Release();
    CoUninitialize();
    return 0;
}
} // namespace

// No CRT startup: only APIs available in the original 32-bit Windows XP.
extern "C" void __cdecl bridgeEntry() { ExitProcess(runBridge()); }
