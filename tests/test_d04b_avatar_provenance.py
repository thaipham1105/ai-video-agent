"""D04-B — provenance, hàng rào tài nguyên, và hồi quy hành vi Duix.

Ba câu hỏi nhóm test này trả lời:

1. Nhìn một `avatar.mp4` bất kỳ, có truy ngược được model/checkpoint/đầu vào không?
2. Cấu hình sai có chết **trước** khi chạm GPU không?
3. Việc mở rộng hợp đồng có làm đổi hành vi Duix đang chạy không?
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from ai_video_agent.clock import now_utc
from ai_video_agent.domain.assets import AssetManifest, sha256_file
from ai_video_agent.domain.enums import ProjectState, RenderStage, StageStatus
from ai_video_agent.domain.project import Approval, Project
from ai_video_agent.domain.storyboard import Storyboard
from ai_video_agent.errors import CapabilityError, ConsentMissingError
from ai_video_agent.orchestrator.pipeline import Pipeline, RenderOptions
from ai_video_agent.orchestrator.repository import ProjectRepository
from ai_video_agent.providers.avatar_capability import (
    check_avatar_request,
    describe_language_fit,
)
from ai_video_agent.providers.base import (
    AvatarCapability,
    AvatarProvenance,
    AvatarRequest,
    AvatarResult,
    ResourceEstimate,
)
from ai_video_agent.providers.duix import DuixAvatarProvider, MockDuixAvatarProvider
from ai_video_agent.providers.duix.capability import DUIX_CAPABILITY, DUIX_RESOURCES


def _wav(path: Path, seconds: float = 1.0, rate: int = 48_000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return path


def _request(tmp_path: Path, **kw: object) -> AvatarRequest:
    audio = _wav(tmp_path / "audio.wav")
    source = tmp_path / "avatar.mp4"
    source.write_bytes(b"nguon avatar")
    base: dict[str, object] = {
        "shot_id": "shot-01", "audio_path": audio, "avatar_source": source,
        "width": 1080, "height": 1920, "fps": 30, "duration_sec": 1.0,
    }
    base.update(kw)
    return AvatarRequest(**base)  # type: ignore[arg-type]


# --- ResourceEstimate: mặc định 0 không được che lỗi ----------------------


def test_ram_bang_0_bi_tu_choi() -> None:
    with pytest.raises(ValueError, match="quên khai"):
        ResourceEstimate(
            vram_mib=1000, ram_mib=0, storage_mib=10,
            deterministic_local=True, measured=True, measured_on="2026-08-07",
        )


def test_tai_nguyen_am_bi_tu_choi() -> None:
    with pytest.raises(ValueError, match="không được âm"):
        ResourceEstimate(
            vram_mib=-1, ram_mib=100, storage_mib=10,
            deterministic_local=True, measured=False,
        )


def test_da_do_ma_thieu_ngay_bi_tu_choi() -> None:
    """Số đo không có ngày thì không biết còn tươi hay đã lỗi thời."""
    with pytest.raises(ValueError, match="measured_on"):
        ResourceEstimate(
            vram_mib=1000, ram_mib=100, storage_mib=10,
            deterministic_local=True, measured=True,
        )


def test_uoc_tinh_khong_do_thi_khong_can_ngay() -> None:
    est = ResourceEstimate(
        vram_mib=1000, ram_mib=100, storage_mib=10,
        deterministic_local=False, measured=False,
    )
    assert est.measured is False


# --- AvatarCapability: không cho khai thiếu -------------------------------


def _cap(**kw: object) -> AvatarCapability:
    base: dict[str, object] = {
        "backend_id": "x", "backend_version": "1", "native_fps": 30,
        "supported_fps": frozenset({30}), "max_width": 1080, "max_height": 1920,
        "audio_sample_rate_hz": 48_000, "audio_channels": 1,
        "audio_encoder": "whisper", "languages_verified": frozenset({"multi"}),
        "accepts_image_source": False, "accepts_video_source": True,
        "requires_gate": "D03", "resources": DUIX_RESOURCES,
    }
    base.update(kw)
    return AvatarCapability(**base)  # type: ignore[arg-type]


def test_capability_thieu_backend_id_bi_tu_choi() -> None:
    with pytest.raises(ValueError, match="backend_id"):
        _cap(backend_id="")


def test_native_fps_ngoai_supported_fps_bi_tu_choi() -> None:
    with pytest.raises(ValueError, match="native_fps"):
        _cap(native_fps=25, supported_fps=frozenset({30}))


def test_thieu_audio_encoder_bi_tu_choi() -> None:
    """Bộ mã hoá tiếng quyết định chất lượng theo ngôn ngữ — không được để trống."""
    with pytest.raises(ValueError, match="audio_encoder"):
        _cap(audio_encoder="")


def test_thieu_ngon_ngu_kiem_chung_bi_tu_choi() -> None:
    with pytest.raises(ValueError, match="languages_verified"):
        _cap(languages_verified=frozenset())


def test_khong_nhan_nguon_nao_bi_tu_choi() -> None:
    with pytest.raises(ValueError, match="ít nhất một loại nguồn"):
        _cap(accepts_image_source=False, accepts_video_source=False)


# --- Hàng rào tương thích: chết TRƯỚC khi chạm GPU -------------------------


def test_fps_khong_ho_tro_bi_chan(tmp_path: Path) -> None:
    with pytest.raises(CapabilityError, match="không xuất được"):
        check_avatar_request(DUIX_CAPABILITY, _request(tmp_path, fps=60))


def test_kich_thuoc_vuot_tran_bi_chan(tmp_path: Path) -> None:
    with pytest.raises(CapabilityError, match="tối đa"):
        check_avatar_request(DUIX_CAPABILITY, _request(tmp_path, width=4096, height=4096))


def test_nguon_anh_bi_chan_voi_duix(tmp_path: Path) -> None:
    """Duix chỉ nhận video làm nguồn."""
    with pytest.raises(CapabilityError, match="không nhận ảnh tĩnh"):
        check_avatar_request(DUIX_CAPABILITY, _request(tmp_path), source_is_image=True)


def test_thieu_vram_bi_chan_truoc_khi_nap_model(tmp_path: Path) -> None:
    with pytest.raises(CapabilityError, match="Không nạp model"):
        check_avatar_request(DUIX_CAPABILITY, _request(tmp_path), available_vram_mib=2_000)


def test_du_vram_thi_qua(tmp_path: Path) -> None:
    check_avatar_request(DUIX_CAPABILITY, _request(tmp_path), available_vram_mib=12_282)


def test_khong_biet_vram_thi_khong_doan(tmp_path: Path) -> None:
    """``None`` = bỏ qua kiểm. Đoán một mặc định sẽ chặn nhầm hoặc để lọt."""
    check_avatar_request(DUIX_CAPABILITY, _request(tmp_path), available_vram_mib=None)


# --- Adapter thật: chết trước khi gửi job, không phải giữa chừng ----------


def _armed_provider(tmp_path: Path) -> DuixAvatarProvider:
    """Adapter thật với volume trỏ vào ``tmp_path`` và bom gài ở lớp HTTP.

    Ánh xạ volume phải hợp lệ, nếu không adapter sẽ chết vì đường dẫn trước khi
    tới được lớp HTTP — và test sẽ xanh/đỏ vì lý do khác với điều nó khẳng định.
    """
    provider = DuixAvatarProvider(path_map=((str(tmp_path), "/inputs"),))

    def bom(*_a: object, **_k: object) -> dict[str, object]:
        raise AssertionError("Đã gửi job đi rồi mới kiểm năng lực — sai thứ tự.")

    provider._post_json = bom  # type: ignore[method-assign]
    return provider


def test_adapter_that_bao_loi_truoc_khi_goi_http(tmp_path: Path) -> None:
    """Cấu hình sai phải chết ở hàng rào, không phải sau 22 s GPU.

    Chứng minh bằng cách gài bom vào lớp HTTP: nếu hàng rào bị bỏ thì adapter
    chạm tới bom và test hỏng với thông điệp khác hẳn ``CapabilityError``.
    """
    with pytest.raises(CapabilityError, match="không xuất được"):
        _armed_provider(tmp_path).generate(_request(tmp_path, fps=60), tmp_path / "out.mp4")


def test_adapter_that_chan_kich_thuoc_vuot_tran_truoc_khi_goi_http(tmp_path: Path) -> None:
    with pytest.raises(CapabilityError, match="tối đa"):
        _armed_provider(tmp_path).generate(
            _request(tmp_path, width=3840, height=2160), tmp_path / "out.mp4"
        )


def test_bom_that_su_no_khi_khong_con_hang_rao(tmp_path: Path) -> None:
    """Kiểm tra chính cái bẫy: yêu cầu HỢP LỆ phải đi tới lớp HTTP.

    Không có test này thì hai test trên có thể xanh vì adapter chết sớm ở một
    hàng rào khác, và ta sẽ tưởng đã chứng minh được thứ tự.
    """
    with pytest.raises(AssertionError, match="sai thứ tự"):
        _armed_provider(tmp_path).generate(_request(tmp_path), tmp_path / "out.mp4")


def test_thieu_tai_san_avatar_chan_som_hon_ca_kiem_nang_luc(tmp_path: Path) -> None:
    """Đồng ý sử dụng hình ảnh là hàng rào đạo đức — phải đứng trước hàng rào kỹ thuật."""
    provider = DuixAvatarProvider()
    request = _request(tmp_path, fps=60)  # sai cả fps lẫn thiếu nguồn
    request.avatar_source.unlink()  # type: ignore[union-attr]

    with pytest.raises(ConsentMissingError):
        provider.generate(request, tmp_path / "out.mp4")


# --- Cảnh báo ngôn ngữ: nói ra, không chặn --------------------------------


def test_duix_bi_canh_bao_khi_dung_cho_tieng_viet() -> None:
    note = describe_language_fit(DUIX_CAPABILITY, "vi")
    assert "KHÔNG gồm" in note
    assert "wenet-aishell" in note
    assert "sai hình âm" in note


def test_backend_da_ngon_ngu_khong_bi_canh_bao() -> None:
    cap = _cap(audio_encoder="whisper", languages_verified=frozenset({"multi"}))
    assert "có phủ" in describe_language_fit(cap, "vi")


# --- Provenance của mock ---------------------------------------------------


def test_mock_tra_ve_provenance_day_du(tmp_path: Path) -> None:
    result = MockDuixAvatarProvider().generate(_request(tmp_path), tmp_path / "out.mp4")
    prov = result.provenance
    assert prov is not None, "mock cũng phải khai provenance để hợp đồng đồng nhất"
    assert prov.backend_id == "duix"
    assert prov.model and prov.backend_version
    assert prov.audio_encoder == DUIX_CAPABILITY.audio_encoder
    assert prov.source_fps == 30


def test_provenance_mang_van_tay_dau_vao(tmp_path: Path) -> None:
    """Băm đầu vào là thứ cho biết video này sinh từ audio/nguồn nào."""
    request = _request(tmp_path)
    result = MockDuixAvatarProvider().generate(request, tmp_path / "out.mp4")
    prov = result.provenance
    assert prov is not None
    assert prov.audio_sha256 == sha256_file(request.audio_path)
    assert request.avatar_source is not None
    assert prov.source_asset_sha256 == sha256_file(request.avatar_source)


def test_van_tay_doi_khi_dau_vao_doi(tmp_path: Path) -> None:
    request = _request(tmp_path)
    first = MockDuixAvatarProvider().generate(request, tmp_path / "a.mp4")
    _wav(request.audio_path, seconds=2.0)  # đổi audio
    second = MockDuixAvatarProvider().generate(request, tmp_path / "b.mp4")
    assert first.provenance is not None and second.provenance is not None
    assert first.provenance.audio_sha256 != second.provenance.audio_sha256


def test_thieu_file_thi_van_tay_de_rong_khong_doan(tmp_path: Path) -> None:
    request = _request(tmp_path)
    request.audio_path.unlink()
    result = MockDuixAvatarProvider().generate(request, tmp_path / "out.mp4")
    assert result.provenance is not None
    assert result.provenance.audio_sha256 == "", "không có file thì để rỗng, không bịa băm"


# --- Mock không được khai rộng hơn bản thật -------------------------------


def test_mock_khong_khai_nang_luc_rong_hon_ban_that() -> None:
    """Mock rộng hơn thật ⇒ test xanh rồi vỡ khi chạy thật."""
    mock = MockDuixAvatarProvider().capability()
    real = DUIX_CAPABILITY
    assert mock.supported_fps <= real.supported_fps
    assert mock.max_width <= real.max_width
    assert mock.max_height <= real.max_height
    assert mock.audio_encoder == real.audio_encoder
    assert mock.languages_verified == real.languages_verified
    assert mock.accepts_image_source == real.accepts_image_source
    assert mock.accepts_video_source == real.accepts_video_source


def test_mock_khai_gate_thap_hon_ban_that() -> None:
    """Mock chạy được từ D01; bản thật cần D03."""
    assert MockDuixAvatarProvider().capability().requires_gate == "D01"
    assert DuixAvatarProvider().capability().requires_gate == "D03"


# --- Hồi quy hành vi Duix hiện hữu ----------------------------------------


def test_duix_giu_nguyen_danh_tinh_va_gia() -> None:
    info = DuixAvatarProvider().info()
    assert info.name == "duix"
    assert info.gate == "D03"
    assert info.billable is False


def test_capability_duix_khop_so_da_do_o_bakeoff() -> None:
    """7.004 MiB là số đo thật ở bake-off D04, không phải chép tài liệu."""
    assert DUIX_RESOURCES.vram_mib == 7_004
    assert DUIX_RESOURCES.measured is True
    assert DUIX_RESOURCES.measured_on == "2026-08-05"
    assert DUIX_CAPABILITY.audio_encoder == "wenet-aishell"
    assert DUIX_CAPABILITY.languages_verified == frozenset({"zh"})
    assert DUIX_CAPABILITY.native_fps == 30


def test_capability_that_mang_digest_image_da_ghim() -> None:
    provider = DuixAvatarProvider(image_digest="sha256:deadbeef")
    assert "sha256:deadbeef" in provider.capability().backend_version


def test_khong_co_digest_thi_dung_ban_goc() -> None:
    assert DuixAvatarProvider().capability().backend_version == DUIX_CAPABILITY.backend_version


# --- Pipeline vẫn nhận AvatarResult mới -----------------------------------


def test_avatar_result_khong_co_provenance_van_hop_le(tmp_path: Path) -> None:
    """Trường mới là tuỳ chọn — code cũ dựng AvatarResult không phải sửa."""
    result = AvatarResult(
        path=tmp_path / "x.mp4", duration_sec=1.0, width=1080, height=1920, fps=30
    )
    assert result.provenance is None


def test_pipeline_chay_tron_voi_avatar_result_moi(
    pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
) -> None:
    """Đường ống hiện có phải đi hết đường với ``AvatarResult`` đã mở rộng.

    Đây là câu hỏi tương thích ngược: thêm ``provenance`` vào kết quả có làm vỡ
    bước nào ở hạ nguồn không.
    """
    project.transition_to(ProjectState.PLANNED)
    project.approval = Approval(
        approved_by="Chủ máy", approved_at=now_utc(), storyboard_sha256=storyboard.sha256()
    )
    project.transition_to(ProjectState.APPROVED)
    repo.save_project(project)

    manifest = pipeline.render(project, storyboard, granted_assets, RenderOptions(dry_run=False))

    assert manifest.status == "succeeded"
    avatar_records = [r for r in manifest.records if r.stage is RenderStage.AVATAR]
    assert avatar_records, "phải có bước avatar trong manifest"
    assert all(r.status is StageStatus.SUCCEEDED for r in avatar_records)


def test_provider_trong_pipeline_thuc_su_tra_provenance(
    pipeline: Pipeline,
    repo: ProjectRepository,
    project: Project,
    storyboard: Storyboard,
    granted_assets: AssetManifest,
) -> None:
    """Chốt bằng gián điệp: kết quả đi vào pipeline có mang provenance thật.

    Test trên chỉ chứng minh pipeline *không vỡ*; test này chứng minh nó đang
    nhận đúng dữ liệu, không phải một ``AvatarResult`` rỗng.
    """
    seen: list[AvatarResult] = []
    inner = pipeline._provider_set.avatar

    class Spy:
        def info(self) -> object:
            return inner.info()

        def capability(self) -> AvatarCapability:
            return inner.capability()

        def quote(self, request: AvatarRequest) -> object:
            return inner.quote(request)

        def estimate_resources(self, request: AvatarRequest) -> ResourceEstimate:
            return inner.estimate_resources(request)

        def generate(self, request: AvatarRequest, out_path: Path) -> AvatarResult:
            result = inner.generate(request, out_path)
            seen.append(result)
            return result

    pipeline._provider_set.avatar = Spy()  # type: ignore[assignment]

    project.transition_to(ProjectState.PLANNED)
    project.approval = Approval(
        approved_by="Chủ máy", approved_at=now_utc(), storyboard_sha256=storyboard.sha256()
    )
    project.transition_to(ProjectState.APPROVED)
    repo.save_project(project)

    pipeline.render(project, storyboard, granted_assets, RenderOptions(dry_run=False))

    assert seen, "pipeline phải gọi avatar provider ít nhất một lần"
    for result in seen:
        assert result.provenance is not None
        assert result.provenance.backend_id == "duix"
        assert result.provenance.audio_sha256, "audio đã sinh xong thì phải có vân tay"


def test_provenance_serialize_duoc_ra_json() -> None:
    """Provenance phải ghi được vào render-manifest."""
    import json
    from dataclasses import asdict

    prov = AvatarProvenance(
        backend_id="duix", backend_version="v1", model="m", model_version="1",
        audio_encoder="wenet-aishell", source_fps=30, params={"chaofen": "0"},
    )
    text = json.dumps(asdict(prov), ensure_ascii=False)
    assert "wenet-aishell" in text
    assert json.loads(text)["params"]["chaofen"] == "0"
