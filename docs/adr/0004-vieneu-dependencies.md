# ADR-0004 — Cách cài VieNeu-TTS: extra riêng, ghim numpy, loại perth

- Trạng thái: **Chấp nhận** (Gate D02)
- Ngày: 2026-08-04
- Bối cảnh: brief §D02.1 — "Cài VieNeu theo hướng ít rủi ro nhất đã được duyệt;
  ưu tiên thử CPU/ONNX trước để tránh xung đột GPU với Duix."

## Ba quyết định

### 1. `vieneu` là **optional extra**, không phải phụ thuộc chính

```toml
[project.optional-dependencies]
tts = ["vieneu>=3.2.4", "numpy<2.3"]
```

Cài bằng `uv sync --extra tts`.

`vieneu` kéo theo **63 gói** (`gradio`, `fastapi`, `uvicorn`, `scipy`,
`scikit-learn`, `pandas`, `librosa`, `numba`…). Nó làm `.venv` phình từ
**89,5 MB lên 640,9 MB**. Đường đi mock của D01 không cần một gói nào trong số
đó, và mọi test đều chạy bằng mock.

Để nó ngoài phụ thuộc chính giữ cho ai chỉ muốn đọc/lập kế hoạch vẫn cài được
repo trong vài giây. Đây cũng là lý do `AGENTS.md` cấm import SDK nặng ở cấp
module — adapter thật chỉ `import vieneu` **bên trong hàm**, và có test canh
điều đó (`test_import_vieneu_khong_xay_ra_o_cap_module`).

### 2. Ghim `numpy<2.3` — không phải sở thích, mà là bắt buộc

Để resolver tự do, nó chọn `numpy==2.5.1`, rồi vì không có `numba` nào tương
thích với numpy mới đến vậy, nó lùi về **`numba==0.53.1` + `llvmlite==0.36.0`**
— bản phát hành năm 2021, **không có wheel cho Python 3.12** và phải build từ
nguồn (llvmlite 0.36 cần LLVM 11).

Kiểm chứng bằng `uv pip install --dry-run --no-build vieneu`: thất bại.

Với `numpy<2.3`, resolver chọn `numpy 2.2.6` → `numba 0.66.0` + `llvmlite 0.48.0`,
**đều có wheel sẵn**. Lệnh `--no-build` khi đó chạy sạch (exit 0), nghĩa là toàn
bộ 63 gói cài được mà máy không cần trình biên dịch nào.

`numba` bị kéo vào là do `librosa>=0.11.0`, mà `librosa` là phụ thuộc chính của
`vieneu`; không né được.

### 3. Loại bỏ `perth`

```toml
[tool.uv]
override-dependencies = ["perth ; python_version < '3.0'"]
```

VieNeu khai báo `perth>=0.2.0` với ý nhắm tới trình đóng dấu âm thanh của
Resemble AI. **Nhưng gói đó trên PyPI tên là `resemble-perth`.** Cái tên trần
`perth` thuộc về một dự án hoàn toàn khác:

| | `perth` (PyPI) | `resemble-perth` (PyPI) |
|---|---|---|
| Mô tả | "Wrapper for `threading.local`" | Thư viện đóng dấu âm thanh |
| Kích thước | sdist **1,7 KB**, không có wheel | wheel 34,4 MB |
| Tác giả | `tomokinakamaru` | Resemble AI |
| Module xuất ra | `perth` | `perth` |

Nghĩa là `uv add vieneu` sẽ kéo về một gói **không liên quan gì**, và vì nó chỉ
có sdist nên `setup.py` của nó còn được **chạy lúc cài**.

Upstream đã phòng sẵn cho tình huống này:

```python
def _init_watermarker(self) -> None:
    try:
        import perth

        self.watermarker = perth.PerthImplicitWatermarker()
    except (ImportError, AttributeError):
        self.watermarker = None
```

`AttributeError` được bắt, nên cài nhầm gói kia **không làm sập** — nó chỉ âm
thầm tắt watermark. Vậy nên bỏ hẳn `perth` cho ra **hành vi y hệt**, chỉ khác là
không rước thêm một sdist lạ vào chuỗi cung ứng.

**Đánh đổi:** không có đóng dấu ẩn trong audio. Chấp nhận được, vì nhãn AI của
dự án là nhãn **nhìn thấy được** do FFmpeg khắc lên khung hình
(`project.ai_disclosure`, brief §4). Nếu sau này muốn đóng dấu ẩn, cách đúng là
thêm `resemble-perth` một cách tường minh — lưu ý gói đó mới hỗ trợ tới
Python 3.11, chưa có 3.12.

### 4. Nhân bản giọng cần torch — extra `clone` riêng

