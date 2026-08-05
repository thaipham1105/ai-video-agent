# Hướng dẫn thu mẫu giọng

Dành cho bước cuối của Gate D02: nhân bản **giọng của chính bạn** để đọc kịch bản.

> Mẫu giọng là dữ liệu sinh trắc học. Nó **không bao giờ** được đưa vào Git.
> Toàn bộ hướng dẫn dưới đây đặt file trong `F:\AI-VIDEO-AGENT-RUNTIME`, nằm
> ngoài repo và đã bị `.gitignore` chặn.

---

## 1. Thu âm

### Cần bao nhiêu

VieNeu chỉ dùng **tối đa 8 giây** (hằng số `_MAX_REF_SECONDS` trong engine), sau
khi tự cắt khoảng lặng đầu/cuối. Nên thu **10–15 giây** rồi để hệ thống tự cắt.

Ngắn hơn 3 giây thì giọng nhân bản sẽ kém giống.

### Nói gì

Nói một câu bình thường, **đúng cái giọng bạn muốn video phát ra**. Nếu video là
để bán hàng thì hãy nói với năng lượng của lúc bán hàng, đừng đọc đều đều.

Gợi ý một câu có đủ thanh điệu tiếng Việt:

> "Xin chào quý khách, tôi là *[tên bạn]*. Rất vui được đồng hành cùng anh chị
> trong việc tìm kiếm bất động sản phù hợp tại khu vực Đồng Nai."

Đọc tự nhiên, không cần đọc thật chuẩn từng chữ.

### Thu thế nào cho sạch

| Nên | Không nên |
|---|---|
| Phòng kín, có rèm hoặc nhiều đồ đạc | Phòng trống, tường gạch trần (vang) |
| Micro cách miệng 15–25 cm | Sát miệng (nổ hơi) hoặc quá xa (vọng) |
| Tắt quạt, điều hoà, TV | Có nhạc nền, tiếng xe, tiếng người khác |
| Nói đều một mức | Lúc to lúc nhỏ |
| Một người nói duy nhất | Nhiều giọng chồng nhau |

Tai nghe có mic của điện thoại cho kết quả tốt hơn mic laptop khá nhiều.

---

## 1b. Mức âm lượng đầu vào — phần quan trọng nhất

Bản thu đầu tiên hỏng ở đúng chỗ này: **peak chạm đúng 1,000 ở mọi giây**, tức
là đã bị ép kịch trần. Cắt phẳng đầu sóng sinh hài bậc cao — đó là cái tai nghe
ra là "thô", và nó **không sửa được bằng phần mềm** (thử rồi, không ăn thua).

### Mục tiêu

| Chỉ số | Đạt | Quy ra dBFS |
|---|---|---|
| **Đỉnh (peak)** | **0,60 – 0,70** | −4,4 đến −3,1 dBFS |
| Đỉnh tuyệt đối không được chạm | 1,00 | 0 dBFS |
| RMS (độ to trung bình) | 0,08 – 0,13 | −22 đến −18 dBFS |
| Sàn nhiễu lúc im lặng | dưới 0,003 | dưới −50 dBFS |
| Clipping | **0,000 %** | — |

Nói nôm na: **chỗ to nhất chỉ nên chạm khoảng hai phần ba vạch đo**, còn một
phần ba trống ở trên. Thấy vạch chạm đỉnh hoặc chuyển đỏ là đã hỏng.

### Tắt mọi thứ tự động — đây là thủ phạm chính

Máy tự chỉnh âm lượng chính là thứ đã đẩy bản thu cũ lên kịch trần. Phải tắt hết:

1. **Settings → System → Sound → Input**, chọn micro đang dùng.
2. Kéo **Input volume** xuống khoảng **60–70**, đừng để 100.
3. Vào **Advanced → More sound settings → tab Recording**, chuột phải micro →
   **Properties**:
   - tab **Levels**: tắt **Microphone Boost** (để +0 dB).
   - tab **Advanced/Enhancements**: tick **Disable all sound effects**.
   - nếu có mục **Automatic Gain Control (AGC)** hay **Noise Suppression** →
     **tắt hết**.

### Đừng thu bằng app gọi điện

Zalo, Messenger, Teams, Discord, Google Meet đều ép AGC và khử nhiễu rất mạnh —
chính chúng làm phẳng đỉnh và làm giọng bị "nén". Dùng app **Ghi âm** (Sound
Recorder) của Windows, hoặc app ghi âm thô của điện thoại.

### Khi xuất file, đừng "normalize"

Nhiều công cụ chuyển đổi có tuỳ chọn *Normalize* / *Chuẩn hoá âm lượng* bật sẵn.
**Tắt nó.** Normalize sẽ kéo đỉnh lên 1,0 và phá hết công sức chỉnh mức ở trên.

### Cách tự kiểm tra trước khi gửi

