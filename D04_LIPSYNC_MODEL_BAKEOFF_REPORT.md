# D04-LIPSYNC-MODEL-BAKEOFF — Báo cáo

Gate thử nghiệm riêng, mở sau khi PO từ chối chất lượng hình ảnh của D04.
Mục tiêu: thử có kiểm soát các mô hình lip-sync khác để tìm ứng viên thay thế Duix.

> **D04 = APPROVED.** PO đã xem đủ hai video đối chiếu vùng miệng và toàn khung
> A–B–C–C2, và đã quyết định. Xem [mục 0](#0-quyết-định-của-po--d04-approved).
>
> **Chưa tích hợp vào pipeline. Chưa thay đổi production.** Việc tích hợp cần
> một gate riêng được duyệt trước.

---

## 0. Quyết định của PO — D04 APPROVED

Ngày duyệt: 2026-08-06. Căn cứ: PO xem trực tiếp
`SO-SANH-4-MODEL-VUNG-MIENG.mp4` và `SO-SANH-4-MODEL-TOAN-KHUNG.mp4`.

### 4 ứng viên chính

| Mã | Ứng viên | Quyết định của PO |
|---|---|---|
| **A** | **Duix** (`duix.avatar@sha256:1970424d…`) | **PRODUCTION WINNER** |
| **B** | MuseTalk 1.5 (`0a89dec4…`) | **LOẠI** |
| **C** | LatentSync 1.6 (`a229c394…`, res 512) | **KHÔNG PHÙ HỢP VẬN HÀNH** trên RTX 4070 SUPER 12 GB |
| **C2** | LatentSync 1.5 (`a229c394…`, res 256) | **BACKUP / RESEARCH CANDIDATE** |

### 5 đầu ra thử nghiệm

4 ứng viên sinh ra 5 đầu ra, vì MuseTalk được chạy ở hai cấu hình fps.

| # | Đầu ra | Ứng viên | fps | Khung | Peak VRAM | SHA-256 |
|---|---|---|---|---|---|---|
| 1 | `A_duix_baseline.mp4` | A | 30 | 228 | 7.004 MiB | `5f7ce378e128317b…` |
| 2 | `B_musetalk_v15_fps25.mp4` | B | 25 | 192 | 9.118 MiB | `7c313a100102ebec…` |
| 3 | `B2_musetalk_v15_fps30.mp4` | B | 30 | 230 | 9.798 MiB | `146bc075a10c1545…` |
| 4 | `C_latentsync_1.6_raw.mp4` | C | 25 | 194 | 11.942 MiB | `1f0be3dae5bbef43…` |
| 5 | `C_latentsync_1.5_raw.mp4` | C2 | 25 | 194 | 7.264 MiB | `a25a9975e52a40a9…` |

Ngoài 5 đầu ra hợp lệ trên còn giữ `_LOI_C2_latentsync_1.5_config512_lech.mp4` —
**không phải đầu ra thử nghiệm**, chỉ là bằng chứng của lỗi cấu hình #10 (mục 10).

### Hệ quả của quyết định

- **Duix ở lại production.** Không phải thay adapter, không phải đổi `registry.py`,
  không phát sinh bước chuyển 25→30 fps, không phải rà lại giấy phép của model mới
  cho đường production. Trần khẩu hình tiếng Việt của Duix (mục 8) là **giới hạn đã
  được chấp nhận**, không còn là lỗi mở.
- **LatentSync 1.5 là ứng viên dự phòng/nghiên cứu.** Môi trường, weights (SHA-256 trong
  `latentsync-1.5-weights-manifest.json`) và lệnh chạy đã dựng sẵn, tái lập được ngay.
  Nếu sau này cần đánh giá lại, không phải làm từ đầu. Lưu ý ràng buộc còn nguyên:
  **ép 25 fps**, **audio ra 16 kHz**, weights **openrail++** có hạn chế hành vi.
- **LatentSync 1.6 bị gạt vì vận hành, không phải vì chất lượng.** Nó chạy được, nhưng
  peak 11.942/12.282 MiB chỉ dư 340 MiB — bất kỳ ứng dụng nào chiếm thêm VRAM cũng làm
  OOM. Không tái lập ổn định trên máy này.
- **MuseTalk bị loại**, dù giấy phép MIT sạch nhất và A/V lệch 0,000 s.

---

## 1. Checkpoint đầu và cuối

| Mục | Đầu batch | Cuối batch |
|---|---|---|
| Repo | `F:\AI-VIDEO-AGENT` | không đổi |
| Branch | `main` | `main` |
| HEAD | `5ec48819ed3a8a2d80a1a5a2d2dc6b848e6959b5` (root commit) | **không đổi** |
| Số commit | 1 | 1 |
| Remote | không có | không có |
| Worktree | sạch | sạch, trừ đúng file báo cáo này |
| `CURRENT_GATE` | `"D04"` | `"D04"` — không đổi |
| Duix baseline | nguyên vẹn | **không render lại, không ghi đè** |

Checkpoint đầu **ĐẠT TOÀN BỘ**, xác minh trước khi tải bất kỳ byte nào.

## 2. Hash bất biến — xác nhận không đổi

Xác minh đầy đủ theo `asset-manifest.json` của `demo-vn`, cả hash lẫn số byte:

| Tài sản | SHA-256 | Byte | Kết quả |
|---|---|---|---|
| `avatar-goc.mp4` (video nguồn) | `71cf0baa2f4506f95019c0ccffd702bfff6c29f1b7b18e96c08c73c7271180da` | 88.079.132 | **KHỚP MANIFEST** |
| `golden-a-mo-dau.wav` | `311471e7d059ba11245586e18d5ff2b6a5eda5b81f1a48a2af4d7d2e6253985c` | 737.324 | **KHỚP MANIFEST** |
| `voice-chinh.wav` | `a578a519530b982e2cfead29fdae1c300dd694ddebcc9f85e2cefa8589d7d9da` | 11.751.502 | KHỚP MANIFEST |
| `voice-v2.wav` | `e9048c66dad79db22d29db962ba3e4af2695983de68620a724148c488b73f42a` | 7.268.396 | KHỚP MANIFEST |
| Duix baseline `avatar.mp4` | `5f7ce378e128317b2bfc6babfd8c909569966f8b071aba23e6fef04276eecb7f` | 11.932.459 | không đổi |

Kiểm tra lại lần cuối sau toàn bộ thử nghiệm: **cả ba đều KHÔNG ĐỔI**.
Không tạo TTS mới. Không đổi nội dung hay độ dài lời nói. Không ghi đè video đối chứng nào.

## 3. Môi trường

| Mục | Giá trị |
|---|---|
| GPU | NVIDIA RTX 4070 SUPER, 12.282 MiB, driver 591.86, CUDA 13.1 |
| VRAM bị chiếm bởi app desktop | 1.700–4.030 MiB (chỉ ghi nhận, **không dừng tiến trình nào**) |
| RAM host | 31,8 GB |
| RAM WSL | 6 GB lúc đầu → **16 GB sau khi PO tự sửa `.wslconfig`** |
| Đĩa F trống | 380,5 GB |
| Docker | 29.6.1 |
| WSL | WSL2 Ubuntu, kernel `6.18.33.2-microsoft-standard-WSL2`, GPU passthrough OK |
| FFmpeg | 9.0 (Windows, Gyan.dev) · 7.0.2 static (imageio-ffmpeg trong WSL) |
| Trình biên dịch | g++/gcc/cc 15.2.0, GNU Make 4.4.1 — **PO tự cài `build-essential`** |

Cách ly: mỗi model một venv Python 3.10 riêng trong WSL2
(`~/bakeoff-envs/musetalk`, `~/bakeoff-envs/latentsync`).
Không đổi PATH hệ thống, Python global, CUDA global, không cài gói vào môi trường chính.
Chỉ chạy một model tại một thời điểm.

## 4. Candidate matrix

| | A — Duix | B — MuseTalk 1.5 | C — LatentSync 1.6 | C2 — LatentSync 1.5 | Ditto |
|---|---|---|---|---|---|
| Repo chính thức | `guiji2025/duix.avatar` (Docker) | `github.com/TMElyralab/MuseTalk` | `github.com/bytedance/LatentSync` | cùng repo C | `github.com/antgroup/ditto-talkinghead` |
| Commit/digest ghim | `sha256:1970424d219cbb6a…` | `0a89dec45a0192b824e3cf4daf96c239440c5ed8` | `a229c3948406bc2cf6eaf4873e662e70c6a04746` | cùng commit C | — |
| Checkpoint | image 4,66 GB | `musetalkV15/unet.pth` | `LatentSync-1.6/latentsync_unet.pt` | `LatentSync-1.5/latentsync_unet.pt` | — |
| SHA-256 checkpoint | (trong image) | `7ebf6c98c181e208…` | `0a478e89eb660f82da4c35dbdde8a5adfb27f99d1b4e50edd03729e1e98316d3` | `6440b49a7ccceff56cdc001f5f17605216337f5bbd66fa360139768926e23f51` | — |
| Giấy phép code | cộng đồng riêng của Duix | **MIT** | **Apache-2.0** | **Apache-2.0** | Apache-2.0 |
| Giấy phép weights | cộng đồng riêng | **MIT** — "any purpose, even commercially" | **openrail++** | **openrail++** | — |
| Thương mại | **phải đọc nguyên văn license trước khi phát hành** | **được** | được, kèm hạn chế hành vi | được, kèm hạn chế hành vi | — |
| Bộ mã hoá tiếng | **WeNet / AISHELL (tiếng Quan Thoại)** | **Whisper (đa ngôn ngữ)** | **Whisper (đa ngôn ngữ)** | **Whisper (đa ngôn ngữ)** | — |
| Loại đầu vào | video + audio | video + audio | video + audio | video + audio | video/ảnh + audio |
| VRAM theo tài liệu | — | ~4 GB fp16 (clip nhỏ) | **18 GB** | **8 GB** | — |
| VRAM đo thật | 7.004 MiB | 9.118 / 9.798 MiB | **11.942 MiB** | **7.264 MiB** | — |
| Nền tảng | Docker + GPU | WSL2 venv | WSL2 venv | WSL2 venv | — |
| **Quyết định** | **RUN** (baseline) | **RUN** | **RUN** | **RUN** | **REJECT** |
| Lý do | giữ nguyên làm mốc | giấy phép sạch nhất, VRAM thấp, Whisper | PO chỉ định | phiên bản khả thi hơn về VRAM | hoãn để bảo vệ hạn mức 40 GB và không kéo dài vô hạn (quy tắc 11) |

Wav2Lip **không** được đưa vào: giấy phép hiện tại giới hạn phi thương mại.

## 5. Ứng viên chạy được và không chạy được

**Chạy được: 4/4 ứng viên đã thử.** Không ứng viên nào phải ghi `MODEL_INFEASIBLE_12GB`.

Đáng chú ý: **LatentSync 1.6 chạy được trong 12 GB VRAM** dù README ghi cần 18 GB.
Đo thật: peak **11.942 / 12.282 MiB** — vừa đúng, chỉ dư 340 MiB.
Con số 18 GB trong tài liệu chính thức **bảo thủ hơn thực tế**, nhưng biên an toàn gần bằng không:
bất kỳ ứng dụng nào chiếm thêm VRAM cũng sẽ làm nó OOM. **Không tái lập được một cách ổn định.**

Hạn mức "một tối ưu chính thức khi OOM" **chưa hề được dùng** — không có OOM nào xảy ra.
`--enable_deepcache` được tính là baseline vì nó nằm sẵn trong `inference.sh` mặc định.

## 6. Đầu vào chung

Mọi model dùng cùng nguồn, cùng golden audio, cùng đoạn.

| File | Thông số | Ghi chú |
|---|---|---|
| `inputs/golden_48k.wav` | 48 kHz mono, 7,680 s | bản sao **nguyên vẹn**, hash `311471e7…` khớp golden gốc |
| `inputs/golden_16k.wav` | 16 kHz mono, 7,680 s | working copy, chỉ đổi định dạng |
| `inputs/source_30fps_8s.mp4` | 1080×1920, 30fps, 240 khung, 8,000 s | working copy |
| `inputs/source_25fps_8s.mp4` | 1080×1920, 25fps, 200 khung, 8,000 s | working copy cho fps huấn luyện của MuseTalk |

Lệnh FFmpeg tạo working copy (không sửa tài sản gốc):

```bash
ffmpeg -i "$G" -ac 1 -ar 16000 -c:a pcm_s16le -y golden_16k.wav
ffmpeg -i "$SRC" -t 8.0 -c:v libx264 -crf 14 -preset medium -pix_fmt yuv420p -r 30 -an -y source_30fps_8s.mp4
ffmpeg -i "$SRC" -t 8.0 -c:v libx264 -crf 14 -preset medium -pix_fmt yuv420p -r 25 -an -y source_25fps_8s.mp4
```

### Cảnh báo về tính công bằng của phép so — PO cần biết

**Ba model không cùng fps đầu ra, và đó không phải lựa chọn của tôi:**

- **Duix**: 30 fps, đúng fps gốc của dự án.
- **MuseTalk**: 25 fps là fps huấn luyện chính thức. Chạy thêm bản 30 fps (B2) để đối chứng.
- **LatentSync**: **ép về 25 fps bất kể đầu vào.** Log ghi `video in 25 FPS` dù nguồn là 30 fps.

Hệ quả cho pipeline: **cả MuseTalk lẫn LatentSync đều buộc thêm một bước 25→30 fps**,
hoặc dự án phải chuyển hẳn sang 25 fps. Chỉ Duix chạy 30 fps native.

**LatentSync còn hạ audio đầu ra xuống 16 kHz** (Duix và MuseTalk giữ 48 kHz).
Điều này không ảnh hưởng bản dựng cuối vì composer dùng golden gốc, nhưng ảnh hưởng khi xem file thô.

## 7. Bảng thông số và hiệu năng

| | A — Duix | B — MuseTalk 25fps | B2 — MuseTalk 30fps | C — LatentSync 1.6 | C2 — LatentSync 1.5 |
|---|---|---|---|---|---|
| Độ phân giải | 1080×1920 | 1080×1920 | 1080×1920 | 1080×1920 | 1080×1920 |
| fps đầu ra | 30 | 25 | 30 | 25 (ép) | 25 (ép) |
| Số khung (đếm thật) | 228 | 192 | 230 | 194 | 194 |
| Thời lượng hình | 7,600 s | 7,680 s | 7,667 s | 7,760 s | 7,760 s |
| Thời lượng tiếng | 7,680 s | 7,680 s | 7,680 s | 7,680 s | 7,680 s |
| **Chênh lệch A/V** | 0,080 s | **0,000 s** | 0,013 s | 0,080 s | 0,080 s |
| Codec hình | h264 High | h264 High | h264 High | h264 High | h264 High |
| Codec tiếng | aac 48 kHz mono | aac 48 kHz mono | aac 48 kHz mono | aac **16 kHz** mono | aac **16 kHz** mono |
| Giải mã toàn bộ | **sạch** | **sạch** | **sạch** | **sạch** | **sạch** |
| Kích thước | 11.932.459 B | 3.112.948 B | 3.261.212 B | 6.474.194 B | 6.357.914 B |
| SHA-256 | `5f7ce378e128317b…` | `7c313a100102ebec…` | `146bc075a10c1545…` | `1f0be3dae5bbef43…` | `a25a9975e52a40a9…` |
| **Thời gian render** | 22,3 s | 210,8 s | 184,7 s | **1.239,6 s** | **105,5 s** |
| **Peak VRAM** | 7.004 MiB | 9.118 MiB | 9.798 MiB | **11.942 MiB** | 7.264 MiB |
| RAM | không đo riêng | trong 15 GiB WSL | trong 15 GiB WSL | trong 15 GiB WSL | trong 15 GiB WSL |

Thời gian render của C (1.239,6 s) **không phản ánh tốc độ thật**: `onnxruntime` không nạp được
CUDA provider (thiếu `libnvrtc.so.12`, xuất hiện 5 lần trong log) nên `insightface` chạy trên CPU.

### Tham số inference thật

**B / B2 — MuseTalk v1.5** (mặc định repo, trừ `fps` và `use_float16`):

```
--version v15  --unet_model_path ./models/musetalkV15/unet.pth
--unet_config ./models/musetalkV15/musetalk.json  --whisper_dir ./models/whisper
--fps 25|30  --use_float16  --batch_size 8  --bbox_shift 0  --extra_margin 10
--parsing_mode jaw  --left_cheek_width 90  --right_cheek_width 90
--audio_padding_length_left 2  --audio_padding_length_right 2
```

**C — LatentSync 1.6** (nguyên văn `inference.sh` chính thức):

```
--unet_config_path configs/unet/stage2_512.yaml   (resolution 512)
--inference_ckpt_path checkpoints-1.6/latentsync_unet.pt
--inference_steps 20  --guidance_scale 1.5  --enable_deepcache  --seed 1247
```

**C2 — LatentSync 1.5** (theo `docs/changelog_v1.6.md`: đổi checkpoint + đổi `resolution`):

```
--unet_config_path configs/unet/stage2.yaml       (resolution 256)
--inference_ckpt_path checkpoints-1.5/latentsync_unet.pt
--inference_steps 20  --guidance_scale 1.5  --enable_deepcache  --seed 1247
```

## 8. Metric kỹ thuật

**Metric này KHÔNG phải bằng chứng rằng khẩu hình nhìn bằng mắt đã đạt.**
Nó chỉ đo một chiều: tương quan giữa độ mở miệng và biên độ tiếng. PO phải xem bằng mắt.

| | r tại lag 0 | r tốt nhất | Biên độ mở miệng | Độ nét vùng miệng |
|---|---|---|---|---|
| A — Duix | +0,264 | +0,264 @ 0 ms | 0,179 | 7,26 |
| B — MuseTalk 25fps | +0,282 | **+0,320** @ −40 ms | 0,113 | 4,77 |
| B2 — MuseTalk 30fps | +0,222 | +0,272 @ −33 ms | 0,112 | 4,81 |
| C — LatentSync 1.6 | +0,267 | **+0,349** @ +40 ms | 0,227 | 6,02 |
| C2 — LatentSync 1.5 | +0,208 | +0,283 @ +40 ms | 0,211 | 4,94 |
| *Nguồn gốc (mốc trần)* | *−0,048* | *+0,129* | *0,181* | *8,11* |

Cách đọc: nguồn gốc là **mốc trần độ nét** (8,11) và là **mốc sàn tương quan** — nó không liên
quan gì tới golden audio nên r của nó (+0,129) xấp xỉ mức trùng hợp ngẫu nhiên.
Mọi r trong bảng đều thấp; không model nào đạt mức tương quan cao.

## 9. Đường dẫn kết quả

Tất cả tại `F:\AI-VIDEO-AGENT-RUNTIME\model-bakeoff\outputs\`:

**Video từng model**

| Ứng viên | File |
|---|---|
| A — Duix baseline | `A_duix_baseline.mp4` |
| B — MuseTalk 25fps | `B_musetalk_v15_fps25.mp4` |
| B2 — MuseTalk 30fps | `B2_musetalk_v15_fps30.mp4` |
| C — LatentSync 1.6 | `C_latentsync_1.6_raw.mp4` |
| C2 — LatentSync 1.5 | `C_latentsync_1.5_raw.mp4` |
| *(bằng chứng lỗi)* | `_LOI_C2_latentsync_1.5_config512_lech.mp4` |

**Video so sánh toàn khung**

- `SO-SANH-4-MODEL-TOAN-KHUNG.mp4` — cả 4 ứng viên, 1760×862
- `SO-SANH-TOAN-KHUNG_A-duix_B-musetalk.mp4` — 2 ô, 1240×1178

**Video so sánh vùng miệng phóng lớn**

- `SO-SANH-4-MODEL-VUNG-MIENG.mp4` — cả 4 ứng viên, lưới 2×2, 1440×1288
- `SO-SANH-VUNG-MIENG_A-duix_B-musetalk.mp4` — 2 ô, 1800×780
- `SO-SANH-CUNG-30FPS-VUNG-MIENG_A-duix_B2-musetalk.mp4` — cùng 30fps, **không nhân bản khung**
- `SO-SANH-3-O-VUNG-MIENG.mp4` — Duix 30 · MuseTalk 25 · MuseTalk 30

Nhãn nằm trong dải đen **thêm vào phía trên khung hình**, không che mặt hay miệng.
Âm thanh giống nhau giữa mọi bản (golden gốc).
Khi ghép các bản 25fps vào khung 30fps, dùng bộ lọc `fps` của FFmpeg = **nhân bản/bỏ khung**,
**không nội suy chuyển động** (không dùng `minterpolate`/`tblend`).

Manifest weights kèm SHA-256 từng file tại `model-bakeoff\weights\`:
`musetalk-weights-manifest.json`, `latentsync-1.6-weights-manifest.json`,
`latentsync-1.5-weights-manifest.json`.

## 10. Lỗi gặp phải

| # | Lỗi | Nguyên nhân | Xử lý |
|---|---|---|---|
| 1 | `mkdir: Permission denied` trên `/mnt/f` | Git Bash dịch đường dẫn khi truyền tham số sang `wsl`, làm biến shell rỗng | Ghi script ra file, gọi qua PowerShell |
| 2 | `ModuleNotFoundError: pkg_resources` khi `mim install` | venv của `uv` không kèm `setuptools` | Cài `setuptools<70` |
| 3 | `mmcv`/`cv2` gãy: `numpy.core.multiarray failed to import` | `xtcocotools`/`chumpy` kéo numpy lên 2.2.6 | Ghim lại `numpy==1.23.5` theo `requirements.txt`, build lại gói native |
| 4 | `mmpose` không cài được vì `chumpy` | `chumpy` (SMPL 3D) không build được trên setuptools mới | `--no-build-isolation`; MuseTalk chỉ dùng DWPose 2D nên không cần SMPL |
| 5 | `pkg_resources` mất lần hai, gãy `mmengine.get_installed_path()` | `--force-reinstall` gỡ mất `setuptools` | Cài lại, và **bổ sung kiểm chứng đúng chuỗi import sâu** `from mmpose.apis import …` thay vì chỉ `import mmpose` |
| 6 | `drawtext` không tồn tại trong ffmpeg của WSL | bản static của `imageio-ffmpeg` thiếu libfreetype | Dựng video đối chiếu bằng ffmpeg 9.0 trên Windows |
| 7 | LatentSync: `error: command 'c++' failed` | WSL không có trình biên dịch; `insightface==0.7.3` trên PyPI **chỉ có bản mã nguồn** | **Dừng xin PO** — cài compiler là thay đổi hệ thống. PO tự cài `build-essential`. Không dùng wheel bên thứ ba. |
| 8 | LatentSync 1.6: `OSError [Errno 12] Cannot allocate memory` tại `torch.load()` | `.wslconfig` giới hạn `memory=6GB`; checkpoint 4,8 GB không nạp nổi | **Dừng xin PO.** PO nâng lên 16 GB. **Không ghi `MODEL_INFEASIBLE_12GB`** vì peak VRAM khi đó mới 3.007 MiB — GPU chưa hề bị chạm tới, giả thuyết 18 GB chưa kiểm chứng được |
| 9 | `onnxruntime` không nạp được CUDA provider | thiếu `libnvrtc.so.12` | Không chặn; `insightface` chạy CPU. **Làm thời gian render của C không phản ánh tốc độ thật** |
| 10 | **C2 lần đầu cho đầu ra vỡ nát** | **Lỗi của tôi**: chạy checkpoint 1.5 bằng `stage2_512.yaml` (res 512). `inference.sh` ở commit này là của 1.6 | Chạy lại với `stage2.yaml` (res 256) đúng `docs/changelog_v1.6.md`. Xác nhận: 105,5 s thay vì 1.289 s, VRAM 7.264 thay vì 11.886 MiB. Giữ bản hỏng làm bằng chứng |

Lỗi #10 đáng lưu ý: số liệu C2 tôi báo trước khi sửa (biên độ mở miệng 0,403 · độ nét 7,79)
là **nhiễu hình chứ không phải khẩu hình**, và đã bị thay bằng số đo đúng trong mục 8.

## 11. Ngân sách và kiểm soát

| Mục | Giá trị |
|---|---|
| Dung lượng trên ổ F | **28,98 GB / 40 GB** |
| Tải thêm từ nguồn chính thức | MuseTalk 4.190 MB · LatentSync 1.6 4.909 MB · LatentSync 1.5 4.909 MB · `buffalo_l` (insightface GitHub releases) |
| Nằm ngoài ngân sách F | venv WSL (~7,5 GB + ~7,1 GB) và cache `uv` (~7,4 GB) trên đĩa WSL native — **khai báo riêng, không tính là ngân sách bake-off** |
| Model/checkpoint/cache/output | **toàn bộ trên ổ F**, `HF_HOME` trỏ `model-bakeoff\weights\hf-cache` |
| Nguồn tải | **chỉ `huggingface.co` và `github.com` chính thức**. Đã **từ chối** `HF_ENDPOINT=hf-mirror.com` mà `download_weights.bat` của MuseTalk đặt sẵn |
| Wheel bên thứ ba | **không dùng** |
| Chạy đồng thời | không — một model tại một thời điểm |
| Tiến trình GPU ngoài dự án | **không dừng cái nào**, chỉ ghi nhận |

**Giải phóng sau khi xong**: VRAM về **568 / 12.282 MiB**; RAM host trống tăng từ 11,5 GB lên
**20,7 GB** sau khi tắt WSL. Không container nào của dự án còn chạy.
Không dừng container ngoài dự án.

## 12. Kiểm tra repo cuối

```
uv run pytest        -> 258 passed
uv run ruff check .  -> All checks passed!
uv run mypy          -> Success: no issues found in 44 source files
git diff --check     -> exit 0
git status           -> sạch (trước khi ghi file báo cáo này)
```

Quét Git: **không có media, checkpoint, model hay secret nào trong index**
(chỉ `.py .md .json .toml .yml .lock` và dotfile). `model-bakeoff\` nằm **ngoài** repo Git.

## 13. Xác nhận ranh giới

- **Chưa commit.** HEAD vẫn `5ec4881`, đúng root commit ban đầu.
- **Chưa push.** Repo không có remote.
- **Chưa deploy.**
- **Chưa mở D05.** `CURRENT_GATE` vẫn `"D04"`.
- **Không sửa adapter Duix, không sửa `registry.py`, không sửa pipeline production.**
  `KNOWN_AVATAR` vẫn là `frozenset({"duix"})`.
- **Không gọi API trả phí.**
- **Không tuyên bố `PROJECT_COMPLETE=true`.**
- **Winner do PO chọn**, không phải do tôi tự quyết (mục 0).
- **Không tuyên bố khẩu hình của bản nào đạt** — đánh giá thẩm mỹ là của PO.

## 14. Trạng thái gate

**D04 = APPROVED, HOÀN TẤT.** Quyết định của PO ghi ở mục 0.

Toàn bộ evidence được giữ nguyên, không sửa, không xoá:

- 5 đầu ra thử nghiệm + 1 file bằng chứng lỗi — mục 9
- Bảng thông số và hiệu năng đầy đủ — mục 7
- Metric kỹ thuật — mục 8
- 6 video so sánh (toàn khung và vùng miệng) — mục 9
- Hash nguồn, golden, mọi checkpoint và mọi đầu ra — mục 2, 4, 7
- 10 lỗi gặp phải, kể cả hai lỗi của tôi — mục 10

### Không làm gì với production trong batch này

- `CURRENT_GATE` vẫn `"D04"` — **không tự nâng lên D05**.
- `KNOWN_AVATAR` vẫn `frozenset({"duix"})` — không đụng.
- Adapter Duix, `registry.py`, pipeline production: **không sửa một dòng nào**.
- Không commit, không push, không deploy.

Duix đã là provider production sẵn có, nên quyết định chọn A **không đòi hỏi thay đổi
code nào**. Đây là lý do D04 khép lại được mà production vẫn nguyên trạng.

### Việc tiếp theo cần PO duyệt

Phạm vi và preflight của gate kế tiếp nằm ở tài liệu riêng:
**[D05_PREFLIGHT.md](D05_PREFLIGHT.md)**.

**Cập nhật 2026-08-06 — D05-A đã chạy xong** (PO duyệt mở từng bước, chỉ discovery):
đã kiểm chứng giá 4 nhà cung cấp B-roll từ trang chính thức và chạy estimate cho các cấu
hình đại diện. **Không gọi API, không đặt key, không sinh B-roll, không tiêu đồng nào.**
`CURRENT_GATE` vẫn `"D04"`, bốn lớp chặn chi tiêu còn nguyên.
Kết quả ở `D05_PREFLIGHT.md` mục 6 và 7. **D05-B chưa mở, chờ PO duyệt.**

Backlog còn treo: **BL-001 "Tủ đồ AI"** (`docs/BACKLOG.md`) vẫn cần gate riêng,
độc lập với D05.

---

D04_LIPSYNC_MODEL_BAKEOFF = APPROVED
BAKEOFF_READY_FOR_PO=true
