# D04-G — Thiết kế bake-off MuseTalk 1.5 vs Duix trên khẩu hình tiếng Việt

**Trạng thái: THIẾT KẾ. Chưa cài, chưa tải, chưa chạy, chưa sửa source.**

Nguồn dữ liệu: [D04_IMPLEMENTATION_PLAN.md](D04_IMPLEMENTATION_PLAN.md) §4/§6/§11
và [D04_LIPSYNC_MODEL_BAKEOFF_REPORT.md](D04_LIPSYNC_MODEL_BAKEOFF_REPORT.md)
§0/§7/§8/§10/§11. Mọi con số dưới đây **đã đo trên chính máy này**, không chép
từ tài liệu upstream.

Batch: **D04-G**. Gate của adapter mới: **`D04G`**.

---

## 0. Phạm vi — D04-G mở lại cái gì và KHÔNG mở lại cái gì

### 0.1 Quyết định D04 vẫn đứng nguyên

Bake-off D04 (2026-08-06) ghi **`B — MuseTalk 1.5 → LOẠI`**, căn cứ **độ nét vùng
miệng 4,77** so với Duix 7,26 và nguồn gốc 8,11.

**Đó là bằng chứng lịch sử hợp lệ và D04-G không phủ nhận nó.** Con số 4,77 đo
thật, trên cùng máy, cùng đầu vào. Batch này không chạy lại phép đo đó để mong ra
kết quả khác.

### 0.2 D04-G chỉ mở lại đúng một câu hỏi

D04-F (§11) cho thấy Duix **trượt 4/8 mốc âm môi tiếng Việt**, tập trung ở /v/ và
`-p` — hai nhóm âm mà WeNet/AISHELL không được huấn luyện. Bake-off D04 **chưa
bao giờ chấm MuseTalk theo 8 mốc âm môi**; nó chấm bằng metric tương quan mà chính
§8 cảnh báo là "biên phân biệt quá hẹp".

Vậy câu hỏi D04-G mở lại, và **chỉ** câu này:

> Bộ mã hoá Whisper đa ngôn ngữ của MuseTalk có sửa được các mốc âm môi tiếng Việt
> mà Duix trượt hay không?

### 0.3 Điều kiện để đổi quyết định production

Kết quả D04-G **chỉ** làm thay đổi quyết định production khi vượt **cả hai** cổng:

| Cổng | Ngưỡng | Vì sao |
|---|---|---|
| **Khẩu hình** | §7.2 | câu hỏi D04-G mở ra |
| **Chất lượng hình** | §7.3 | tiêu chí đã khiến D04 loại nó — **không được bỏ qua** |

Thắng một cổng không đủ. Bảng phân loại kết quả ở §7.5.

### 0.4 Cảnh báo trước: kết cục nào là khả dĩ nhất

Bake-off đã đo độ nét MuseTalk @30fps = **4,81**. Ngưỡng §7.3 là **≥ 6,17**
(85% của Duix 7,26). Trên bằng chứng hiện có, MuseTalk **nhiều khả năng trượt
cổng chất lượng hình**, kể cả khi thắng cổng khẩu hình.

Ghi rõ ở đây để batch không được đọc như một nỗ lực "phục hồi" MuseTalk. Kết cục
`LIP-SYNC WINNER — PRODUCTION FAIL` là kết quả **hợp lệ và hữu ích**: nó chỉ ra
đánh đổi thật, cho PO một dữ kiện để quyết, chứ không phải một thất bại.

---

## 1. Tương thích thực tế với máy này

Tất cả đã kiểm chứng bằng một lần chạy thật ở bake-off, **không phải suy đoán**.

| Hạng mục | Trạng thái đã đo | Kết luận |
|---|---|---|
| **WSL2** | `Ubuntu` (WSL 2) còn cài, hiện `Stopped`. GPU passthrough đã chạy được | ✅ dùng lại |
| **CUDA** | torch `2.0.1+cu118` trong venv riêng, không đụng CUDA global | ✅ |
| **RTX 4070 SUPER 12 GB** | peak **9.118 MiB** @25fps · **9.798 MiB** @30fps | ⚠️ xem §4 |
| **Giấy phép** | **MIT** cho cả code lẫn weights, cho phép thương mại | ✅ sạch nhất trong 4 ứng viên |
| **Repo** | đã clone tại `model-bakeoff/repos/MuseTalk`, commit `0a89dec45a0192b824e3cf4daf96c239440c5ed8` | ✅ |
| **Weights** | đã tải đủ, SHA-256 trong `weights/musetalk-weights-manifest.json` | ✅ |
| **venv Python 3.10** | nằm **trong WSL**, không trên ổ F (`model-bakeoff/envs` rỗng) | ❓ phải kiểm lại |