**Đính chính so với D00.** Kết luận "VieNeu chạy torch-free trên CPU/ONNX" chỉ
đúng với **giọng dựng sẵn**. Nhân bản giọng thì không.

Đường nhân bản đi qua `_v3_turbo_engine/speaker/`, và ở đó:

- `onnx_extractor.py` có `import torch` ở **cấp module** (dòng 18),
- `fbank.py` → `audio_utils.py` dùng `torchaudio.compliance.kaldi` và
  `torchaudio.functional`.

Trớ trêu là suy luận thật vẫn do onnxruntime chạy trên `speaker_encoder.onnx`;
torch chỉ đóng vai thư viện tensor (`torch.as_tensor`, `.mean(0)`,
`.unsqueeze(0).numpy()`) và torchaudio lo phần trích fbank kiểu Kaldi. Nhưng vì
là import cấp module nên không có cách nào né.

Triệu chứng nếu thiếu: `ModuleNotFoundError: No module named 'torch'` ném ra từ
`prepare_reference()` — **chỉ khi** truyền `ref_audio`, còn giọng dựng sẵn vẫn
chạy bình thường.

```toml
clone = ["torch>=2.6", "torchaudio>=2.6"]
```

Cài bằng `uv sync --extra tts --extra clone`.

**Vẫn giữ được nguyên tắc không tranh GPU với Duix.** Trên Windows/cp312, wheel
`torch` của PyPI là **116,4 MB** và dry-run không kéo theo gói `nvidia-*` hay
`cuda-toolkit` nào. Xác nhận sau khi cài:

```text
torch 2.13.0+cpu   CUDA build: None   torch.cuda.is_available(): False
```

Bản này **về mặt vật lý không chạm được GPU**, nên còn an toàn hơn bản CUDA.
Tổng tải thêm ~150 MB (nén), 483,6 MB trên đĩa.

Tách thành extra riêng để ai chỉ dùng 14 giọng dựng sẵn không phải gánh gần
nửa GB.

## Cấu hình engine bị ghim cứng

`VieNeuTtsProvider` truyền cả ba tham số một cách tường minh thay vì để mặc định:

```python
Vieneu(mode="v3turbo", backend="onnx", device="cpu", precision="int8")
```

- `backend="onnx"` — mặc định là `"auto"`, sẽ rơi sang PyTorch nếu phát hiện GPU.
  Ghim cứng để **không bao giờ** tranh GPU với Duix (brief §D02.1).
- `device="cpu"` — cùng lý do.
- `precision="int8"` — chọn thư mục `onnx_int8/` (~158 MB) thay vì `onnx_update/`
  fp32 (~490 MB). Đủ chất lượng cho lời thoại marketing.

## Dung lượng thật sự tải về

Đo trên máy sau khi chạy health check: **284,9 MB** trong cache Hugging Face.

| Nguồn | Nội dung | Dung lượng |
|---|---|---|
| `pnnbao-ump/VieNeu-TTS-v3-Turbo`, thư mục `onnx_int8/` | 7 file: prefill, decode_step, acoustic_cached, backbone_shared.data, heads.npz, config, tokenizer | 157,8 MB |
| `OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX` | 6 file codec | 86,4 MB |
| còn lại | metadata, blob phụ | ~40 MB |

D00 ước tính "1–2 GB" là **cao hơn thực tế**. Lý do: repo model trên HF tổng
cộng **7,6 GB** (chứa cả safetensors, fp32, các bản update), nhưng thư viện dùng
`hf_hub_download` **theo từng file** trong danh sách cố định, không bao giờ gọi
`snapshot_download`. Đọc được ở `vieneu/_v3_turbo_engine/onnx_runtime_lite.py`.

Nhân bản giọng sẽ tải thêm `speaker_encoder.onnx` (27 MB) và `denoiser.onnx`
(40,7 MB) ở lần dùng đầu tiên.

**14 giọng dựng sẵn nằm ngay trong wheel** (`assets/voices_v3_turbo.json`,
230 KB) — không phải tải gì thêm.

## Chốt chặn để test không chạm mạng

Trong lúc làm D02, việc mở gate đã khiến một test cũ chạm vào adapter thật và
**tải model thật** giữa lúc chạy test. Đã bịt bằng cách đặt `HF_HUB_OFFLINE=1`
và `TRANSFORMERS_OFFLINE=1` trong fixture autouse của `tests/conftest.py`: từ
nay bất kỳ test nào lỡ chạm adapter thật sẽ **báo lỗi ngay** thay vì âm thầm tải
312 MB. Đây là brief §4 ("test tự động không được gọi API") được biến thành thứ
máy tự thực thi.
