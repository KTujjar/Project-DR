"""Interpretation adapters intentionally have no reference to the control system."""


class UnconfiguredAdapter:
    async def interpret(self, snapshot):
        return {"status": "unconfigured", "title": "No AI model configured", "text": "The sensor capture is saved. No image analysis was performed and no movement command was generated.", "source": "system_status"}


class MockAdapter:
    async def interpret(self, snapshot):
        return {"status": "demonstration", "title": "Simulated perception response",
                "text": "This is a demonstration, not an AI observation. The simulated scan contains nearby surfaces; the camera is an illustrated placeholder. Connect a vision-language adapter to analyze actual captures.", "source": "mock_response"}