**Điểm không chắc duy nhất là venv.** `envs/` trên ổ F rỗng nghĩa là venv sống
trong filesystem của WSL. Việc đầu tiên của batch thực thi là kiểm tra venv còn
không. Xử lý khi thiếu: xem §9.3.

### 1.1 Bốn rào cản đã biết — nếu phải dựng lại venv

Chép từ §4 của D04 plan, đây là các lỗi **đã gặp thật**:

1. **`chumpy` không build được** trên setuptools mới → cài `mmpose --no-deps`
   cộng phụ thuộc runtime thật. MuseTalk chỉ dùng DWPose 2D, không cần SMPL.
2. **`setuptools` bị gỡ** trong các bước `--force-reinstall`, làm
   `mmengine.get_installed_path()` hỏng → ghim `setuptools<70`.
3. **`numpy` phải là 1.23.5.** Để pip đẩy lên 2.x thì `mmcv`/`cv2` gãy.
4. **`download_weights.bat` của upstream đặt `HF_ENDPOINT=hf-mirror.com`** —
   mirror bên thứ ba. **Từ chối**; weights đã có sẵn nên bước này không chạy lại.

Bài học riêng ở bake-off §10: kiểm import **sâu** (`from mmpose.apis import …`),
không chỉ `import mmpose`.

---

## 2. Kiến trúc provider/adapter

Hợp đồng `AvatarProvider` (D04-A→D04-D) sinh ra chính vì tình huống này. Thêm
backend = thêm một dòng vào registry; **không sửa orchestrator, không sửa
pipeline, không sửa schema**.

### 2.1 File mới (trong Git)

```
src/ai_video_agent/providers/musetalk/
├── __init__.py
├── capability.py     # MUSETALK_CAPABILITY + MUSETALK_RESOURCES (số ĐÃ ĐO)
├── mock.py           # MockMuseTalkProvider — chạy được từ D01
└── adapter.py        # MuseTalkAvatarProvider — gate D04G, chưa mở
```

Sửa đúng một dòng ngoài thư mục đó:

```python
# providers/registry.py
KNOWN_AVATAR = frozenset({"duix", "musetalk"})
```

**Chưa thực hiện trong batch thiết kế này.**

### 2.2 Capability — khai đúng sự thật đã đo

```python
MUSETALK_RESOURCES = ResourceEstimate(
    vram_mib=9_798,        # peak thật @30fps (bake-off §7). KHÔNG dùng số 25fps
    ram_mib=15_360,        # chạy trong WSL 15 GiB
    storage_mib=30_720,    # repo 15 GB + weights 14 GB đã nằm trên F
    deterministic_local=True,
    measured=True,
    measured_on="2026-08-06",
)

MUSETALK_CAPABILITY = AvatarCapability(
    backend_id="musetalk",
    backend_version="musetalk-v15@0a89dec4",
    native_fps=25,                          # ← khác Duix; xem §5.2
    supported_fps=frozenset({25, 30}),
    max_width=1920, max_height=1920,
    audio_sample_rate_hz=48_000,
    audio_channels=1,
    audio_encoder="whisper-tiny",           # ← điểm khác biệt cốt lõi
    languages_verified=frozenset({"multi"}),
    accepts_image_source=True,
    accepts_video_source=True,
    requires_gate="D04G",
    resources=MUSETALK_RESOURCES,
    source_url="https://github.com/TMElyralab/MuseTalk",
)
```

`languages_verified={"multi"}` khiến `language_is_verified()` trả `True` cho `vi`
⇒ **không có cảnh báo ngôn ngữ** như Duix. Đó là khác biệt sẽ hiện ngay trên CLI
và trong manifest — và là toàn bộ lý do batch này tồn tại.

### 2.3 Vào / ra

| | Duix (đã chạy) | MuseTalk (thiết kế) |
|---|---|---|
| Giao tiếp | HTTP tới container | **subprocess vào venv WSL** |
| Nguồn | đường dẫn container `/inputs/...` | đường dẫn WSL `/mnt/f/...` |
| Audio vào | WAV 48 kHz mono (tự hạ 16 kHz nội bộ) | WAV 48 kHz mono (Whisper tự hạ 16 kHz) |
| Ra | `.mp4` trong `/code/data` | `.mp4` trong thư mục `--result_dir` |
| Đưa về cache | pipeline `shutil.copy2` | **giống hệt** — code đã có sẵn |

