"""
tests/unit/test_providers.py — Unit tests for BaseProvider, capability validation, and modality routing.
"""

import unittest

from harness.providers.base import BaseProvider, Capability, UnsupportedCapabilityError
from harness.providers.llamacpp import LlamaCppProvider
from harness.providers.comfyui import ComfyUIProvider


class TestProvidersAndCapabilities(unittest.TestCase):
    def setUp(self):
        self.llama_prov = LlamaCppProvider(
            base_url="http://127.0.0.1:8081",
            api_key="test-key",
            model_alias="qwen3.8-27b",
        )
        self.comfy_prov = ComfyUIProvider(server_url="http://127.0.0.1:8188")

    def test_llamacpp_capabilities(self):
        caps = self.llama_prov.get_capabilities()
        self.assertIn(Capability.TEXT, caps)
        self.assertIn(Capability.CODE_TOOLS, caps)
        self.assertNotIn(Capability.IMAGE_GEN, caps)
        self.assertNotIn(Capability.VIDEO_GEN, caps)

    def test_llamacpp_rejects_image_gen_with_guidance(self):
        with self.assertRaises(UnsupportedCapabilityError) as ctx:
            self.llama_prov.generate_image(prompt="a sunset")
        err = ctx.exception
        self.assertEqual(err.requested, Capability.IMAGE_GEN)
        self.assertIn("does not support requested capability 'image_gen'", str(err))
        self.assertIn("FREECOMPUTE_IMAGE_SERVER", str(err))

    def test_comfyui_capabilities(self):
        caps = self.comfy_prov.get_capabilities()
        self.assertIn(Capability.IMAGE_GEN, caps)
        self.assertNotIn(Capability.TEXT, caps)
        self.assertNotIn(Capability.CODE_TOOLS, caps)

    def test_comfyui_rejects_text_chat_with_guidance(self):
        with self.assertRaises(UnsupportedCapabilityError) as ctx:
            self.comfy_prov.stream_chat(messages=[])
        err = ctx.exception
        self.assertEqual(err.requested, Capability.TEXT)
        self.assertIn("LlamaCppProvider", str(err))

    def test_comfyui_workflow_generation(self):
        wf = self.comfy_prov.build_qwen_image_workflow(
            prompt="cyberpunk anime girl",
            width=1024,
            height=1024,
            steps=12,
            cfg=4.0,
            seed=42,
        )
        self.assertIn("1", wf)
        self.assertEqual(wf["6"]["inputs"]["width"], 1024)
        self.assertEqual(wf["6"]["inputs"]["height"], 1024)
        self.assertEqual(wf["7"]["inputs"]["steps"], 12)
        self.assertEqual(wf["7"]["inputs"]["seed"], 42)
        self.assertEqual(wf["4"]["inputs"]["text"], "cyberpunk anime girl")


if __name__ == "__main__":
    unittest.main()
