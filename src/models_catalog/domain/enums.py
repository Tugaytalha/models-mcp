from enum import Enum


class StrEnum(str, Enum):
    def __str__(self) -> str:
        return self.value

    @classmethod
    def values(cls) -> list[str]:
        return [m.value for m in cls]


class ServiceType(StrEnum):
    LLM_CHAT = "llm_chat"
    LLM_COMPLETION = "llm_completion"
    EMBEDDING = "embedding"
    RERANKER = "reranker"
    CLASSIFIER = "classifier"
    VISION = "vision"
    SPEECH_ASR = "speech_asr"
    SPEECH_TTS = "speech_tts"
    OCR = "ocr"
    CUSTOM = "custom"


class ApiStyle(StrEnum):
    OPENAI_COMPATIBLE = "openai_compatible"
    TEI = "tei"
    CUSTOM = "custom"


class Location(StrEnum):
    BANKA = "banka"
    ATG = "atg"


class Environment(StrEnum):
    DEV = "dev"
    UAT = "uat"
    PROD = "prod"


class Platform(StrEnum):
    ARGOCD_K8S = "argocd_k8s"
    DEV_GPU = "dev_gpu"
    VM = "vm"
    DOCKER = "docker"
    OTHER = "other"


class Status(StrEnum):
    ACTIVE = "active"
    MAINTENANCE = "maintenance"
    DEPRECATED = "deprecated"


class AuditAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    RESTORE = "restore"


class Source(StrEnum):
    MCP = "mcp"
    API = "api"
    WEB = "web"


LLM_TYPES = {ServiceType.LLM_CHAT.value, ServiceType.LLM_COMPLETION.value, ServiceType.VISION.value}