Adapter thật gọi qua `wsl.exe -d Ubuntu -- bash -lc "<lệnh>"`. Không cài gì vào
Windows, không đụng PATH/Python/CUDA global.

### 2.4 Manifest và provenance — không cần sửa gì

`AvatarProvenanceRecord` (D04-C) đã đủ chỗ. Ánh xạ:

| Trường | Giá trị MuseTalk |
|---|---|
| `backend_id` | `musetalk` |
| `backend_version` | `musetalk-v15@0a89dec4` |
| `model_version` | `unet.pth sha256 7ebf6c98…7007` |
| `audio_encoder` | `whisper-tiny` |
| `languages_verified` | `["multi"]` |
| `native_fps` / `source_fps` | `25` / `30` |
| `checkpoint_sha256` | `7ebf6c98…7007` (**có** file rời, khác Duix để rỗng) |
| `image_digest` | `""` (không chạy Docker) |
| `params` | toàn bộ cờ inference ở §3.2 |
| `peak_vram_mib` | **đo được** qua `nvidia-smi` vòng lặp — Duix không đo được |

Hai chỗ MuseTalk **giàu bằng chứng hơn** Duix: có `checkpoint_sha256` thật và
đo được `peak_vram_mib` thật. §11.5 của D04 ghi rõ Duix không cho cả hai.

---

## 3. Phiên bản cần khoá

### 3.1 Đã có trên đĩa — chỉ xác minh lại SHA

| Thành phần | Nguồn chính thức | Bytes | SHA-256 |
|---|---|---|---|
| Repo MuseTalk | `github.com/TMElyralab/MuseTalk` | — | commit `0a89dec45a0192b824e3cf4daf96c239440c5ed8` |
| `musetalkV15/unet.pth` | `hf.co/TMElyralab/MuseTalk` | 3.400.074.924 | `7ebf6c98c181e20838e4c0054e96e944ac60d5d692cc01db42839fe11b787007` |
| `musetalkV15/musetalk.json` | như trên | 748 | `5b6923aee04d7169…1b47` |
| `sd-vae/diffusion_pytorch_model.bin` | `hf.co/stabilityai/sd-vae-ft-mse` | 334.707.217 | `1b4889b6b1d4ce7a…7ddc` |
| `whisper/pytorch_model.bin` | `hf.co/openai/whisper-tiny` | 151.095.027 | `9607f98a2b22d9e2…ac1d` |
| `dwpose/dw-ll_ucoco_384.pth` | `hf.co/yzd-v/DWPose` | 406.878.486 | `0d9408b13cd863c4…7a07` |
| `face-parse-bisent/79999_iter.pth` | `hf.co/ManyOtherFunctions/face-parse-bisent` | 53.289.463 | `468e13ca13a9b43c…6567` |
| `face-parse-bisent/resnet18-5c106cde.pth` | như trên | 46.827.520 | `5c106cde386e87d4…13f8` |

Nguồn đầy đủ: `model-bakeoff/weights/musetalk-weights-manifest.json` (10 mục).

### 3.2 Tham số inference — khoá đúng bake-off, chỉ đổi `fps`

```
--version v15  --unet_model_path ./models/musetalkV15/unet.pth
--unet_config ./models/musetalkV15/musetalk.json  --whisper_dir ./models/whisper
--fps 30  --use_float16  --batch_size 8  --bbox_shift 0  --extra_margin 10
--parsing_mode jaw  --left_cheek_width 90  --right_cheek_width 90
--audio_padding_length_left 2  --audio_padding_length_right 2
```

Chỉ `--fps` khác bản B của bake-off (25→30). Lý do ở §5.2.

---

## 4. VRAM và gate — tách rõ trước/sau khi nạp model

Bài học D04-F: ngưỡng 8.500 MiB đặt cho lúc container **chưa** nạp model, rồi bị
áp lại sau khi nạp — và tự chặn chính nó. **Không lặp lại lỗi đó.**

### 4.1 Ba mốc, ba ngưỡng khác nhau

