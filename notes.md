# Reverse Engineering Notes

hiLife2 Android app v5.6.2 (`com.qj.hilife2`). Flutter app with native Java plugins and ARM shared libraries.

## Overview

The app uses a three-layer system to produce an unlock sound:

1. **hiLife API** (`https://api3.hilife.sg`) — user login, returns `userId` and apartment info
2. **XingWang API** (`http://sopen.hilife.sg:8888`) — manages unlock waves (sound, QR, Bluetooth, password)
3. **libdtv_util.so** — native ARM library that converts a server-provided content string into audio

This tool skips layer 3 entirely: the API returns an `audio_url` pointing to a static MP3 on the server, which the door reader accepts without timestamp validation.

## Tools Used

- **jadx** — APK decompilation (Java/Kotlin)
- **blutter** — Flutter/Dart AOT snapshot analysis (arm64)
- **Ghidra** — Native library (`libdtv_util.so`) decompilation

## hiLife Login

```
POST https://api3.hilife.sg/v3/app/login
```
```json
{
  "account": "email_or_phone",
  "password": "...",
  "device_type": "Android",
  "device_token": "",
  "voip_token": ""
}
```

The `account` and `password` field names were recovered using [blutter](https://github.com/aspect-build/blutter) on the arm64 `libapp.so` Dart AOT snapshot. The Dart source `flutter_app_hilife/api/http/api_util_v3.dart` constructs the login map at `ApiUtilV3::login` (address `0xd822ec`).

Response includes `data.user_id`, apartment details (`unit_list[].property_id`, `block_no`, `unit_no`), and a JWT `token`.

## XingWang API

Hardcoded credentials extracted from `com.hilife.siptalk.weiju.HLXingWangManager`:

| Constant | Value |
|----------|-------|
| `CLIENT_ID` | `0200101001` |
| `CLIENT_SECRET` | `96BB44D74D9FA5A603FB92A8F713DD802A127C17` |

### Auth

`POST /V1.0/users/access_token`

```json
{
  "grant_type": "client_credentials",
  "client_id": "0200101001",
  "client_secret": "96BB44D74D9FA5A603FB92A8F713DD802A127C17",
  "uuid": "<device_id>",
  "user_id": "<from_login>",
  "type": 0
}
```

The `uuid` field uses device IMEI, WiFi MAC (colons stripped), `android_id`, or `Build.SERIAL` as fallbacks (see `com.evideo.weiju.c`). Any random string works.

### Waves

`GET/POST /V1.0/apartments/{id}/unlocks/waves`

| Type | Name | Expiry | Use limit |
|------|------|--------|-----------|
| 0 | Owner/Resident | Never | Unlimited |
| 1 | Visitor | Configurable | Configurable |

Response includes `content` (opaque string) and `audio_url` (public, unauthenticated MP3 download).

### Other Endpoints

Discovered in `com.evideo.weiju.a.b`:

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/V1.0/apartments` | List apartments |
| DELETE | `/V1.0/apartments/{id}/unlocks/waves/{waveId}` | Delete wave |
| POST | `/V1.0/apartments/{id}/unlocks/passwords` | Create unlock password |
| POST | `/V1.0/apartments/{id}/unlocks/qrcodes` | Create unlock QR code |
| POST | `/V1.0/apartments/{id}/unlocks/bluetooth` | Create Bluetooth key |
| GET | `/V1.0/users/voip` | Get VoIP/SIP info |

## Native Audio Generation (libdtv_util.so)

Decompiled with Ghidra. The app generates audio locally for replay protection (timestamp-dependent), but the door reader does not validate timestamps.

### JNI Entry Point

`toAudio(JNIEnv*, jobject, jstring content, jint timestamp, jstring outputPath)`:

1. Calls `dtv_enc(content, len, buf, 32, timestamp)`:
   - Copies content bytes into buffer
   - Appends `0x23` (`#`) separator
   - Appends 4-byte big-endian timestamp
   - Returns new length

2. Calls `myrs_encode(rs_ctx, input, output, len, 2)`:
   - Reed-Solomon error correction (symbol size 2)
   - Adds redundancy for the door reader's acoustic decoder

3. Calls `DtvCore::toAudio(encoded_data, len, output_path, format)`:
   - `format=0`: uses `WavWriter` (48kHz, 16-bit PCM)
   - Detects `.mp3` → `Mp3Writer` (LAME encoder, 48kHz, 192kbps)
   - Detects `.pcm` → `PcmWriter` (raw samples)

### Audio Encoding

`DtvCore::writeData` — each input byte is split into 4x 2-bit symbols (MSB first). Each symbol is mapped to 3 simultaneous sine wave frequencies and written as 1024 samples at 48kHz (~21ms per symbol):

```
Constants (mode 0, from binary at offsets 0x46e58, etc.):
  sample_rate = 48000
  scale       = 46.875
  base_freq   = 100
  freq_step   = 6
  freq_spread = 30
  samples_per_symbol = 1024

For each 2-bit symbol (value 0-3):
  group = symbol_index % 3
  f_base = (value * freq_step + base_freq + group * freq_spread / 2 + freq_spread / 2) * scale
  f1 = f_base
  f2 = f_base + freq_spread * scale
  f3 = f_base + 2 * freq_spread * scale
```

`DtvCore::__gen` generates 1024 PCM samples of 3 superimposed sine waves:

```c
for (i = 0; i < 1024; i++) {
    sample = (sin(i * f1 * 2*PI / 48000)
            + sin(i * f2 * 2*PI / 48000)
            + sin(i * f3 * 2*PI / 48000)) * (1024 / 3);
}
```

**Preamble** (`writeHead`): 4 repetitions of a 3-tone chord at [6562.5, 7500.0, 8437.5] Hz, followed by sync tones at 6093.75 Hz (mode 0) or 7968.75 Hz (mode 1).

**Tail** (`writeTail`): 4 blocks of silence (zero-amplitude).