"""Image provider abstraction layer.

Protocol-based interface with stub implementations for ComfyUI,
Replicate, and OpenAI DALL-E, plus a working HuggingFace Space provider.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import structlog

try:
    from gradio_client import Client as _GradioClient
except ImportError:
    _GradioClient = None  # type: ignore[assignment,misc]

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ImageRequest:
    """Request to generate an image from text."""

    prompt: str
    negative_prompt: str = ""
    width: int = 1024
    height: int = 1024
    style_tags: list[str] | None = None
    seed: int | None = None
    model_preference: str | None = None
    reference_image_paths: list[str] | None = None
    extra_params: dict[str, Any] | None = None


@dataclass
class Img2ImgRequest(ImageRequest):
    """Request to generate an image from an existing image + text."""

    source_image_path: str = ""
    strength: float = 0.7


@dataclass
class GeneratedImage:
    """Result from an image generation call."""

    image_data: bytes
    width: int
    height: int
    provider: str
    model: str
    seed: int | None = None
    metadata: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ImageProvider(Protocol):
    """Protocol for image generation backends."""

    async def generate(self, request: ImageRequest) -> GeneratedImage: ...

    async def img2img(self, request: Img2ImgRequest) -> GeneratedImage: ...

    @property
    def supports_img2img(self) -> bool: ...


# ---------------------------------------------------------------------------
# ComfyUI Provider (stub)
# ---------------------------------------------------------------------------


class ComfyUIProvider:
    """Local Stable Diffusion / Flux via ComfyUI API.

    Connects to ComfyUI WebSocket API for txt2img and img2img.
    Stub implementation -- full ComfyUI integration in Phase 5.
    """

    def __init__(self, settings: Any = None) -> None:
        self._settings = settings

    @property
    def supports_img2img(self) -> bool:
        return True

    async def generate(self, request: ImageRequest) -> GeneratedImage:
        raise NotImplementedError(
            "ComfyUI provider is not yet implemented. "
            "Use AIWN_IMAGE_PROVIDER=replicate (with AIWN_REPLICATE_API_TOKEN) "
            "or AIWN_IMAGE_PROVIDER=hf-space instead."
        )

    async def img2img(self, request: Img2ImgRequest) -> GeneratedImage:
        raise NotImplementedError(
            "ComfyUI provider is not yet implemented. "
            "Use AIWN_IMAGE_PROVIDER=replicate or AIWN_IMAGE_PROVIDER=hf-space instead."
        )


# ---------------------------------------------------------------------------
# Replicate Provider (stub)
# ---------------------------------------------------------------------------


class ReplicateProvider:
    """Replicate API for cloud image generation.

    Uses httpx to call Replicate's HTTP API. Supports Flux models
    (flux-schnell for fast/cheap, flux-dev for high quality).
    """

    _BASE_URL = "https://api.replicate.com/v1"

    def __init__(
        self, settings: Any = None, api_token_override: str | None = None,
    ) -> None:
        self._settings = settings
        self._api_token_override = api_token_override

    @property
    def supports_img2img(self) -> bool:
        return False  # Flux models are txt2img only

    @property
    def _api_token(self) -> str:
        # BYOK override takes precedence
        if self._api_token_override:
            return self._api_token_override
        token = getattr(self._settings, "replicate_api_token", "")
        if not token:
            raise ValueError(
                "Replicate API token not configured. "
                "Set AIWN_REPLICATE_API_TOKEN environment variable."
            )
        return token

    @property
    def _model(self) -> str:
        return getattr(
            self._settings, "replicate_model", "black-forest-labs/flux-schnell"
        )

    @property
    def _poll_interval(self) -> float:
        return getattr(self._settings, "replicate_poll_interval", 0.5)

    @property
    def _timeout(self) -> float:
        return getattr(self._settings, "replicate_timeout", 120.0)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
            "Prefer": "wait",
        }

    async def generate(self, request: ImageRequest) -> GeneratedImage:
        import httpx

        # Build input payload — Flux models use these params
        model_input: dict[str, Any] = {
            "prompt": request.prompt,
            "width": request.width,
            "height": request.height,
            "num_outputs": 1,
            "output_format": "png",
        }
        if request.seed is not None:
            model_input["seed"] = request.seed
        if request.negative_prompt:
            model_input["negative_prompt"] = request.negative_prompt

        # Merge extra_params (allows style guide overrides)
        if request.extra_params:
            model_input.update(request.extra_params)

        # Aspect ratio: Flux prefers aspect_ratio over explicit w/h
        # Map common dimensions to aspect ratios
        ar = _dimensions_to_aspect_ratio(request.width, request.height)
        if ar:
            model_input["aspect_ratio"] = ar
            model_input.pop("width", None)
            model_input.pop("height", None)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            # Create prediction via the models endpoint (auto-selects latest version)
            resp = await client.post(
                f"{self._BASE_URL}/models/{self._model}/predictions",
                headers=self._headers(),
                json={"input": model_input},
            )
            resp.raise_for_status()
            prediction = resp.json()

            # If "Prefer: wait" worked, status is already succeeded
            # Otherwise poll until terminal state
            poll_url = prediction.get("urls", {}).get("get", "")
            elapsed = 0.0
            while prediction.get("status") not in ("succeeded", "failed", "canceled"):
                await asyncio.sleep(self._poll_interval)
                elapsed += self._poll_interval
                if elapsed > self._timeout:
                    raise TimeoutError(
                        f"Replicate prediction timed out after {self._timeout}s"
                    )
                poll_resp = await client.get(poll_url, headers=self._headers())
                poll_resp.raise_for_status()
                prediction = poll_resp.json()

            if prediction["status"] != "succeeded":
                error = prediction.get("error", "Unknown error")
                raise RuntimeError(f"Replicate prediction failed: {error}")

            # Download the output image
            output = prediction.get("output")
            if isinstance(output, list):
                image_url = output[0]
            else:
                image_url = str(output)

            img_resp = await client.get(image_url)
            img_resp.raise_for_status()
            image_data = img_resp.content

        used_seed = (
            prediction.get("output_metadata", {}).get("seed")
            or request.seed
        )

        logger.info(
            "replicate_image_generated",
            model=self._model,
            width=request.width,
            height=request.height,
            prediction_id=prediction.get("id"),
            predict_time=prediction.get("metrics", {}).get("predict_time"),
        )

        return GeneratedImage(
            image_data=image_data,
            width=request.width,
            height=request.height,
            provider="replicate",
            model=self._model,
            seed=int(used_seed) if used_seed is not None else None,
            metadata={
                "prediction_id": prediction.get("id"),
                "predict_time": prediction.get("metrics", {}).get("predict_time"),
            },
        )

    async def img2img(self, request: Img2ImgRequest) -> GeneratedImage:
        raise NotImplementedError(
            "Replicate Flux models do not support img2img"
        )


# ---------------------------------------------------------------------------
# Replicate helpers
# ---------------------------------------------------------------------------


def _dimensions_to_aspect_ratio(width: int, height: int) -> str | None:
    """Map pixel dimensions to Flux aspect_ratio string, or None."""
    _MAP = {
        (1024, 1024): "1:1",
        (1024, 576): "16:9",
        (576, 1024): "9:16",
        (1024, 768): "4:3",
        (768, 1024): "3:4",
        (1024, 683): "3:2",
        (683, 1024): "2:3",
    }
    return _MAP.get((width, height))


# ---------------------------------------------------------------------------
# OpenAI DALL-E Provider (stub)
# ---------------------------------------------------------------------------


class OpenAIImageProvider:
    """DALL-E 3 via OpenAI API.

    txt2img only (no img2img support).
    Stub implementation -- full OpenAI integration in Phase 5.
    """

    def __init__(self, settings: Any = None) -> None:
        self._settings = settings

    @property
    def supports_img2img(self) -> bool:
        return False

    async def generate(self, request: ImageRequest) -> GeneratedImage:
        raise NotImplementedError(
            "OpenAI DALL-E provider is not yet implemented. "
            "Use AIWN_IMAGE_PROVIDER=replicate (with AIWN_REPLICATE_API_TOKEN) "
            "or AIWN_IMAGE_PROVIDER=hf-space instead."
        )

    async def img2img(self, request: Img2ImgRequest) -> GeneratedImage:
        raise NotImplementedError(
            "OpenAI DALL-E does not support img2img."
        )


# ---------------------------------------------------------------------------
# HuggingFace Space Provider
# ---------------------------------------------------------------------------


class HuggingFaceSpaceProvider:
    """Image generation via HuggingFace Gradio Spaces.

    Uses gradio_client to call hosted Gradio Spaces for txt2img generation.
    Default Space: mrfakename/Z-Image-Turbo (Tongyi-MAI/Z-Image-Turbo model).

    The Space accepts: prompt, height, width, num_inference_steps, seed,
    randomize_seed. Returns (image_filepath, used_seed).
    """

    def __init__(self, settings: Any = None) -> None:
        self._settings = settings
        self._client: Any = None

    @property
    def supports_img2img(self) -> bool:
        return False

    @property
    def _space_id(self) -> str:
        return getattr(self._settings, "hf_space_id", "mrfakename/Z-Image-Turbo")

    @property
    def _inference_steps(self) -> int:
        return getattr(self._settings, "hf_space_inference_steps", 9)

    def _get_client(self) -> Any:
        """Lazily create and cache the Gradio client."""
        if self._client is None:
            if _GradioClient is None:
                raise ImportError(
                    "gradio_client is required for HuggingFace Space provider. "
                    "Install with: pip install gradio-client"
                )
            hf_token = getattr(self._settings, "hf_token", None) or None
            self._client = _GradioClient(
                self._space_id, token=hf_token, verbose=False
            )
        return self._client

    async def generate(self, request: ImageRequest) -> GeneratedImage:
        client = self._get_client()

        seed = request.seed if request.seed is not None else 42
        randomize_seed = request.seed is None

        result = await asyncio.to_thread(
            client.predict,
            request.prompt,
            request.height,
            request.width,
            self._inference_steps,
            seed,
            randomize_seed,
            api_name="/generate_image",
        )

        image_result, used_seed = result

        # gradio_client returns either a filepath str or a dict with path/url
        if isinstance(image_result, dict):
            image_path = image_result.get("path") or image_result.get("url", "")
        else:
            image_path = str(image_result)

        path = Path(image_path)
        if path.exists():
            image_data = path.read_bytes()
        else:
            # Remote URL — download it
            import httpx

            async with httpx.AsyncClient() as http:
                resp = await http.get(image_path)
                resp.raise_for_status()
                image_data = resp.content

        logger.info(
            "hf_space_image_generated",
            space_id=self._space_id,
            width=request.width,
            height=request.height,
            steps=self._inference_steps,
            seed=int(used_seed),
        )

        return GeneratedImage(
            image_data=image_data,
            width=request.width,
            height=request.height,
            provider="hf-space",
            model=self._space_id,
            seed=int(used_seed),
            metadata={"num_inference_steps": self._inference_steps},
        )

    async def img2img(self, request: Img2ImgRequest) -> GeneratedImage:
        raise NotImplementedError(
            "HuggingFace Space provider does not support img2img"
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def is_image_provider_configured(settings: Any) -> bool:
    """Check whether image generation is enabled and the provider is usable.

    Returns True only when ``image_enabled`` is True AND the selected
    provider has the credentials / dependencies it needs to actually
    generate images.  Stub-only providers (ComfyUI, OpenAI) always
    return False since they raise NotImplementedError.
    """
    if not getattr(settings, "image_enabled", False):
        return False

    provider_name = getattr(settings, "image_provider", "comfyui")

    if provider_name == "replicate":
        return bool(getattr(settings, "replicate_api_token", ""))
    elif provider_name == "hf-space":
        # HF Space works without a token (public spaces); just needs gradio_client
        return _GradioClient is not None
    elif provider_name in ("comfyui", "dall-e-3", "openai"):
        # These are stubs — not yet implemented
        return False
    else:
        return False


def get_image_provider(
    settings: Any,
    model_override: str | None = None,
    api_token: str | None = None,
) -> ImageProvider:
    """Factory function: return the configured image provider.

    Args:
        settings: Application settings with ``image_provider`` attribute.
        model_override: Optional provider name from ArtStyleGuide.model_preference
            that overrides the default ``settings.image_provider``.

    Returns:
        An ImageProvider instance.

    Raises:
        ValueError: If the provider name is unknown.
    """
    provider_name = model_override or getattr(settings, "image_provider", "comfyui")

    if provider_name == "comfyui":
        return ComfyUIProvider(settings)
    elif provider_name == "replicate":
        return ReplicateProvider(settings, api_token_override=api_token)
    elif provider_name in ("dall-e-3", "openai"):
        return OpenAIImageProvider(settings)
    elif provider_name == "hf-space":
        return HuggingFaceSpaceProvider(settings)
    else:
        msg = f"Unknown image provider: {provider_name!r}"
        raise ValueError(msg)