| Mốc | Ngưỡng | Vì sao |
|---|---|---|
| **G1 — ngay trước khi nạp model** | VRAM trống ≥ **10.300 MiB**, đo **3 lần liên tiếp** | peak đo được 9.798 + biên 500 MiB |
| **G2 — sau khi nạp model, trước inference** | còn ≥ **1.000 MiB** ngoài phần model đã giữ | chỉ kiểm còn chỗ cho batch |
| **G3 — trong lúc chạy** | ghi `peak_vram_mib`, **không chặn** | chặn giữa chừng = mất lượt, không cứu được gì |

**Không hạ ngưỡng trong mọi tình huống.** Trượt G1 hoặc G2 ⇒ STOP, báo số thực
tế, chờ PO.

### 4.2 Trạng thái hiện tại CHƯA đạt G1

| | |
|---|---|
| Đo gần nhất (sau khi tắt container Duix, D04-F) | **10.195 MiB** trống |
| Ngưỡng G1 | **10.300 MiB** |
| **Thiếu** | **105 MiB** |

Phải giải phóng thêm VRAM rồi đo lại **3 lần liên tiếp** mới được nạp model.
Không dừng tiến trình nào của người dùng — chỉ báo số và chờ.

### 4.3 Vì sao biên hẹp đến vậy

| | Duix | MuseTalk @30fps |
|---|---|---|
| Peak đo được | 7.004 MiB | **9.798 MiB** |
| Trần card | 12.282 MiB | 12.282 MiB |
| Biên nếu desktop chiếm 1.800 MiB | 3.480 MiB | **684 MiB** |
| Biên nếu desktop chiếm 3.100 MiB | 2.178 MiB | **−616 MiB → OOM** |

Ở D04-F, desktop chiếm 3.117 MiB tại một thời điểm — mức đó **làm MuseTalk OOM**.

`--batch_size 8` là cờ hạ VRAM nếu cần, nhưng đổi nó là đổi điều kiện so sánh với
bản B của bake-off. Chỉ dùng khi PO chấp nhận mất tính so sánh.

---

## 5. Một lượt render duy nhất, không retry

### 5.1 Đầu vào — khoá tuyệt đối từ D04-F

Điều kiện tiên quyết của "công bằng": **cùng WAV, cùng video nguồn, cùng câu
thoại**. Không sinh TTS mới. **Xác minh SHA-256 trước khi chạy**; lệch một byte
⇒ STOP.

| Thứ | Đường dẫn | SHA-256 phải khớp |
|---|---|---|
| WAV (đầu ra TTS của D04-F) | `projects/sample-khau-hinh/artifacts/shot-khau-hinh/e33ed107fbb38526/audio.wav` | `0d072f5e45ececc4ce51b498b818af31428ea089ec1490764a4daf3b8f863a03` |
| Video nguồn | `projects/sample-khau-hinh/assets/avatar/avatar-goc.mp4` | `71cf0baa2f4506f95019c0ccffd702bfff6c29f1b7b18e96c08c73c7271180da` |
| **Đối chứng Duix (thô)** | `.../artifacts/shot-khau-hinh/e33ed107fbb38526/avatar.mp4` | `35ce43971b6899003f244b45e603749e7b186c90fa56bbb2ec7ed2df744fd143` |

Câu thoại nguyên văn (55 âm tiết):

> Bà con mình lưu ý: miếng đất mặt tiền này bề ngang tám mét, pháp lý minh bạch,
> sổ hồng bao sang tên. Mình bán gấp giá một tỷ hai, bao phí công chứng. Vị trí
> đẹp, bên phải chợ, buổi mai vẫn mát, ai mua thì mình bàn thêm về phương án vay vốn.

`voice_asset_id = "voice-chinh"` ghi ở đây chỉ để truy vết WAV đến từ đâu —
**không dùng lại** trong batch này vì không sinh TTS mới.

### 5.2 30 fps là lượt chính thức DUY NHẤT

MuseTalk gốc 25 fps; Duix và toàn bộ project dùng 30 fps.

**D04-G chạy 30 fps. Không chạy 25 fps. Không retry.**

Lý do: 25 fps buộc thêm bước chuyển nguồn 30→25 và đầu ra 25→30; mỗi bước làm
hỏng phép so từng khung. Chạy 30 fps giữ **cùng video nguồn, cùng dòng thời gian,
cùng số khung** với bản Duix đã có.

Đây là **bất lợi có chủ ý cho MuseTalk** — bake-off đo r 0,272 @30fps so với
0,320 @25fps. Ghi rõ trong mọi báo cáo. Nếu MuseTalk thắng ở 30 fps thì kết luận
càng mạnh.