Thu thử **10 giây**, đặt vào `F:\AI-VIDEO-AGENT-RUNTIME\incoming\`, báo tôi. Tôi
đo peak/RMS/clipping và nói ngay là nên tăng hay giảm mức bao nhiêu — làm vậy
trước khi thu trọn 90 giây sẽ đỡ mất công thu lại.

---

## 1c. Chuẩn WAV phù hợp nhất cho VieNeu

Rút ra từ mã nguồn `vieneu 3.2.4` (`_load_mono`, `prepare_reference`,
`extract_speaker_fbank`):

| Thuộc tính | Khuyến nghị | Vì sao |
|---|---|---|
| Định dạng | **WAV PCM** | không nén, không mất dữ liệu |
| Độ sâu | **16-bit** | đủ dùng; 24-bit không lợi thêm ở đây |
| Kênh | **Mono (1 kênh)** | VieNeu tự hạ mono bằng cách cộng trung bình hai kênh — mic stereo lệch pha sẽ bị triệt tiếng |
| Sample rate | **48 000 Hz** | khớp đúng tần số đầu ra của v3 Turbo, đỡ một lần lấy mẫu lại |
| | *44 100 Hz cũng chấp nhận được* | bộ khử nhiễu nội bộ vốn đưa về 44 100 |
| Thời lượng | **60–90 giây** | 8 giây đầu là mẫu chính, phần còn lại là vật liệu dự phòng |
| Xử lý hậu kỳ | **KHÔNG** normalize, nén động, khử nhiễu, EQ, noise gate | mọi thứ đó đều làm méo đặc trưng giọng |

Tóm gọn một dòng: **WAV, mono, 48 kHz, 16-bit, peak 0,6–0,7, không xử lý gì thêm.**

Không có sẵn 48 kHz mono thì cứ thu ở mức cao nhất máy cho phép rồi gửi nguyên
bản — `aiva voice-add` tự chuẩn hoá về mono 16-bit, giữ nguyên sample rate.

### Định dạng file

`libsndfile 1.2.2` (đi kèm sẵn) đọc được, **không cần cài thêm gì**:

> `.wav` · `.mp3` · `.flac` · `.ogg` · `.aiff` · `.caf` · `.w64` · `.au`

**Không đọc được: `.m4a` và `.aac`** — đó là container MPEG-4, cần FFmpeg mà
FFmpeg thuộc Gate D04. Đây chính là định dạng mặc định của app Ghi âm trên
Windows 11 và của Ghi âm trên iPhone, nên hãy để ý.

Lệnh `aiva voice-add` tự chuẩn hoá mọi định dạng đọc được về **WAV mono 16-bit**
một lần lúc nhập, giữ nguyên sample rate.

Nếu app ghi âm của bạn chỉ xuất `.m4a`, đổi sang WAV như sau (Windows 11, không
cần cài gì):

1. Mở app **Ghi âm** (Sound Recorder).
2. Bấm **⚙ Cài đặt** ở góc trên phải.
3. **Định dạng ghi âm** → chọn **WAV**.
4. **Chất lượng âm thanh** → chọn mức cao nhất.
5. Ghi âm xong, chuột phải vào bản ghi → **Mở vị trí tệp** để lấy đường dẫn.

Ghi âm bằng điện thoại rồi gửi qua Zalo/Telegram thường ra `.m4a` hoặc `.ogg` —
`.ogg` thì dùng được luôn, `.m4a` thì không.

---

## 2. Đăng ký mẫu giọng vào hệ thống

Giả sử file của bạn ở `C:\Users\admin\Documents\giong-cua-toi.wav` và project tên
`demo-vn`. Nếu chưa có project nào, tạo trước:

```bash
uv run aiva plan --brief "Bán lô đất thổ cư tại Biên Hoà, sổ hồng riêng, giá 1,2 tỷ. Liên hệ 0909123456." --id demo-vn --duration 40
```

Rồi đăng ký giọng:

```bash
uv run aiva voice-add "C:\Users\admin\Documents\giong-cua-toi.wav" --project demo-vn --owner "Phạm Văn Thái"
```

Lệnh này tự động:

- **Chép** file vào `F:\AI-VIDEO-AGENT-RUNTIME\projects\demo-vn\assets\voice\`
  (ngoài Git),
- tính **SHA-256** và dung lượng,
- ghi vào `asset-manifest.json` với `consent.status = granted`, kèm chủ sở hữu,
  thời điểm và phạm vi sử dụng — đúng yêu cầu brief §4 và §7,
- cảnh báo nếu mẫu quá ngắn, quá dài hoặc bị clipping.

`--owner` là **ai sở hữu giọng nói đó**. Nếu là giọng người khác, bạn phải có sự
đồng ý rõ ràng của họ trước; xem
[assets-example/consent-template.md](../assets-example/consent-template.md).

---

## 3. Nghe thử giọng đã nhân bản

> Nhân bản giọng cần thêm extra `clone` (`torch` + `torchaudio`, bản CPU, ~150 MB).
> Giọng **dựng sẵn** thì không cần. Cài một lần:
>
> ```powershell
> uv sync --extra tts --extra clone
> ```
>
> Lý do: xem [ADR-0004](adr/0004-vieneu-dependencies.md) §4.

```bash
uv run aiva tts-check --ref-audio "F:\AI-VIDEO-AGENT-RUNTIME\projects\demo-vn\assets\voice\voice-chinh.wav"
```

Lệnh sinh WAV thật rồi kiểm tra đủ bốn mục của brief §D02.5: file tồn tại, thời
lượng, sample rate, clipping. File kết quả nằm ở
`F:\AI-VIDEO-AGENT-RUNTIME\healthcheck\tts-clone.wav`.

Muốn đọc thử một câu khác:

```bash
uv run aiva tts-check --ref-audio "...\voice-chinh.wav" --text "Câu bạn muốn nghe thử."
```

---

## 3b. Kế hoạch kiểm tra bản thu mới (đã chốt, tối đa 3 biến thể)

Khi bản thu mới nằm trong `incoming\`, tôi làm đúng hai bước sau và dừng.

### Bước 1 — kiểm tra kỹ thuật (không sinh giọng)

| Kiểm tra | Đạt khi |
|---|---|
| Định dạng thật (magic bytes) | `RIFF/WAVE`, không phải file đổi đuôi |
| Sample rate / kênh / độ sâu | ≥ 44 100 Hz, mono ưu tiên, 16-bit |
| Thời lượng | 60–90 giây |
| Đỉnh | 0,60 – 0,70 |
| Clipping | 0,000 % |
| RMS | 0,08 – 0,13 |
| Sàn nhiễu lúc im | dưới 0,003 |
| Mười giây đầu | đã có tiếng nói, không im lặng, không clipping |
| DC offset | gần 0 |

Không đạt mục nào thì tôi báo **trước khi sinh giọng**, kèm con số cụ thể và nên
chỉnh gì. Đỡ tốn công cả hai bên.

### Bước 2 — đúng 3 biến thể, mỗi bản đổi một thứ

Cả ba dùng **cùng câu thoại với `tts-clone.wav`** để so trực tiếp với bản đối
chứng anh đã chọn:

> "Xin chào, đây là bản kiểm tra giọng đọc tiếng Việt của hệ thống dựng video."

| | Cấu hình | Trả lời câu hỏi |
|---|---|---|
| **N1** | Y HỆT `tts-clone.wav`: int8, tham chiếu thô (8 giây đầu), `denoise=True`, `use_ref_codes=True`, `temperature=0.8` | **Thu lại có ăn thua không?** Đây là phép so sạch nhất: chỉ đổi mỗi bản thu. |
| **N2** | N1 nhưng `denoise=False` | Bản thu đã sạch thì bộ khử nhiễu có đang làm hại không? |
| **N3** | N1 nhưng model **fp32** | Nguồn sạch rồi thì độ chính xác cao hơn có giúp không? |

**Không** đụng lại những thứ đã chứng minh là vô ích trên nguồn cũ: gỡ kẹp trần,
chọn đoạn thủ công, lấy vân giọng từ 24 giây. V1–V4 cho thấy chúng không nâng
được độ giống.

N1 là biến thể quan trọng nhất. Nếu N1 vẫn quanh 5–6/10 thì vấn đề không nằm ở
bản thu mà ở giới hạn của chính mô hình với chất giọng này — lúc đó phải tính
hướng khác, chứ không chỉnh tham số tiếp.

---

## 4. Nếu giọng chưa giống

| Hiện tượng | Nguyên nhân thường gặp | Cách sửa |
|---|---|---|
| Giọng lơ lớ, sai vùng miền | Mẫu quá ngắn hoặc nói không tự nhiên | Thu lại 12–15 giây, nói như đang trò chuyện |
| Có tiếng rè, tiếng gió | Mic quá gần, hoặc nhiễu nền | Lùi mic ra 20 cm, tắt quạt/điều hoà |
| Nghe như đang ở trong hầm | Phòng vang | Thu trong phòng có rèm, thảm, tủ quần áo |
| Cảnh báo clipping | Thu quá to | Giảm âm lượng đầu vào rồi thu lại |
| Ngữ điệu đều đều | Mẫu đọc đều đều | Mẫu như thế nào thì giọng ra như thế đó |

Nhân bản giọng lấy **phong cách nói** từ mẫu, nên mẫu càng giống cách bạn muốn
video nói thì kết quả càng đúng.

---

## 5. Quy tắc an toàn

- Mẫu giọng nằm ở `F:\AI-VIDEO-AGENT-RUNTIME`, **không bao giờ** trong repo.
  `tests/test_no_secrets.py` sẽ báo đỏ nếu có file `.wav` lọt vào Git.
- Không dùng giọng người khác khi chưa có đồng ý rõ ràng bằng văn bản.
- Muốn rút lại: đổi `consent.status` thành `"denied"` trong `asset-manifest.json`
  rồi xoá file. Cost guard sẽ chặn mọi lần render thật sau đó.
- Video xuất ra luôn có nhãn "Nội dung có sử dụng AI" khắc trên hình
  (`project.ai_disclosure`), theo brief §4.
