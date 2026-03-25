"""Tests for image provider abstraction layer."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aiwebnovel.config import Settings
from aiwebnovel.images.provider import (
    ComfyUIProvider,
    GeneratedImage,
    HuggingFaceSpaceProvider,
    ImageProvider,
    ImageRequest,
    Img2ImgRequest,
    OpenAIImageProvider,
    ReplicateProvider,
    get_image_provider,
)


@pytest.fixture()
def test_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379",
        jwt_secret_key="test-secret-key-for-testing-only",
        debug=True,
    )


class TestImageRequestDataclasses:
    """Tests for ImageRequest/GeneratedImage dataclasses."""

    def test_image_request_defaults(self) -> None:
        req = ImageRequest(prompt="a mountain landscape")
        assert req.prompt == "a mountain landscape"
        assert req.negative_prompt == ""
        assert req.width == 1024
        assert req.height == 1024
        assert req.style_tags is None
        assert req.seed is None

    def test_image_request_custom(self) -> None:
        req = ImageRequest(
            prompt="a dragon",
            negative_prompt="blurry",
            width=512,
            height=512,
            style_tags=["fantasy", "dark"],
            seed=42,
        )
        assert req.width == 512
        assert req.style_tags == ["fantasy", "dark"]
        assert req.seed == 42

    def test_img2img_request(self) -> None:
        req = Img2ImgRequest(
            prompt="evolved portrait",
            source_image_path="/tmp/old.png",
            strength=0.6,
        )
        assert req.source_image_path == "/tmp/old.png"
        assert req.strength == 0.6

    def test_generated_image(self) -> None:
        img = GeneratedImage(
            image_data=b"fake_png_bytes",
            width=1024,
            height=1024,
            provider="comfyui",
            model="sdxl",
            seed=42,
            metadata={"steps": 30},
        )
        assert len(img.image_data) > 0
        assert img.provider == "comfyui"
        assert img.seed == 42


class TestComfyUIProvider:
    """Tests for ComfyUI stub provider."""

    def test_supports_img2img(self) -> None:
        provider = ComfyUIProvider(settings=None)
        assert provider.supports_img2img is True

    @pytest.mark.asyncio
    async def test_generate_raises_not_implemented(self) -> None:
        provider = ComfyUIProvider(settings=None)
        with pytest.raises(NotImplementedError):
            await provider.generate(ImageRequest(prompt="test"))

    @pytest.mark.asyncio
    async def test_img2img_raises_not_implemented(self) -> None:
        provider = ComfyUIProvider(settings=None)
        with pytest.raises(NotImplementedError):
            await provider.img2img(Img2ImgRequest(prompt="test"))


class TestReplicateProvider:
    """Tests for Replicate provider (Flux models — txt2img only)."""

    def test_supports_img2img(self) -> None:
        provider = ReplicateProvider(settings=None)
        # Flux models are txt2img only
        assert provider.supports_img2img is False

    @pytest.mark.asyncio
    async def test_generate_requires_api_token(self) -> None:
        provider = ReplicateProvider(settings=None)
        # generate() is a real implementation that requires an API token
        with pytest.raises(ValueError, match="Replicate API token not configured"):
            await provider.generate(ImageRequest(prompt="test"))

    @pytest.mark.asyncio
    async def test_img2img_raises_not_implemented(self) -> None:
        provider = ReplicateProvider(settings=None)
        with pytest.raises(NotImplementedError):
            await provider.img2img(Img2ImgRequest(prompt="test"))


class TestOpenAIImageProvider:
    """Tests for OpenAI DALL-E stub provider."""

    def test_no_img2img_support(self) -> None:
        provider = OpenAIImageProvider(settings=None)
        assert provider.supports_img2img is False

    @pytest.mark.asyncio
    async def test_generate_raises_not_implemented(self) -> None:
        provider = OpenAIImageProvider(settings=None)
        with pytest.raises(NotImplementedError):
            await provider.generate(ImageRequest(prompt="test"))

    @pytest.mark.asyncio
    async def test_img2img_raises_not_implemented(self) -> None:
        provider = OpenAIImageProvider(settings=None)
        with pytest.raises(NotImplementedError):
            await provider.img2img(Img2ImgRequest(prompt="test"))


class TestHuggingFaceSpaceProvider:
    """Tests for HuggingFace Space provider."""

    def test_no_img2img_support(self) -> None:
        provider = HuggingFaceSpaceProvider(settings=None)
        assert provider.supports_img2img is False

    @pytest.mark.asyncio
    async def test_img2img_raises_not_supported(self) -> None:
        provider = HuggingFaceSpaceProvider(settings=None)
        with pytest.raises(NotImplementedError, match="does not support img2img"):
            await provider.img2img(Img2ImgRequest(prompt="test"))

    @pytest.mark.asyncio
    async def test_generate_returns_image_from_filepath(self, tmp_path) -> None:
        """Test generate() with gradio returning a local file path dict."""
        fake_image = tmp_path / "fake_image.png"
        fake_image.write_bytes(b"fake_png_data")

        mock_client = MagicMock()
        mock_client.predict.return_value = ({"path": str(fake_image)}, 12345)

        provider = HuggingFaceSpaceProvider(settings=None)
        provider._client = mock_client

        result = await provider.generate(
            ImageRequest(prompt="a dragon", width=512, height=512, seed=42)
        )

        assert isinstance(result, GeneratedImage)
        assert result.image_data == b"fake_png_data"
        assert result.width == 512
        assert result.height == 512
        assert result.provider == "hf-space"
        assert result.model == "mrfakename/Z-Image-Turbo"
        assert result.seed == 12345
        assert result.metadata == {"num_inference_steps": 9}

        # Verify predict called with correct positional args + api_name
        mock_client.predict.assert_called_once_with(
            "a dragon",  # prompt
            512,         # height
            512,         # width
            9,           # num_inference_steps (default)
            42,          # seed
            False,       # randomize_seed (seed was provided)
            api_name="/generate_image",
        )

    @pytest.mark.asyncio
    async def test_generate_handles_string_path(self, tmp_path) -> None:
        """Test generate() with gradio returning a plain string path."""
        fake_image = tmp_path / "img.png"
        fake_image.write_bytes(b"string_path_data")

        mock_client = MagicMock()
        mock_client.predict.return_value = (str(fake_image), 777)

        provider = HuggingFaceSpaceProvider(settings=None)
        provider._client = mock_client

        result = await provider.generate(ImageRequest(prompt="test", seed=1))
        assert result.image_data == b"string_path_data"
        assert result.seed == 777

    @pytest.mark.asyncio
    async def test_generate_randomizes_seed_when_none(self, tmp_path) -> None:
        """Test that seed=None triggers randomize_seed=True."""
        fake_image = tmp_path / "img.png"
        fake_image.write_bytes(b"data")

        mock_client = MagicMock()
        mock_client.predict.return_value = ({"path": str(fake_image)}, 99999)

        provider = HuggingFaceSpaceProvider(settings=None)
        provider._client = mock_client

        result = await provider.generate(ImageRequest(prompt="test"))

        # 6th positional arg is randomize_seed
        call_args = mock_client.predict.call_args[0]
        assert call_args[5] is True
        assert result.seed == 99999

    @pytest.mark.asyncio
    async def test_generate_uses_custom_settings(self, tmp_path) -> None:
        """Test that settings override defaults for space_id and steps."""
        fake_image = tmp_path / "img.png"
        fake_image.write_bytes(b"data")

        mock_client = MagicMock()
        mock_client.predict.return_value = ({"path": str(fake_image)}, 42)

        settings = Settings(
            database_url="sqlite+aiosqlite:///:memory:",
            redis_url="redis://localhost:6379",
            jwt_secret_key="test-secret",
            hf_space_id="custom/my-space",
            hf_space_inference_steps=4,
        )
        provider = HuggingFaceSpaceProvider(settings=settings)
        provider._client = mock_client

        result = await provider.generate(ImageRequest(prompt="test", seed=1))

        assert result.model == "custom/my-space"
        assert result.metadata == {"num_inference_steps": 4}
        # Verify steps=4 was passed
        call_args = mock_client.predict.call_args[0]
        assert call_args[3] == 4

    def test_lazy_client_creation(self) -> None:
        """Test that Gradio Client is created lazily on first use."""
        provider = HuggingFaceSpaceProvider(settings=None)
        assert provider._client is None

        with patch("aiwebnovel.images.provider._GradioClient") as MockClient:
            MockClient.return_value = MagicMock()
            client = provider._get_client()
            MockClient.assert_called_once_with(
                "mrfakename/Z-Image-Turbo", token=None, verbose=False
            )
            # Second call returns cached client
            client2 = provider._get_client()
            assert client is client2
            MockClient.assert_called_once()  # not called again

    def test_lazy_client_with_token(self) -> None:
        """Test that hf_token is passed to Gradio Client."""
        settings = Settings(
            database_url="sqlite+aiosqlite:///:memory:",
            redis_url="redis://localhost:6379",
            jwt_secret_key="test-secret",
            hf_token="hf_test_token_123",
        )
        provider = HuggingFaceSpaceProvider(settings=settings)

        with patch("aiwebnovel.images.provider._GradioClient") as MockClient:
            MockClient.return_value = MagicMock()
            provider._get_client()
            MockClient.assert_called_once_with(
                "mrfakename/Z-Image-Turbo", token="hf_test_token_123", verbose=False
            )


class TestGetImageProvider:
    """Tests for the factory function."""

    def test_returns_comfyui_by_default(self, test_settings: Settings) -> None:
        test_settings.image_provider = "comfyui"
        provider = get_image_provider(test_settings)
        assert isinstance(provider, ComfyUIProvider)

    def test_returns_replicate(self, test_settings: Settings) -> None:
        test_settings.image_provider = "replicate"
        provider = get_image_provider(test_settings)
        assert isinstance(provider, ReplicateProvider)

    def test_returns_openai(self, test_settings: Settings) -> None:
        test_settings.image_provider = "dall-e-3"
        provider = get_image_provider(test_settings)
        assert isinstance(provider, OpenAIImageProvider)

    def test_returns_hf_space(self, test_settings: Settings) -> None:
        test_settings.image_provider = "hf-space"
        provider = get_image_provider(test_settings)
        assert isinstance(provider, HuggingFaceSpaceProvider)

    def test_unknown_provider_raises(self, test_settings: Settings) -> None:
        test_settings.image_provider = "midjourney"
        with pytest.raises(ValueError, match="Unknown image provider"):
            get_image_provider(test_settings)


class TestProtocolConformance:
    """Verify all providers implement the ImageProvider protocol."""

    def test_comfyui_is_image_provider(self) -> None:
        assert isinstance(ComfyUIProvider(settings=None), ImageProvider)

    def test_replicate_is_image_provider(self) -> None:
        assert isinstance(ReplicateProvider(settings=None), ImageProvider)

    def test_openai_is_image_provider(self) -> None:
        assert isinstance(OpenAIImageProvider(settings=None), ImageProvider)

    def test_hf_space_is_image_provider(self) -> None:
        assert isinstance(HuggingFaceSpaceProvider(settings=None), ImageProvider)