> Muốn có số liệu 25 fps thì phải mở **batch mới, PO duyệt riêng**. Không được
> thêm vào D04-G dưới bất kỳ hình thức nào, kể cả khi kết quả 30 fps sát ngưỡng.

### 5.3 Trình tự

| Bước | Nội dung | Tốn |
|---|---|---|
| A | Kiểm venv WSL còn không; xác minh 10 SHA weights; xác minh 3 SHA đầu vào §5.1 | 0, chỉ đọc |
| B | **Nếu venv thiếu → STOP**, xin duyệt batch cài đặt riêng (§9.3) | — |
| C | Viết `MockMuseTalkProvider` + capability → 19 test contract phủ ngay | 0 |
| D | Viết `MuseTalkAvatarProvider`, gate `D04G` đóng, chưa chạy | 0 |
| E | **Căn chỉnh §6 trên WAV — phải ra đủ 55 âm tiết TRƯỚC khi chạm GPU** | 0 |
| F | Dry-run `--provider-mode real` — xác nhận 0 USD, gate, preflight | 0 |
| G | **G1: đo VRAM 3 lần.** Trượt thì STOP | 0 |
| H | **Chạy đúng 1 lượt**, ghi `peak_vram_mib` bằng vòng lặp `nvidia-smi` | ~4 phút GPU |
| I | Kiểm tính toàn vẹn đầu ra §6.3. Trượt thì STOP, **không chấm** | 0 |
| J | Chấm §7, dựng video và filmstrip đối chiếu | 0 |

**Không retry ở bất kỳ bước nào.** Hỏng ở H = dừng, báo cáo, chờ PO.

Thứ tự E **trước** G/H là có chủ đích: nếu căn chỉnh không ra đủ 55 âm tiết thì
phép chấm vô nghĩa, và chạy GPU trước sẽ tiêu một lượt vào một bài test không
chấm được.

---

## 6. Khoá phép so và phương pháp căn chỉnh

### 6.1 Khoá phép so — cùng một đường ống đo cho cả hai model

| Điều kiện | Quy định |
|---|---|
| Đối tượng so | **avatar thô của cả hai** (`avatar.mp4` do backend sinh) |
| **Cấm** | so bản đã compose/subtitle của model này với bản thô của model kia |
| Decoder | cùng một binary ffmpeg, cùng cờ |
| Trích khung | cùng lệnh, cùng cửa sổ, cùng số khung |
| ROI vùng miệng | cùng toạ độ crop, cùng kích thước, cùng thang scale |
| Metric độ nét | cùng hàm, cùng tham số |
| Bộ mốc thời gian | **một bộ duy nhất**, tính từ WAV chung |

Bản đã ghép có phụ đề và nhãn AI đè lên khung; so nó với bản thô là so hai thứ
khác nhau.

### 6.2 Căn chỉnh — M1 phải ra đủ 55 âm tiết trước khi chạm GPU

§11.3 của D04 ghi rõ điểm yếu: mốc từng từ là **nội suy tuyến tính** từ 3 cue phụ
đề. Với bake-off, lỗi đó có thể **thiên vị một model**.

**Điểm mấu chốt: cả hai video dùng CHUNG một file WAV.** Nên căn chỉnh **một lần**
trên WAV đó rồi áp **cùng bộ mốc** cho cả hai video. Sai số căn chỉnh (nếu có) tác
động **giống hệt nhau** lên hai bên ⇒ **không thiên vị**.

| | Phương án | Tải thêm | Ghi chú |
|---|---|---|---|
| **M1** | **Phân đoạn âm tiết theo năng lượng** | **0 byte** | Tiếng Việt âm tiết tính: mỗi âm tiết ≈ một đỉnh năng lượng. Văn bản đã biết ⇒ bài toán là "tìm 55 đỉnh", không phải nhận dạng |
| M2 | Montreal Forced Aligner + model tiếng Việt | ~1,5 GB | chuẩn vàng, nhưng kéo conda vào máy |
| M3 | WhisperX + `wav2vec2-base-vietnamese-250h` | ~1,2 GB | pip được, thêm một phụ thuộc torch |

**Điều kiện cứng:** M1 phải ánh xạ ra **đúng 55 âm tiết**. Không đủ 55 ⇒ **STOP,
không chấm, không render tiếp**, và xin duyệt M2/M3 như một batch riêng (có tải
thêm).

