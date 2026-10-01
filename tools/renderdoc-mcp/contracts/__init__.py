"""Wire contracts shared by the modern server and the ABI-compatible worker."""
VERSION = "0.3.2"
PROTOCOL_VERSIONS = ("2025-06-18", "2024-11-05")


class ToolError(Exception):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code, self.details = code, details

    def payload(self):
        return {"code": self.code, "message": str(self), "details": self.details}
