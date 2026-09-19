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
WCHAR speechXml[MAX_TEXT * 6 + 100];

void logMessage(const char* message) {
    DWORD written;
    WriteFile(GetStdHandle(STD_OUTPUT_HANDLE), message, lstrlenA(message), &written, NULL);
    WriteFile(GetStdHandle(STD_OUTPUT_HANDLE), "\r\n", 2, &written, NULL);
}

bool sendLine(const char* line) {
    if (serialFault) return false;
    DWORD length = lstrlenA(line), written = 0;
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

void stopSpeech() {
    if (voice) {
        voice->Speak(NULL, SPF_PURGEBEFORESPEAK, NULL);
        if (paused) voice->Resume();
    }
    paused = false;
    speaking = false;
    assembling = false;
    batchSpeech = false;
    xmlUsed = 0;
    styleOpen = false;
}

void sendError(const char* code) {
    wsprintfA(outgoing, "ERROR\t%s\t%u\t%u\t%s", session, generation, requestId, code);
    sendLine(outgoing);
    logMessage(code);
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
    }
}

// Only these generated tags are allowed. User text is always XML-escaped.
void makeSpeechXml(unsigned int pitch, bool spell) {
    wsprintfW(speechXml, L"<pitch absmiddle=\"%d\">", static_cast<int>(pitch) - 10);
    if (spell) lstrcatW(speechXml, L"<spell>");
    for (const WCHAR* next = speechText; *next; ++next) {
        if (*next == L'&') lstrcatW(speechXml, L"&amp;");
        else if (*next == L'<') lstrcatW(speechXml, L"&lt;");
        else if (*next == L'>') lstrcatW(speechXml, L"&gt;");
        else {
            unsigned int end = lstrlenW(speechXml);
            speechXml[end] = *next;
            speechXml[end + 1] = 0;
        }
    }
    if (spell) lstrcatW(speechXml, L"</spell>");
    lstrcatW(speechXml, L"</pitch>");
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
    HRESULT result = S_OK;
    if (selectedVoice != static_cast<int>(voiceIndex)) {
        result = voice->SetVoice(voices[voiceIndex]);
        if (SUCCEEDED(result)) selectedVoice = voiceIndex;
    }
    if (SUCCEEDED(result)) result = voice->SetRate(static_cast<int>(rate) - 10);
    if (SUCCEEDED(result)) result = voice->SetVolume(static_cast<USHORT>(volume));
    makeSpeechXml(pitch, spell != 0);
    if (SUCCEEDED(result)) result = voice->Speak(speechXml, SPF_ASYNC | SPF_IS_XML, NULL);
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
        if (*next == L'&') { if (!appendXml(L"&amp;")) return false; }
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

bool setOutputQuality(unsigned int sampleRate) {
    if (selectedQuality == static_cast<int>(sampleRate)) return true;
    HRESULT result;
    if (!sampleRate) result = voice->SetOutput(NULL, TRUE);
    else {
        ISpAudio* output = NULL;
        result = CoCreateInstance(CLSID_SpMMAudioOut, NULL, CLSCTX_INPROC_SERVER,
                                  IID_ISpAudio, reinterpret_cast<void**>(&output));
        if (FAILED(result)) return false;
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
    return SUCCEEDED(result);
}

void reportFormat() {
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
        if (count != 6 || speaking || assembling ||
            !parseNumber(fields[4], MAX_VOICES - 1, batchVoice) || batchVoice >= voiceCount || !voices[batchVoice] ||
            !parseNumber(fields[5], 48000, batchQuality) ||
            (batchQuality && batchQuality != 16000 && batchQuality != 22050 && batchQuality != 44100 && batchQuality != 48000)) {
            sendError("invalid-begin"); return;
        }
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
            HRESULT result = S_OK;
            if (selectedVoice != static_cast<int>(batchVoice)) {
                result = voice->SetVoice(voices[batchVoice]);
                if (SUCCEEDED(result)) selectedVoice = batchVoice;
            }
            if (SUCCEEDED(result) && !setOutputQuality(batchQuality)) result = E_FAIL;
            if (SUCCEEDED(result)) result = voice->SetRate(0);
            if (SUCCEEDED(result)) result = voice->SetVolume(100);
            if (SUCCEEDED(result) && xmlUsed) result = voice->Speak(utteranceXml, SPF_ASYNC | SPF_IS_XML, &activeStream);
            if (FAILED(result)) { sendError("batch-speak-failed"); return; }
            speaking = xmlUsed != 0;
            batchSpeech = speaking;
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

void speechEvents() {
    SPEVENT event;
    ULONG fetched;
    while (voice->GetEvents(1, &event, &fetched) == S_OK && fetched) {
        if (batchSpeech && event.ulStreamNum == activeStream) {
            if (event.eEventId == SPEI_TTS_BOOKMARK) {
                wsprintfA(outgoing, "INDEX\t%s\t%u\t%u\t%u", session, generation, requestId, static_cast<unsigned int>(event.wParam));
                sendLine(outgoing);
            } else if (event.eEventId == SPEI_END_INPUT_STREAM) {
                speaking = false;
                batchSpeech = false;
                wsprintfA(outgoing, "DONE\t%s\t%u\t%u", session, generation, requestId);
                sendLine(outgoing);
            }
        }
        if (event.elParamType == SPET_LPARAM_IS_STRING || event.elParamType == SPET_LPARAM_IS_POINTER)
            CoTaskMemFree(reinterpret_cast<void*>(event.lParam));
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
        stopSpeech();
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
    } else if (!lstrcmpA(fields[0], "CANCEL") && count == 3) {
        unsigned int value;
        if (!parseNumber(fields[2], 2147483647, value)) { sendError("invalid-generation"); return; }
        stopSpeech();
        generation = value;
        wsprintfA(outgoing, "CANCELLED\t%s\t%u", session, generation);
        sendLine(outgoing);
    } else if (!lstrcmpA(fields[0], "PAUSE") && count == 3) {
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
    logMessage("Angel Legacy Voice Bridge 0.1.0 beta. Waiting for the host. Ctrl+C exits.");
    unsigned int used = 0;
    bool discardingLine = false;
    unsigned int serialErrors = 0;
    DWORD lastSerialError = 0;
    char buffer[256];
    while (!stopping) {
        DWORD received = 0;
        if (!ReadFile(serialPort, buffer, sizeof(buffer), &received, NULL)) serialFault = true;
        if (serialFault) {
            DWORD now = GetTickCount();
            if (static_cast<DWORD>(now - lastSerialError) > 10000) serialErrors = 0;
            lastSerialError = now;
            stopSpeech();
            session[0] = 0;
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
        speechEvents();
        if (speaking && !batchSpeech && !paused && voice->WaitUntilDone(0) == S_OK) {
            speaking = false;
            wsprintfA(outgoing, "DONE\t%s\t%u\t%u", session, generation, requestId);
            sendLine(outgoing);
        }
        if (session[0] && static_cast<DWORD>(GetTickCount() - lastContact) > HEARTBEAT_TIMEOUT) {
            stopSpeech();
            session[0] = 0;
            logMessage("Host disconnected; old speech discarded. Waiting for reconnection.");
        }
    }
    stopSpeech();
    CloseHandle(serialPort);
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