Bộ mốc **ghi ra JSON và commit vào Git**, để lần chấm sau tái lập được và PO kiểm
được từng con số.

### 6.3 Kiểm toàn vẹn đầu ra — chạy TRƯỚC khi chấm

Với **từng** file đầu ra (Duix và MuseTalk), kiểm:

| Phép kiểm | Cách | Trượt thì |
|---|---|---|
| `start_time` của stream video và audio | `ffprobe -show_streams` | STOP |
| PTS khung đầu | `ffprobe -show_frames` khung 0 | STOP |
| Duration drift hình vs tiếng | `\|dur_video − dur_audio\|` | STOP nếu **> 1 khung** (@30fps = 0,0334 s) |
| Số khung đếm thật | `ffprobe -count_frames` | ghi nhận |

Lệch A/V quá **một khung** ở bất kỳ đầu ra nào ⇒ **STOP, không chấm và không
render tiếp**. Một khung lệch là đủ để biến "đạt" thành "trượt" ở một mốc âm môi.

### 6.4 Cấm dịch mốc sau khi xem kết quả

Bộ mốc §6.2 được chốt **trước** khi nhìn bất kỳ khung hình nào của MuseTalk.

**Cấm tuyệt đối:** dịch mốc riêng cho một backend sau khi thấy kết quả không như
mong đợi. Nếu phát hiện bộ mốc sai, phải sửa cho **cả hai** và **chấm lại cả hai**
từ đầu, ghi rõ đã sửa gì và vì sao.

### 6.5 Trích khung

Mỗi mốc lấy cửa sổ **±0,15 s** (9 khung @30fps) trên video thô. Crop đúng cùng
vùng miệng cho cả hai model.

---

## 7. Tiêu chí PASS/FAIL

### 7.1 Tám mốc âm môi — giữ nguyên bộ của D04-F

`bà` · `miếng` · `mặt` · `pháp` · `gấp` · `vị` · `đẹp` · `vay vốn`

| Mốc | Âm phải thấy | Đạt khi |
|---|---|---|
| `bà` | /b/ bật môi | ≥ 1 khung **khép kín** trong cửa sổ |
| `miếng` | /m/ khép môi | ≥ 1 khung khép kín |
| `mặt` | /m/ khép môi | ≥ 1 khung khép kín |
| `pháp` | /f/ môi–răng + `-p` khép | thấy môi dưới chạm răng trên **và** khép kín cuối |
| `gấp` | `-p` khép cuối | ≥ 1 khung khép kín ở **nửa sau** cửa sổ |
| `vị` | /v/ môi–răng | môi dưới tụt vào răng trên |
| `đẹp` | `-p` khép cuối | ≥ 1 khung khép kín ở nửa sau |
| `vay vốn` | /v/ ×2 | ≥ 1 động tác môi–răng phân biệt được |

Baseline Duix (D04-F §11.3): **2 đạt / 2 mơ hồ / 4 trượt**.

### 7.2 Cổng khẩu hình

| | Ngưỡng |
|---|---|
| Tổng | **≥ 6/8 mốc đạt** |
| Mốc cuối `-p` | **không trượt bất kỳ mốc nào** trong 3 mốc `pháp`, `gấp`, `đẹp` |

Ba mốc `-p` được tách riêng vì tiếng Quan Thoại **không có** phụ âm cuối `-p` —
đây là chỗ khác biệt bộ mã hoá phải lộ ra nếu nó có ý nghĩa.

> **Lưu ý về baseline:** Duix hiện là `pháp ◐ · gấp ❌ · đẹp ✅` ⇒ **Duix cũng
> trượt cổng khẩu hình này**. Ngưỡng đặt theo yêu cầu production, không theo mức
> backend đang dùng.

### 7.3 Cổng chất lượng hình

| | Ngưỡng | Nguồn |
|---|---|---|
| **Độ nét ROI miệng** | **≥ 85% baseline Duix** ⇒ **≥ 6,17** (Duix 7,26) | tiêu chí đã khiến D04 loại MuseTalk |
| **Seam / flicker** | không thấy rõ khi xem **filmstrip** *và* **video thời gian thực** | mắt người, không phải metric |
| A/V lệch | ≤ 0,02 s | D04 plan §6.3 |
| Render / giây video | ≤ 30 s | D04 plan §6.3 |
| Peak VRAM | ≤ 10.000 MiB | D04 plan §6.3 |
| Giải mã sạch | không dòng lỗi | D04 plan §6.1 |

Độ nét đo bằng **cùng metric, cùng ROI** đã dùng ở bake-off §8 — nếu không thì
con số 7,26 không còn là baseline hợp lệ.

### 7.4 Phân loại kết quả

| Khẩu hình §7.2 | Chất lượng hình §7.3 | Kết luận |
|---|---|---|
| Đạt | Đạt | **PRODUCTION CANDIDATE** |
| Đạt | Trượt | **LIP-SYNC WINNER — PRODUCTION FAIL** |
| Trượt | Đạt | không giải quyết được câu hỏi D04-G ⇒ giữ Duix |
| Trượt | Trượt | giữ Duix, xem §7.5 |

**Chỉ ô đầu tiên** mới được gọi là `PRODUCTION CANDIDATE`. Máy có quyền từ chối,
không có quyền chấp nhận — mọi ngưỡng đạt vẫn phải PO xem bằng mắt mới quyết.

### 7.5 Nếu cả hai ≤ 4/8

Kết luận được phép rút ra, và **chỉ** kết luận này:

> Hai backend cụ thể trong bake-off này — Duix và MuseTalk 1.5, ở cấu hình đã
> khoá, trên câu thoại này — **không đạt bài test âm môi tiếng Việt**.

**Không** được suy rộng thành "kiến trúc audio-to-viseme thất bại". Bài test chỉ
phủ 2 model, 1 câu thoại, 1 người nói, 1 cấu hình fps. Đó là bằng chứng về hai
điểm dữ liệu, không phải về một lớp kiến trúc.

**Chặn thử model thứ ba** trừ khi có **giả thuyết mới hoặc bằng chứng mới** — ví
dụ một bộ mã hoá được huấn luyện có tiếng Việt, hoặc một bài test cho thấy nút
thắt nằm ở chỗ khác. Thử model tiếp theo mà không có giả thuyết là lặp lại cùng
một phép đo với hy vọng ra kết quả khác.

### 7.6 Bảng so sánh sẽ điền

| | A — Duix (đã có) | B — MuseTalk (sẽ đo) |
|---|---|---|
| Bộ mã hoá tiếng | `wenet-aishell` (Quan Thoại) | `whisper-tiny` (đa ngôn ngữ) |
| Ngôn ngữ kiểm chứng | `['zh']` | `['multi']` |
| Cảnh báo ngôn ngữ trên CLI | **có** | **không** |
| Âm môi 8 mốc | **2 / 2 / 4** | *(điền)* |
| Ba mốc `-p` | `◐ ❌ ✅` | *(điền)* |
| Độ nét ROI miệng | 7,26 | *(điền — bake-off đo 4,81 @30fps)* |
| Peak VRAM | 7.004 MiB *(không đo lại ở D04-F)* | *(đo được)* |
| Render / giây video | 3,57 s | *(bake-off: ~24 s)* |
| A/V lệch | 0,000 s | *(bake-off: 0,013 s @30fps)* |
| Giấy phép | Docker image, chưa rà kỹ | **MIT**, cho thương mại |
| `checkpoint_sha256` | rỗng (trong image) | có thật |

Đầu ra bằng chứng: `SO-SANH-DUIX-MUSETALK-VUNG-MIENG.mp4` (cạnh nhau, cùng mốc)
và một filmstrip mỗi model, để PO xem trực tiếp như đã làm ở D04.

---

## 8. Rủi ro, dung lượng, thời gian

### 8.1 Rủi ro

| Mức | Rủi ro | Giảm thiểu |
|---|---|---|
| **Cao** | **Chưa đạt G1.** Đo gần nhất 10.195 MiB, thiếu 105 MiB | Giải phóng VRAM rồi đo lại 3 lần. Không hạ ngưỡng |
| **Cao** | **OOM.** Peak 9.798 MiB; desktop chiếm 1.800–3.100 MiB | G1/G2/G3 §4. Chạy lúc máy rảnh |
| **Cao** | **venv WSL có thể đã mất** | Bước A kiểm trước. Thiếu ⇒ STOP, xin batch riêng (§9.3) |
| **Cao** | **Độ nét 4,81 vs ngưỡng 6,17** — nhiều khả năng trượt cổng §7.3 | Không giấu; đó là kết cục `LIP-SYNC WINNER — PRODUCTION FAIL`, vẫn hữu ích |
| **Trung bình** | **30 fps là bất lợi có chủ ý** cho MuseTalk | Ghi rõ mọi nơi. 25 fps là batch riêng, không thêm vào D04-G |
| **Trung bình** | **M1 không ra đủ 55 âm tiết** | STOP trước GPU; xin duyệt M2/M3 |
| **Thấp** | Whisper-tiny là bản nhỏ nhất | Là cấu hình chính thức của MuseTalk v1.5, không tự đổi |

### 8.2 Dung lượng

| Hạng mục | Cần tải thêm |
|---|---|
| Repo MuseTalk | **0** — đã có, commit `0a89dec4` |
| Weights (10 file) | **0** — đã có, SHA-256 đã ghi |
| venv WSL *(nếu phải dựng lại)* | ~7,5 GB đĩa WSL, tải ~2,5 GB wheel từ PyPI |
| Căn chỉnh M2/M3 *(chỉ khi M1 hỏng)* | 1,2–1,5 GB |
| **Đường ưu tiên (venv còn + M1)** | **0 byte** |
| **Xấu nhất (venv mất + M2)** | **~4 GB tải, ~7,5 GB đĩa WSL** |

Xem §9.3: **"0 byte" là đường ưu tiên, không phải bảo đảm.**

### 8.3 Thời gian

| Bước | Ước |
|---|---|
| A — kiểm venv + xác minh SHA | 10 phút |
| C+D — mock + adapter + test | 2–3 giờ |
| E — căn chỉnh 55 âm tiết | 30 phút |
| F — dry-run | 5 phút |
| G+H — G1 + một lượt render | 10 phút *(render ~4 phút)* |
| I+J — kiểm toàn vẹn, chấm, video đối chiếu | 1 giờ |
| **Tổng (venv còn)** | **~4,5 giờ** |

---

## 9. Điều kiện dừng và điểm PO duyệt

### 9.1 Năm điều kiện STOP cứng

Chạm bất kỳ điều nào ⇒ dừng, báo số thực tế, chờ PO. Không tự xử lý, không hạ ngưỡng.

1. **venv WSL thiếu** ⇒ §9.3
2. **SHA đầu vào §5.1 không khớp**
3. **M1 không ra đủ 55 âm tiết** (§6.2) — trước khi chạm GPU
4. **G1 < 10.300 MiB** hoặc **G2 < 1.000 MiB** (§4)
5. **A/V lệch > 1 khung** hoặc PTS/start_time bất thường ở bất kỳ đầu ra nào (§6.3)

### 9.2 Không retry

Một lượt render duy nhất. Hỏng vì bất kỳ lý do gì — OOM, lỗi venv, lỗi model —
đều **không chạy lại trong batch này**.

### 9.3 "0 byte tải" là đường ưu tiên, không phải bảo đảm

Repo và weights đã nằm trên ổ F, xác minh được bằng SHA. Nhưng **venv nằm trong
WSL và chưa kiểm chứng còn hay mất**.

Nếu venv thiếu ⇒ **STOP ngay**, không tự cài. Việc dựng lại kéo theo ~2,5 GB
wheel từ PyPI và bốn rào cản §1.1 — đó là **một batch cài đặt riêng, phải được PO
duyệt**, không phải một bước phụ của D04-G.

### 9.4 PO đã duyệt trong batch này

| | |
|---|---|
| Tên batch và gate | **D04-G** / `requires_gate = "D04G"` |
| Phạm vi | mở lại **chỉ** câu hỏi khẩu hình; kết luận D04 về độ nét vẫn đứng |
| fps | **30 fps, lượt duy nhất, không retry**; 25 fps là batch riêng |
| Ngưỡng VRAM | G1 10.300 / G2 1.000 / G3 ghi nhận, **không hạ** |
| Căn chỉnh | M1 trước, phải đủ 55 âm tiết; M2/M3 cần duyệt riêng |
| Cổng PASS | §7.2 khẩu hình **và** §7.3 chất lượng hình |

### 9.5 Batch thiết kế này KHÔNG làm gì

Không cài model · không kéo image · không tải byte nào · không khởi động WSL ·
không chạy GPU · không viết adapter · không sửa `KNOWN_AVATAR` · không sửa source ·
không gọi API. Chỉ đọc tài liệu đã commit, metadata weights đã ghi, và viết file này.

---

D04G_STATUS = THIẾT KẾ ĐÃ DUYỆT — CHỜ DUYỆT BƯỚC TRIỂN KHAI SOURCE
